# Changelog

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
