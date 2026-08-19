# 构建管线

## 主流程

`scripts/build.sh` 是主编排入口。一次标准 build 的阶段如下：

1. 校验 region、role、YYYYMMDD 和输入 PBF。
2. 将输入 PBF 链接到 `${WORKDIR}/staging/${SESSION}/source.osm.pbf`。
3. `scripts/tags-filter.sh` 按 layer 运行 `osmium tags-filter`。
4. `scripts/export.sh` 按 layer 运行 `osmium export`，输出 GeoJSONSeq。
5. `scripts/normalize.sh` 过滤并归一化 properties。
6. `scripts/tippecanoe.sh` 按 role 生成 PMTiles。
7. `scripts/metadata.sh` 写入 PMTiles metadata。
8. `scripts/manifest.sh` 生成 manifest。
9. `scripts/attribution.sh` 生成 attribution。
10. `scripts/verify.sh` 校验 PMTiles 和伴随文件。
11. 写出 `.sha512` sidecar。

当 `make build GLYPH=1` 或直接运行 `make glyph`/`make style` 时，会额外执行离线文字资源阶段：

1. `scripts/glyph.sh` 读取 `config/glyphs.yaml`，调用本地 `build-glyphs` 生成 MapLibre glyph PBF。
2. `scripts/style.sh` 读取 `config/styles.yaml`，生成带 `glyphs` URL 模板的 MapLibre style JSON。
3. `scripts/pack.sh` 在这些产物已存在时，把 style 和 glyphs 一起复制进 bundle。
4. `scripts/prepare-import.sh` 在这些产物已存在时，把 style 和 glyphs 一起复制进 import 包，供 `huavd-map` 安装后服务 `/api/v1/map/glyphs/{locale}/{fontstack}/{range}.pbf`。

DEM 资产使用独立入口，不参与 OSM PBF 矢量构建：

1. `scripts/fetch-dem.sh` 从已授权的本地或内网 mirror 准备 DEM 输入，不默认访问未确认公网 URL。
2. `scripts/build-dem.sh` 接受已授权 DEM PMTiles、MBTiles 或瓦片目录，标准化输出 `${WORKDIR}/outputs/{region-slug}-{yyyymmdd}.dem.pmtiles`。
3. DEM metadata 必须包含 `dem-encoding`、`huavd:vertical-datum`、`bounds` 和 `attribution`。
4. `scripts/verify.sh --role=dem --strict` 校验 raster tile type、metadata、bounds、manifest 和 SHA512。
5. `scripts/pack.sh --role=all` 会把 DEM 作为 `install.json.offline_maps[]` 中的 `dem-raster` 单资产，并在 bundle assets 中关联；不得新增私有顶层 size 字段。

## 输入输出

默认工作目录：

```text
/tmp/huavd-map-build
```

关键路径：

| 路径 | 内容 |
| :--- | :--- |
| `${WORKDIR}/mirror/` | Geofabrik PBF 和 MD5 |
| `${WORKDIR}/cache/tags-filter/` | per-layer 过滤后的 PBF |
| `${WORKDIR}/cache/configs/` | YAML 转 JSON 缓存 |
| `${WORKDIR}/staging/${SESSION}/layers/` | per-layer GeoJSONSeq |
| `${WORKDIR}/outputs/` | PMTiles、manifest、attribution、bundle、import archive |

产物命名：

```text
{region-slug}-{yyyymmdd}.{role}.pmtiles
{region-slug}-{yyyymmdd}.{role}.pmtiles.sha512
{region-slug}-{yyyymmdd}.{role}.manifest.json
{region-slug}-{yyyymmdd}.{role}.attribution.json
{region-slug}-{yyyymmdd}.glyphs/
{region-slug}-{yyyymmdd}.style.json
{region-slug}-{yyyymmdd}.style.json.sha512
{region-slug}-{yyyymmdd}.import.zip
{region-slug}-{yyyymmdd}.import.tar.gz
{region-slug}-{yyyymmdd}.bundle.tar.gz
{region-slug}-{yyyymmdd}.bundle.zip
```

## Role

`ROLE=base` 生成基础地图 PMTiles。`ROLE=building` 生成建筑专用 PMTiles。`ROLE=both` 会依次处理可构建的 role。

`ROLE=dem` 只处理 DEM PMTiles 四件套。`ROLE=all` 用于打包或校验 base、building 和 dem 三类资产；其中 building 仍是可选派生产物，DEM 只有在显式请求或 region `huavd.dem_required=true` 时才作为必需产物。

building role 只有在 `config/regions.yaml` 中同时满足以下配置时才启用：

```yaml
huavd:
  asset_role: "building-vector"
  source_type: "derived-building"
```

否则 `ROLE=both` 会跳过 building 并输出 warning。

## 验证范围

`scripts/verify.sh` 当前校验：

- PMTiles magic、spec version、compression、tile type、zoom。
- root directory 是否完整位于前 16KiB。
- PMTiles metadata JSON 是否可读。
- metadata bounds 是否与 header bounds 匹配。
- `--strict` 模式下,metadata 是否包含文字标注必需字段:`place_label.place`、`poi_label.amenity`、`poi_label.shop`、`poi_label.tourism`、`transport_label.public_transport`。
- `--strict` 模式下,配置是否保留所有 label 可用的 `name:zh` 字段,防止中文 locale 下被 `name:en` 抢先显示。
- `--strict` 模式下,metadata 是否包含底色 / 建筑样式必需字段:`landuse.landuse`、`natural_a.natural`、`leisure_a.leisure`、`building.building`,并校验 `building` metadata minzoom 为 12。
- `--strict` 模式下,metadata 是否包含铁路样式必需字段:`railway.railway`、`railway.bridge`、`railway.tunnel`。
- `--role=dem` 时,PMTiles `tile_type` 必须是 raster (`2`/`3`/`4`/`5`),metadata 必须包含合法 `dem-encoding`、`huavd:vertical-datum`、`attribution` 和与 header 一致的 bounds。
- manifest `output.size_bytes` 是否匹配文件大小。
- manifest `output.sha512` 和 sidecar SHA512 是否匹配。

它不校验瓦片内容、每个 zoom/layer 的实际覆盖情况，也不做 manifest JSON Schema 校验。
