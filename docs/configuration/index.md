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

`source_id: null` 的 region 当前无法完整跑完标准 build，因为 `metadata.sh` 会在 metadata 阶段失败。

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
