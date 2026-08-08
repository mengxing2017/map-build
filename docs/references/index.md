# 契约与外部工具

## 外部工具

| 工具 | 用途 |
| :--- | :--- |
| devbox | 开发环境与工具声明 |
| osmium | OSM PBF tags-filter、export |
| tippecanoe | GeoJSONSeq 到 PMTiles |
| pmtiles | PMTiles metadata edit、header show |
| build-glyphs | 从字体生成 MapLibre glyph PBF；setup 通过 cargo 安装 |
| fonttools | 字体文件检查和调试 |
| jq/yq | JSON/YAML 解析 |
| wget | Geofabrik 和 release 下载 |

`versatiles_glyphs` 由 cargo 安装，devbox 通过 `rustup` 提供 cargo。setup 会在 `$HOME/.local/bin` 写入 `build-glyphs` wrapper；构建机需要保证 `$HOME/.local/bin` 和 `$CARGO_HOME/bin` 在 `PATH` 中。

## 外部数据源

Geofabrik PBF 和 MD5 地址配置在 `config/regions.yaml`。`scripts/fetch.sh` 使用 `wget --timestamping` 下载到 `${WORKDIR}/mirror` 并执行 `md5sum -c`。

## PMTiles 约束

当前校验以 PMTiles v3 为目标：

- magic 为 `PMTiles`。
- spec version 为 `3`。
- tile type 为 `1`，即 MVT。
- internal compression 与 tile compression 为 gzip。
- root directory 必须完整位于文件前 16KiB 内。

## MapLibre glyph 约束

`scripts/style.sh` 生成 MapLibre style v8 JSON。style 的 `glyphs` 字段必须是 URL 模板，并保留 `{fontstack}` 和 `{range}` 占位；本项目默认使用：

```text
huavd-map://glyphs/{locale}/{fontstack}/{range}.pbf
```

`scripts/glyph.sh` 会按 locale/fontstack 生成对应目录和 PBF，并为每个 PBF 写 `.sha512` sidecar。`scripts/pack.sh` 只在 glyph/style 产物已经存在时将它们复制进 bundle。

参考：

- MapLibre Style Spec: `glyphs`，https://maplibre.org/maplibre-style-spec/glyphs/
- Noto fonts，https://github.com/notofonts

## HUAVD 契约

本项目生成的 manifest 和 metadata 会写入 HUAVD 字段：

```text
huavd:source-id
huavd:asset-role
huavd:build-time
huavd:region
huavd:data-license
```

地图产品契约和跨服务边界以 HUAVD 总体文档为真值源；本项目只负责离线地图构建产物。
