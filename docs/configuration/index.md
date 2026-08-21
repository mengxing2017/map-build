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
| `regions[].huavd.asset_role` | region 源数据的默认 vector 资产角色，通常为 `base-vector` 或 `building-vector` |
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

## composites.yaml

`config/composites.yaml` 定义由 source asset 合成并作为标准 `base-vector` 安装的派生产品。它可表达
地级市合成省、省合成国家、国家合成洲以及洲合成世界，目标 region 必须复用
`regions.yaml` 中已登记的地图身份。它不同于 `overviews.yaml`：overview 只生成审核用的
`overview-vector`，composite 会生成可安装的标准资产。

关键字段：

| 字段 | 说明 |
| :--- | :--- |
| `composites[].id` | 稳定派生地图 id，供 `DERIVED_MAP` / `--derived-map` 使用 |
| `target_region` | 目标 region，必须存在于 `regions.yaml` 并已有 `base-vector` 地图身份 |
| `sources[].asset` | `source-assets.yaml` 中登记的输入资产 |
| `sources[].coverage_mode` | 当前为 `union` |
| `layer_profile` | canonical layer contract；当前为 `base-v1` |
| `conflict_policy` | `conflict-policies.yaml` 中的合成规则 |

`source-assets.yaml` 定义 provider、输入、coverage、许可证和 adapter。`inputs.path_template` 只是可选
默认路径；`inputs.path_overrides` 可按 region 指定任意 `.osm.pbf` 文件名，例如
`mirror/taiwan-20200803.osm.pbf`。因此 PBF 命名不依赖 `-latest` 约定。`source-inventory.sh` 校验本地输入
checksum，`adapter-run.sh` 生成 canonical layers，`compose-layers.sh` 写出 conflict policy 的
composition report。timestamp 和 sequence 只用于 lineage，不是合成准入条件。

新国家可由相邻省份的现有地图构成。先在 `regions.yaml` 注册目标，并为它分配稳定的
`huavd.region_id`、`huavd.source_id` 和 `base-vector` 身份；随后使用显式 source asset，而不是要求
目标国家已有 PBF：

```yaml
# source-assets.yaml
assets:
  - id: new-country-neighboring-provinces
    provider: osm-pbf-set
    inputs:
      mode: explicit
      regions: [country-a/province-one, country-b/province-two]
      path_template: null
      path_overrides:
        country-a/province-one: "mirror/province-one-20200803.osm.pbf"
        country-b/province-two: "mirror/province-two-20200815.osm.pbf"
      md5_sidecar: true
    version: "2020-boundary-release"
    coverage: {region: new-country}
    license_ref: odbl-1.0
    adapter: osm-default
    layer_profile: base-v1
    priority: 100
```

```yaml
# composites.yaml
composites:
  - id: new-country-base
    target_region: new-country
    layer_profile: base-v1
    conflict_policy: new-country-base-v1
    sources:
      - asset: new-country-neighboring-provinces
        coverage_mode: union
```

两个文件的日期或版本可以不同。对应的 conflict policy 必须明确重叠边界、重复要素和来源优先级。

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

底色和铁路相关 layer 必须保留分类字段:`landuse.final_fields.landuse`、`natural_a.final_fields.natural`、`natural_a.final_fields.place`、`leisure_a.final_fields.leisure`、`building.final_fields.building`、`railway.final_fields.railway`、`water.final_fields.water`、`water.final_fields.intermittent`、`water.final_fields.place`、`island.final_fields.place`。HMI style-loader 直接使用这些字段做 MapLibre `match` 表达式；铁路桥梁 / 隧道样式使用 `railway.final_fields.bridge` 和 `railway.final_fields.tunnel`。

`place=island` / `place=islet` 的 polygon 由 `island` source-layer 持有,`water` layer 在 `post_filter.exclude.place` 阶段把同名 polygon 排除,避免岛被填成蓝色。`scripts/normalize.sh` 和 `scripts/overview-normalize.sh` 会通用地应用每层 `post_filter.exclude` 与 `post_filter.geometry`：前者按属性排除，后者只保留声明的 GeoJSON geometry 类型。`island` 必须同时允许 `Polygon`、`MultiPolygon` 和 `Point`，以保留节点式岛屿；其它面层只允许 polygonal geometry。

`scripts/island-water-flag.sh` 在 normalize 之后为 `island` 面要素派生 `in_water`（Boolean）标记：判据是"该岛外环的采样顶点 ≥99.9% 落在同一个水体面要素内"（纯算术射线法，无几何库）。客户端必须据此分两层绘制——`in_water` 的岛面画在 `water` 之上（否则会被水体盖住），其余岛面画在绿地图层之下（否则会盖住绿地）；绿地与 `water` 的相对顺序不能改，否则水库/湖面会被绿地染色。该字段通过 `source_layers.island.enrich_fields` 与 `final_fields` 声明，不进入 `include_tags`（它不是 OSM tag）。派生报告写入 `${WORKDIR}/staging/${SESSION}/island_water_report.json`，`scripts/verify.sh` 会校验报告结构、`in_water` 要素数一致、最大面积阈值（1 km²）以及 `water` 图层逐字节未被改写。

`scripts/island-anchor.sh` 随后为每个 `island` **面**要素追加一个面内锚点 `Point`（`island_anchor: true`、`island_area_km2`），属性继承原面要素，面要素原样保留。锚点优先取各部件外环的 shoelace 质心（按面积从大到小），质心落在面外时退回 7×7 网格采样，二者都失败才退回外环顶点（此时 `verify.sh` 会失败，避免静默降级）。客户端应只对 `Point` 标注（`filter: ["==", ["geometry-type"], "Point"]`）：面要素会被裁进它覆盖的每个瓦片、每个瓦片各自计算标注锚点，导致同一座岛的名字重复出现；点要素最多落在相邻 1–2 个瓦片且位置重合，会被碰撞检测收敛为一条。`island_area_km2` 供客户端做大岛/小岛的字号与 zoom 分级（`symbol-sort-key` 也可直接用面积）。派生报告写入 `${WORKDIR}/staging/${SESSION}/island_anchor_report.json`。

`config/export-config/water.json` 必须声明 `area_tags: ["natural=water"]`。河心岛等要素在 OSM 中常作为 `natural=water` multipolygon relation 的**内环（hole）**存在,但内环 way若自带 tag(`leisure=park`、`natural=wetland`、`name` 等),`osmium export` 会把它们当作独立 area 一并导出;这些 polygon 不带 `place` 字段,会绕过上面的 `post_filter.exclude.place`,被当作水面填成水色从而盖住岛屿。限定 `area_tags` 后,只有 `natural=water` 的闭合 way生成 area,带 tag 的内环退化为 LineString,再由 `post_filter.geometry` 丢弃。`scripts/verify.sh` 的 `verify_area_layer_geometry_contracts` 会在 strict 模式下断言该配置和 geometry 白名单存在。

`building`、`landuse`、`natural_a`、`leisure_a` 和 `island` 的 export config 也必须分别声明 `area_tags: ["building"]`、`["landuse"]`、`["natural"]`、`["leisure"]`、`["place"]`。这避免闭合 way 同时以线和面导出。`scripts/verify.sh` 在 strict base 验证中检查这些精确配置及 staging 几何白名单；`admin` 不属于该契约，因为它仍需单独评估其边界线渲染语义。

`poi_label` 与 `highway_point` 是点图层，不能采用 `area_tags` 去重：不闭合或异常闭合的 way 可能只能导出为 LineString，仍需在 normalize 阶段转成 Point。两层通过 export config 的 `linear_tags` 从源头抑制闭合 way 的线/面双几何：`poi_label` 必须为 `["amenity", "tourism"]`，覆盖其全部 way 级筛选条件；`highway_point` 必须为 `["highway=services", "highway=rest_area"]`。新增或修改这两个 layer 的 way 级 `tags_filter` 时，必须同步更新 `linear_tags`；严格 base 验证会检查该契约。

水系线(`waterway` source-layer)必须保留 OSM `waterway` 子类型字段(`river` / `canal` / `stream` / `drain` / `ditch` 等)与 `width` 字段(数值类型)。`scripts/normalize.sh` 会对 `waterway` layer 的 `width` 做 `tonumber` 归一化,无效字符串 fallback 为 `null`。OSM 中 `width=*` 字段覆盖率仅约 5-10%(国内地区更低),客户端不能把 `width` 作为唯一线宽依据,必须按 `waterway` 子类型做阶梯默认宽度,`width` 仅在存在且为 number 时作为覆盖值。HMI style-loader 的 `line-width` 推荐按 zoom 做 `interpolate`,子类型 fallback:`river=1.0→6.0`、`canal=0.8→4.0`、`stream=0.4→2.5`、`drain=0.3→1.5`、`ditch=0.3→1.5`;`width` 字段存在且 ≥ 1 时可按 `max(0.3, width/8)` / `min(12, width*0.5)` 缩放覆盖。

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

`config/styles.yaml` 同时驱动三类 style 输出：

- `${SESSION}.style.json`：完整 vector style，包含 fill/line/symbol。
- `${WORKDIR}/cache/bake/${SESSION}/style-render.json`：raster bake 渲染用 style，只保留 background/fill/line，不包含 symbol 和 fill-extrusion。
- `${SESSION}.style-raster.json`：下游 hybrid style，使用 `raster-baked` raster source 作为底图，只叠加 base-vector symbol/icon layer。

`raster_bake` 不是 region catalog 里的 `huavd.asset_role` 配置值，而是构建角色派生出的正式下游 asset role：`raster-baked`。它表示 OSM/vector style 预烘焙 WebP raster 底图，不是 `imagery-raster`。

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
