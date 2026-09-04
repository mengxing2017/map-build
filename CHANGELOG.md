# Changelog

## 0.3.0 - 2026-09-04

当前版本为 `0.3.0`。本版本在保留 0.2.0 全部能力的基础上，新增多区域概览图、低缩放构建配置和派生地图（分层合成）三条独立流水线，并补充对应的配置、校验、文档与构建入口。

### 概览图（Overview）

- 新增 `config/overviews.yaml`，显式声明多区域 OSM PBF 概览图组合，包括默认低缩放参数、`source_regions` 列表、tippecanoe 覆盖和 LOD 边界。
- 新增 `scripts/lib/overview.sh` 提供概览配置解析、路径与元数据辅助函数。
- 新增概览专用脚本：`overview-filter.sh`、`overview-export.sh`、`overview-normalize.sh`、`overview-tippecanoe.sh`、`overview-metadata.sh`、`overview-manifest.sh`、`overview-attribution.sh`，复用 region 图层定义但走独立流程。
- 新增 `scripts/merge-pbf.sh`，按同一 OSM replication 快照校验多份本地源 PBF，写入 `${WORKDIR}/cache/merge/<overview-id>/` 的内容寻址缓存，记录每份提取的 replication sequence 用于溯源。
- 新增 `scripts/build-overview.sh`、`scripts/verify-overview.sh`、`scripts/pack-overview.sh`，分别负责构建、校验和打包 audit bundle（不带 `install.json`）。
- 新增 Makefile 入口 `build-overview`、`verify-overview`、`pack-overview`，支持 `OVERVIEW` 变量切换概览 id。
- 概览产物为独立的 `overview-vector` 资产，输出形如 `{overview-id}-{yyyymmdd}.overview.pmtiles`、`.overview.manifest.json` 与 `.overview.bundle.{tar.gz,zip}`。

### 低缩放构建（Tier profiles）

- 新增 `config/tier-profiles.yaml` 与 `scripts/lib/config.sh` 中的 tier profile 解析，集中维护低缩放 `country-low` 等构建轮廓，包含 `min_zoom`、`max_zoom`、`maximum_tile_bytes`、`extend_zooms_if_still_dropping` 与 `source_layers` 过滤。
- 新增 `scripts/profile-transform.sh`，把 tier profile 翻译为 tippecanoe CLI 参数和图层过滤选项，避免在区域脚本里硬编码低缩放参数。
- 在 `scripts/build.sh`、`scripts/tippecanoe.sh` 中集成 tier profile，支持单 region base-vector 按 profile 输出低缩放 PMTiles。
- 在 `scripts/manifest.sh`、`scripts/metadata.sh`、`scripts/style.sh` 中适配 build profile，确保 manifest/style/profile 字段随构建 profile 正确写入。
- 在 `scripts/verify.sh` 与 `scripts/doctor.sh` 中校验 tier profile 配置和低缩放构建产物完整性。

### 派生地图（Derived map）/ 分层合成（Composite）

- 新增 `config/source-assets.yaml`，声明本地源资产目录、路径、覆盖范围、许可证信息与适配器绑定。
- 新增 `config/adapters.yaml`，声明 provider adapter 与规范图层（canonical layer）profile 的绑定关系。
- 新增 `config/conflict-policies.yaml`，声明覆盖、去重、优先级和许可证冲突策略。
- 新增 `config/composites.yaml`，声明派生地图目标（`base-vector`）的源资产引用、冲突策略和合并规则。
- 新增 `scripts/lib/source-asset.sh`、`scripts/lib/derived-map.sh`，提供 source asset 校验、canonical layer 缓存寻址与派生合成辅助函数。
- 新增图层合成脚本：`source-inventory.sh`、`derived-inventory.sh`、`adapter-run.sh`、`compose-layers.sh`，分别负责源资产清点、引用校验、provider adapter 执行到隔离 canonical 缓存、按冲突策略合成图层。
- 新增派生地图入口：`build-derived-map.sh`、`verify-derived-map.sh`、`pack-derived-map.sh`、`prepare-derived-import.sh`，输出可安装 `base-vector`。
- Makefile 以 `source-inventory`、`derived-inventory`、`adapter-run`、`compose-layers`、`build-derived-map`、`verify-derived-map`、`pack-derived-map`、`prepare-derived-import` 取代早期 `composite-*` 命令入口，并提供 `ASSET` 变量（默认 `china-regional-osm`）。
- 在 `scripts/doctor.sh` 中校验派生地图 schema、source asset 与 conflict policy 完整性。

### 配置扩展

- 新增 `config/overviews.yaml`、`config/tier-profiles.yaml`、`config/source-assets.yaml`、`config/adapters.yaml`、`config/conflict-policies.yaml`、`config/composites.yaml` 等多份带 `schema_version` 的独立配置文件。
- `scripts/lib/config.sh` 新增对上述配置的解析、默认值、schema 校验与跨配置身份一致性检查。

### 校验与诊断

- `scripts/doctor.sh` 新增对 composites、derived-map schema、source asset、conflict policy、tier profiles 的校验。
- `scripts/verify.sh` 新增对 tier profile 构建产物的校验，覆盖元数据、图层集合和哈希一致性。
- `scripts/merge-pbf.sh` 在同快照校验中改为仅比较 replication timestamp，避免不同提取的 sequence 数值差异误判。
- `scripts/build-dem.sh` 补齐 `--vertical-datum` 参数的 usage 说明。

### 文档与法律

- 新增 MIT 许可证文件 `LICENSE` 与中文版 `LICENSE.zh-CN`。
- `README.md` 完善功能概览、构建流程与使用说明，并补充 tier profiles 与概览图入口说明。
- `AGENTS.md` 补充派生地图配置与脚本清单，修正 overview 同快照规则，明确 `tier-profiles`、`overview`、`derived-map` 的协作边界。
- 新增概览图与分层合成（derived map）专题文档，位于 `docs/configuration/index.md`、`docs/pipeline/index.md`、`docs/manual/index.md`。
- `docs/manual/index.md` 补充 DEM、overview、sprite 与质量工具（density-lint、viewport-lint 等）的变量和脚本用法说明。

## 0.2.0 - 2026-08-24

当前版本为 `0.2.0`。本版本内容均为新增能力。

### 构建流水线

- 新增从 Geofabrik OpenStreetMap `.osm.pbf` 提取离线矢量地图包的完整构建流程。
- 新增按 region、日期和 role 组织的 staging、cache、outputs 工作目录结构。
- 新增 `base`、`building`、`both`、`dem`、`all` 等构建/校验角色入口。
- 新增 OSM tag 过滤、GeoJSONSeq 导出、属性归一化、tippecanoe PMTiles 生成、metadata 写入、manifest 写入和 attribution 写入步骤。
- 新增 `make build`、`make release`、`make clean` 等稳定命令入口。

### 区域与图层配置

- 新增 `config/regions.yaml` 区域目录，支持 Geofabrik PBF URL、MD5 URL、basename、父级 region 和 HUAVD 元数据映射。
- 新增 `config/layers.yaml` 图层定义，集中维护 source layer、OSM tag filter 和最终字段。
- 新增 `config/export-config/*.json`，为 osmium export 提供按图层拆分的导出配置。
- 新增 `config/tippecanoe.yaml`，集中维护 tippecanoe 默认参数、高密度区域覆盖和 building role 配置。
- 新增区域 package-version 模板解析，支持全局默认、按角色默认、region 继承和环境变量覆盖。

### DEM 离线资产

- 新增 DEM raster PMTiles 构建路径。
- 新增 `config/dem.yaml` 授权 DEM 数据源配置，记录 encoding、license、vertical datum 等元数据。
- 新增 DEM metadata 校验要求，包括 `dem-encoding` 和 `huavd:vertical-datum`。
- 新增 DEM 在 `install.json.offline_maps[]` 中以 `asset-role=dem-raster` 参与离线包安装描述的能力。

### 样式资源

- 新增 MapLibre style 生成入口。
- 新增 glyph 生成入口和字体配置。
- 新增 sprite 生成入口和图标 manifest 配置。
- 新增 style、glyph、sprite 的 lint/校验辅助脚本。

### 打包与安装描述

- 新增 tar.gz 和 zip 两种 bundle 打包格式。
- 新增 import 包准备流程。
- 新增 bundle、PMTiles、manifest、attribution 和 install.json 的 SHA-512 sidecar 输出。
- 新增 `install.json` 生成逻辑，描述 offline maps、bundle assets 和安装所需元数据。
- 新增跨区域产物对比辅助脚本。

### 校验与诊断

- 新增 `doctor` 环境检查，验证 osmium、tippecanoe、pmtiles、jq、yq 等关键工具可用性。
- 新增 PMTiles header、metadata、tile type、compression、zoom 和 vector layer 数量校验。
- 新增 manifest、attribution、hash 和 strict package-version 一致性校验。
- 新增脚本级输入校验和统一错误码/日志辅助函数。

### 开发环境

- 新增 devbox 开发环境声明。
- 新增 `setup-tools.sh`，支持安装 osmium、tippecanoe、pmtiles、glyph generator 等工具。
- 新增 tippecanoe 源码编译路径，支持本地 tarball、内部二进制包 URL 和 Nix sqlite/zlib 编译参数。
- 新增 Makefile 对常用脚本入口的封装。

### 文档

- 新增 README 快速启动、环境准备、手动安装和发布构建说明。
- 新增 VitePress 文档站点。
- 新增手册、配置、流水线、运维、开发和参考文档。
- 新增 AGENTS.md，为 AI coding agent 提供仓库上下文、开发规则和验证要求。
