# 配置索引

## regions.yaml

`config/regions.yaml` 是 region catalog 和 HUAVD metadata 映射。

关键字段：

| 字段 | 说明 |
| :--- | :--- |
| `regions[].id` | region id，例如 `china/guangxi` |
| `regions[].slug` | 文件名和 session 使用的 slug，例如 `china-guangxi` |
| `regions[].geofabrik.pbf_url` | PBF 下载地址 |
| `regions[].geofabrik.md5_url` | MD5 下载地址 |
| `regions[].geofabrik.basename` | mirror 中的 PBF 文件名 |
| `regions[].huavd.source_id` | HUAVD source id，metadata 阶段需要 |
| `regions[].huavd.asset_role` | `base-vector` 或 `building-vector` |
| `regions[].huavd.source_type` | `osm-pbf` 或 `derived-building` |
| `regions[].huavd.package_version_template` | manifest package version 模板 |
| `regions[].huavd.dem_required` | 可选;为 `true` 时 DEM 打包 / 校验缺失会失败 |
| `regions[].huavd.dem_source_id` | 可选;引用 `config/dem.yaml` 中已授权 DEM source |

`source_id: null` 的 region 当前无法完整跑完标准 build，因为 `metadata.sh` 会在 metadata 阶段失败。

## dem.yaml

`config/dem.yaml` 定义 DEM source、输出编码、授权说明、zoom 范围、tile size 和垂直基准。默认配置只指向本地或内网授权 mirror,不得把未确认授权、测绘、分发和出口合规的公网 DEM URL 作为生产默认。

关键字段：

| 字段 | 说明 |
| :--- | :--- |
| `dem.default_source` | 默认 DEM source id |
| `dem.default_encoding` | 默认输出编码,必须在 `allowed_encodings` 中 |
| `dem.allowed_encodings[]` | 允许的 DEM encoding:`mapbox-terrain-rgb`、`terrarium`、`heightmap-u16` |
| `dem.sources[].id` | 稳定 source id,由 region `huavd.dem_source_id` 引用 |
| `dem.sources[].output_encoding` | 输出到 PMTiles metadata 的 `dem-encoding` |
| `dem.sources[].vertical_datum` | 高程垂直基准,写入 `huavd:vertical-datum` |
| `dem.sources[].attribution` | DEM attribution,进入 PMTiles metadata 和 attribution JSON |
| `dem.sources[].data_license` | DEM 数据许可说明 |
| `dem.sources[].uri` | 本地或内网 mirror 入口;公网 URL 只允许在完成合规确认后显式配置 |

## layers.yaml

`config/layers.yaml` 定义 source layer、OSM tag 过滤规则和最终字段。

关键字段：

| 字段 | 说明 |
| :--- | :--- |
| `source_layers.*.order` | layer 顺序 |
| `source_layers.*.tags_filter` | 传给 `osmium tags-filter` 的条件 |
| `source_layers.*.include_tags` | 期望导出的 OSM tag |
| `source_layers.*.final_fields` | normalize 后保留的字段和类型 |

当前 `include_tags` 同时维护在 `config/layers.yaml` 和 `config/export-config/*.json`。两边目前一致，但修改时需要同步。

名称字段必须同时保留 `name`、`name:zh-Hans`、`name:zh`、`name:en`、`name:ja` 和 `name:ko`。`normalize.sh` 会按 region 的 `name_locale_priority` 或全局 `name_coalesce_order` 把优先语言写入通用 `name`;中文顺序必须是 `name:zh-Hans`、`name:zh`、`name`、`name:en`,避免原始中文 `name` 被 `name:en` 覆盖。

## export-config

`config/export-config/*.json` 是 `osmium export -c` 的配置文件。文件名必须与 layer id 匹配，例如：

```text
config/export-config/road.json
config/export-config/building.json
```

`scripts/export.sh` 会把这些文件复制到 `${WORKDIR}/staging/${SESSION}/export-config/` 后再执行 `osmium export`。

## tippecanoe.yaml

`config/tippecanoe.yaml` 定义 tippecanoe 默认参数、高密度区域覆盖和 building role 参数。

`scripts/tippecanoe.sh` 当前传入全局 `-Z/-z`，没有传 per-layer minzoom/maxzoom。`metadata.vector_layers[].minzoom/maxzoom` 来自 `scripts/lib/config.sh` 的配置计算，可能不等于 tippecanoe 实际瓦片内每个 layer 的出现范围。

base role 的 `building` metadata minzoom 当前为 12,用于 HMI 在常用 zoom 下显示低透明度建筑底色。实际 tippecanoe base 打包仍使用全局 `defaults.min_zoom`;如需物理 per-layer minzoom,必须另行改造 tippecanoe 管线并重新评估 tile size / drop 策略。

底色和铁路相关 layer 必须保留分类字段:`landuse.final_fields.landuse`、`natural_a.final_fields.natural`、`leisure_a.final_fields.leisure`、`building.final_fields.building` 和 `railway.final_fields.railway`。HMI style-loader 直接使用这些字段做 MapLibre `match` 表达式；铁路桥梁 / 隧道样式使用 `railway.final_fields.bridge` 和 `railway.final_fields.tunnel`。

## glyphs.yaml

`config/glyphs.yaml` 定义离线 MapLibre glyph 生成输入。`scripts/glyph.sh` 会把 YAML 转为 JSON 后读取该配置，并调用 `generator.command` 指定的本地命令。

关键字段：

| 字段 | 说明 |
| :--- | :--- |
| `generator.command` | glyph 生成器命令，默认 `build-glyphs`，必须存在于 `PATH` |
| `generator.url_template` | glyph 资源 URL 模板，必须保留 `{fontstack}` 和 `{range}.pbf` |
| `fonts[].id` | locale 引用字体时使用的稳定 id |
| `fonts[].fontstack` | 输出目录名，也是 MapLibre style 中 `text-font` 使用的 fontstack 名称 |
| `fonts[].file` | 相对仓库根目录的字体文件路径 |
| `ranges[]` | 期望的 glyph codepoint 范围说明；实际切片行为由 `build-glyphs` 生成器决定 |
| `locales[].tag` | locale 标签，例如 `zh-Hans`、`en`、`ja`、`ko` |
| `locales[].fonts` | 该 locale 需要生成的字体 id 列表 |

默认配置依赖 `fonts/NotoSans-Regular.ttf` 和 `fonts/NotoSansCJK*.otf`。这些字体不是脚本自动下载项，准备构建机时需要单独放置，并确认再分发许可。

## styles.yaml

`config/styles.yaml` 定义生成 MapLibre style JSON 的最小模板。

关键字段：

| 字段 | 说明 |
| :--- | :--- |
| `source.id` | style 中的 vector source id |
| `source.url` | 默认 PMTiles URL 模板 |
| `glyphs_url` | style 的 `glyphs` URL 模板，必须包含 `{fontstack}` 和 `{range}.pbf` |
| `locales[].tag` | 可生成的 style locale |
| `locales[].name_fields` | symbol 文本字段优先级 |
| `text_layers[]` | 需要渲染文字的 MapLibre symbol layer |
| `text_layers[].font_stack` | MapLibre `text-font` 数组，应与 `glyphs.yaml` 中的 `fonts[].fontstack` 对齐 |

`zh-Hans` 的 `name_fields` 顺序必须是 `name:zh-Hans`、`name:zh`、`name`、`name:en`。其中 `name` 已经由 normalize 阶段按中文优先级回填;如果把 `name:en` 放在 `name` 前面，会造成地图上中文和英文标注混排。

## 配置联动

新增 layer 时通常需要同时修改：

- `config/layers.yaml`
- `config/export-config/{layer}.json`
- `config/tippecanoe.yaml` 的 `defaults.source_layers`
- `scripts/verify.sh` 中 metadata vector layer 数量预期

新增 region 时通常需要同时确认：

- `config/regions.yaml` 的 Geofabrik URL、basename、HUAVD metadata。
- 若使用 polygon fallback，准备 `config/regions/{region-slug}.poly`。

新增或替换字体时通常需要同时确认：

- `config/glyphs.yaml` 的 `fonts[]`、`locales[].fonts` 和实际 `fonts/` 文件路径。
- `config/styles.yaml` 中引用的 `text_layers[].font_stack`。
- 构建机是否已安装 `build-glyphs`，且字体许可允许随离线包分发生成结果。
