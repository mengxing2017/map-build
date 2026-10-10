//! One local XYZ tile per process. Python owns orchestration and cancellation.
use std::{fs, io::Write, num::NonZeroU32, path::PathBuf};

use clap::Parser;
use maplibre_native::{ImageRendererBuilder, ResourceOptions};
use serde_json::{json, Value};

#[derive(Parser, Debug)]
#[command(disable_version_flag = true)]
struct Args {
    #[arg(long)]
    version: bool,
    #[arg(long)]
    self_test: bool,
    #[arg(long)]
    style: Option<PathBuf>,
    #[arg(long)]
    output: Option<PathBuf>,
    #[arg(long)]
    z: Option<u8>,
    #[arg(long)]
    x: Option<u32>,
    #[arg(long)]
    y: Option<u32>,
    #[arg(long, default_value_t = 256)]
    width: u32,
    #[arg(long, default_value_t = 256)]
    height: u32,
}

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Debug)]
struct StageError(u8, String);
impl std::fmt::Display for StageError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.1)
    }
}
impl std::error::Error for StageError {}

fn validate_style(style: &Value) -> Result<()> {
    if style["version"] != 8 {
        return Err("style must have version 8".into());
    }
    let sources = style["sources"]
        .as_object()
        .ok_or("style sources must be an object")?;
    let layers = style["layers"]
        .as_array()
        .ok_or("style layers must be an array")?;
    if style.get("glyphs").is_some() || style.get("sprite").is_some() {
        return Err("glyphs and sprites are not supported by protocol 1".into());
    }
    for layer in layers {
        if layer["type"] == "symbol" {
            return Err("symbol layers are not supported by protocol 1".into());
        }
        if let Some(source) = layer.get("source") {
            if !sources.contains_key(source.as_str().ok_or("layer source must be a string")?) {
                return Err("layer references a missing source".into());
            }
        }
    }
    for source in sources.values() {
        match source["type"].as_str() {
            Some("vector") => {
                if source.get("url").is_some() {
                    return Err("vector source must use explicit local tiles, not url".into());
                }
                let tiles = source["tiles"]
                    .as_array()
                    .ok_or("vector source requires tiles")?;
                if tiles.is_empty() {
                    return Err("vector source tiles must not be empty".into());
                }
                for template in tiles {
                    let template = template.as_str().ok_or("tile template must be a string")?;
                    if !["{z}", "{x}", "{y}"].iter().all(|p| template.contains(p)) {
                        return Err("tile template requires {z}, {x} and {y}".into());
                    }
                    let url = url::Url::parse(template)?;
                    if url.scheme() != "http"
                        || !matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"))
                        || !url.username().is_empty()
                        || url.password().is_some()
                    {
                        return Err("tile source must be unauthenticated loopback HTTP".into());
                    }
                }
            }
            Some("geojson") if source["data"].is_object() => {}
            _ => {
                return Err(
                    "only local vector tiles and inline GeoJSON sources are supported".into(),
                )
            }
        }
    }
    Ok(())
}

fn version() -> Value {
    json!({
        "protocol_version": 1, "engine": "maplibre-native-headless",
        "version": env!("CARGO_PKG_VERSION"), "backend": "vulkan",
        "wrapper_revision": "d5295457f5c0492c2a783becd0d38539b84545bc",
        "core_revision": "a33d3f00fb9dbf9117ce18edd799aa0ca5bcce5b",
        "wrapper_patch_sha256": option_env!("HUAVD_NATIVE_PATCH_SHA256").unwrap_or("unrecorded"),
        "source_sha256": option_env!("HUAVD_NATIVE_SOURCE_SHA256").unwrap_or("unrecorded")
    })
}

fn run(args: Args) -> Result<Value> {
    if args.version {
        return Ok(version());
    }
    let (z, x, y, size, style) = if args.self_test {
        (
            0,
            0,
            0,
            512,
            json!({"version":8,"sources":{},"layers":[
                {"id":"background","type":"background","paint":{"background-color":"#123456"}}
            ]}),
        )
    } else {
        let z = args.z.ok_or("--z is required")?;
        let x = args.x.ok_or("--x is required")?;
        let y = args.y.ok_or("--y is required")?;
        if z > 24 || x >= (1u32 << z) || y >= (1u32 << z) {
            return Err("XYZ coordinate is outside supported extent (z 0..24)".into());
        }
        if args.width != args.height || !matches!(args.width, 256 | 512) {
            return Err("width and height must both be 256 or both be 512".into());
        }
        let path = args.style.as_ref().ok_or("--style is required")?;
        args.output.as_ref().ok_or("--output is required")?;
        let style = serde_json::from_slice(&fs::read(path)?)?;
        (z, x, y, args.width, style)
    };
    validate_style(&style)?;
    // Core clamps map zoom to zero; z0/256 needs a whole-world 512 render.
    let logical_size = if z == 0 { 512 } else { size };
    let dimension = NonZeroU32::new(logical_size).ok_or("zero dimension")?;
    let mut map = ImageRendererBuilder::new()
        .with_resource_options(ResourceOptions::default().with_cache_path(":memory:".into()))
        .with_size(dimension, dimension)
        .with_pixel_ratio(1.0)
        .build_tile_renderer();
    map.load_style_from_json_str(serde_json::to_string(&style)?)
        .wait()
        .map_err(|error| StageError(6, error.to_string()))?;
    let rendered = map
        .render_tile(z, x, y)
        .map_err(|error| StageError(6, error.to_string()))?;
    let pixels = if logical_size == size {
        rendered.as_image().clone()
    } else {
        image::imageops::resize(
            rendered.as_image(),
            size,
            size,
            image::imageops::FilterType::Lanczos3,
        )
    };
    if pixels.dimensions() != (size, size) {
        return Err("native renderer returned unexpected dimensions".into());
    }
    if args.self_test {
        if !pixels.pixels().all(|p| p.0 == [0x12, 0x34, 0x56, 255]) {
            return Err("self-test pixels differ from the expected background".into());
        }
        return Ok(json!({"protocol_version":1,"self_test":"passed","width":size,"height":size}));
    }
    let output = args.output.ok_or("--output is required")?;
    let parent = output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(std::path::Path::new("."));
    fs::create_dir_all(parent)?;
    let name = output
        .file_name()
        .ok_or("output needs a file name")?
        .to_string_lossy();
    let temporary = parent.join(format!(".{name}.native-{}.png", std::process::id()));
    let mut created = false;
    let result = (|| -> Result<()> {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        created = true;
        image::DynamicImage::ImageRgba8(pixels).write_to(&mut file, image::ImageFormat::Png)?;
        file.flush()?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, &output)?;
        Ok(())
    })();
    if result.is_err() && created {
        let _ = fs::remove_file(&temporary);
    }
    result.map_err(|error| StageError(7, error.to_string()))?;
    Ok(json!({"protocol_version":1,"z":z,"x":x,"y":y,"width":size,"height":size,"output":output}))
}

fn main() {
    match run(Args::parse()) {
        Ok(result) => println!("{result}"),
        Err(error) => {
            eprintln!("huavd-native-render: {error}");
            std::process::exit(i32::from(
                error
                    .downcast_ref::<StageError>()
                    .map_or(2, |stage| stage.0),
            ));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_empty_tiles_and_remote_sources_before_native_initialization() {
        let mut style =
            json!({"version":8,"sources":{"base":{"type":"vector","tiles":[]}},"layers":[]});
        assert!(validate_style(&style)
            .unwrap_err()
            .to_string()
            .contains("empty"));
        style["sources"]["base"]["tiles"] = json!(["https://example.invalid/{z}/{x}/{y}.mvt"]);
        assert!(validate_style(&style)
            .unwrap_err()
            .to_string()
            .contains("loopback"));
        style["sources"]["base"]["tiles"] = json!(["http://127.0.0.1:1234/{z}/{x}/{y}.mvt"]);
        assert!(validate_style(&style).is_ok());
    }
}
