# 命令与变量参考

[返回手册目录](./index.md)

日常使用优先通过 `make` 入口执行。`scripts/*.sh` 是同一套能力的直连脚本，适合 CI、排障或只重跑某个内部阶段时使用。

所有命令默认在仓库根目录执行。构建数据写入 `WORKDIR`，默认是 `/tmp/huavd-map-build`；仓库目录只保存脚本、配置和文档。

## 通用变量

`make` 变量可以通过环境变量声明，也可以在命令行临时覆盖：

```bash
export REGION=china/guangxi
export YYYYMMDD=20260818
make build

make build REGION=china/guangxi YYYYMMDD=20260818 ROLE=base
```

| 变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `WORKDIR` | `/tmp/huavd-map-build` | 构建工作目录，包含 `mirror/`、`staging/`、`cache/`、`outputs/` |
| `REGION` | `china/guangxi` | region id，必须存在于 `config/regions.yaml` |
| `YYYYMMDD` | 当前 UTC 日 | 输出版本日，格式为 8 位数字，例如 `20260818` |
| `SESSION` | `{region-slug}-{YYYYMMDD}` | 构建会话名，例如 `china-guangxi-20260818`；通常不需要手动设置 |
| `INPUT` | 空 | `make build` 的输入 PBF；为空时自动使用 `mirror/{geofabrik.basename}` |
| `ROLE` | `both` | 构建或处理的资产角色：`base`、`building`、`raster_bake`、`base_raster`、`both_raster`、`both`、`dem`、`all`；`raster_bake` 复用已验证的 base PMTiles，`base_raster` 同时构建 base 与图片瓦片 |
| `FORMAT` | `both` | `make pack` 的包格式：`tar`、`zip`、`both` |
| `IMPORT_FORMAT` | `zip` | `make prepare-import` 的导入包格式：`zip` 或 `tar` |
| `GLYPH` | `0` | 矢量构建是否同时生成 glyph 和 style：`0` 或 `1`；`ROLE=base_raster`、`both_raster` 会自动启用，`ROLE=raster_bake` 要求同会话已存在 base、glyph、sprite 和 style 支撑资源 |
| `FORCE_BUILDING` | `0` | 设为 `1` 时允许 `make build` 强制构建 building；只应在已确认 region 建筑数据契约后使用 |
| `FORCE` | `0` | 设为 `1` 时让 `make build-overview` 忽略已有 overview 成品并重新构建 |
| `OVERVIEW` | `south-china-overview` | `config/overviews.yaml` 中的 overview id，供 `*-overview` 命令使用 |
| `DEM_SOURCE` | region 配置的默认源 | `config/dem.yaml` 中已授权的 DEM source id |
| `DEM_INPUT` | 空 | 已授权 DEM 的 PMTiles、MBTiles 或瓦片目录；供 `fetch-dem`/`build-dem` 使用 |
| `DEM_ENCODING` | source/default encoding | `mapbox-terrain-rgb`、`terrarium` 或 `heightmap-u16` |
| `HUAVD_MAP_BUILD_MACHINE_HOME` | `/opt/huavd-map-build` | 构建机初始化目标目录，用于 `init-build-machine-workdir` |
| `HUAVD_MAP_PACKAGE_VERSION` | 来自 `regions.yaml` 模板 | 全局覆盖 manifest / install.json 的 `package-version`；命中后跳过 region 模板（详见 `package-version 解析规则`） |
| `HUAVD_MAP_PACKAGE_VERSION_BASE` | 同上 | 仅覆盖 base role |
| `HUAVD_MAP_PACKAGE_VERSION_BUILDING` | 同上 | 仅覆盖 building role |
| `HUAVD_MAP_PACKAGE_VERSION_DEM` | 同上 | 仅覆盖 dem role |

`SESSION` 与 `YYYYMMDD` 同时设置时，以显式 `SESSION` 为准；脚本会从 `SESSION` 末尾反推 `YYYYMMDD`。`ROLE=both` 会处理 base 和 building，其中 building 只有在 region 配置为 `huavd.asset_role: building-vector` 且 `huavd.source_type: derived-building` 时才可用。

完整版本优先级见 [版本与 CI](./versioning.md#package-version-解析规则)。

## Makefile 入口

| 命令 | 用途 | 常用示例 |
| :--- | :--- | :--- |
| `make setup` | 安装或检查 `osmium`、`tippecanoe`、`pmtiles` 等工具 | `make setup` |
| `make doctor` | 检查外部命令、YAML/JSON 解析和关键配置 | `make doctor` |
| `make init` | `make init-workdir` 的别名 | `make init` |
| `make init-workdir` | 初始化当前 `WORKDIR` 目录结构 | `make init-workdir SESSION=china-guangxi-20260818` |
| `make install-config` | 初始化 `WORKDIR` 并复制当前 `config/` | `make install-config WORKDIR=/data/huavd-map-build` |
| `make init-build-machine-workdir` | 初始化构建机固定目录 | `make init-build-machine-workdir SESSION=china-guangxi-20260818` |
| `make install-build-machine-config` | 初始化构建机固定目录并复制配置 | `make install-build-machine-config` |
| `make catalog` | 从 `config/regions.yaml` 生成 region catalog 快照 | `make catalog` |
| `make fetch` | 下载 region 配置中的 Geofabrik PBF 和 `.md5`，并执行 MD5 校验 | `make fetch REGION=china/guangxi` |
| `make fetch-dem` | 拉取或拷贝 `config/dem.yaml` 中授权的 DEM 源到 `WORKDIR/mirror/dem/` | `make fetch-dem REGION=china/guangxi DEM_SOURCE=srtm DEM_INPUT=/data/srtm.tif` |
| `make build` | 从 PBF 构建 PMTiles、metadata、manifest、attribution 和 sha512 | `make build REGION=china/guangxi YYYYMMDD=20260818 ROLE=base` |
| `make build-dem` | 从授权 DEM 源生成 DEM PMTiles、manifest、attribution 和 sha512 | `make build-dem REGION=china/guangxi YYYYMMDD=20260818 DEM_SOURCE=srtm` |
| `make build-overview` | 合并同一 replication snapshot 的多个 region PBF，构建低缩放概览图 | `make build-overview OVERVIEW=south-china-overview YYYYMMDD=20260818` |
| `make derived-inventory` | 检查派生地图的 source assets 与 checksum | `make derived-inventory DERIVED_MAP=china-base` |
| `make build-derived-map` | 按图层合成并构建派生 `base-vector` | `make build-derived-map DERIVED_MAP=china-base YYYYMMDD=20260818` |
| `make glyph` | 生成当前 session 的 glyphs 目录 | `make glyph REGION=china/guangxi YYYYMMDD=20260818` |
| `make sprite` | 从 `config/icons/manifest.yaml` 生成当前 session 的 PNG sprite 和索引 JSON | `make sprite REGION=china/guangxi YYYYMMDD=20260818` |
| `make style` | 生成当前 session 的 MapLibre style JSON | `make style REGION=china/guangxi YYYYMMDD=20260818` |
| `make verify` | 验证 PMTiles header、metadata、manifest、SHA-512；`--strict` 还会校验 `package_version` 与 install.json `package-version` / `bundle-version` | `make verify REGION=china/guangxi YYYYMMDD=20260818 ROLE=both` |
| `make verify-dem` | 严格模式验证 DEM PMTiles、metadata、manifest 与 SHA-512 | `make verify-dem REGION=china/guangxi YYYYMMDD=20260818` |
| `make verify-overview` | 验证 overview 的 PMTiles 格式、图层、组成信息和哈希 | `make verify-overview OVERVIEW=south-china-overview YYYYMMDD=20260818` |
| `make verify-derived-map` | 严格验证派生产物、composition report 和地图身份 | `make verify-derived-map DERIVED_MAP=china-base YYYYMMDD=20260818` |
| `make pack` | 生成 tar/zip 分发包 | `make pack SESSION=china-guangxi-20260818 ROLE=both FORMAT=both` |
| `make pack-tar` | 只生成 `.bundle.tar.gz` | `make pack-tar SESSION=china-guangxi-20260818 ROLE=base` |
| `make pack-zip` | 只生成 `.bundle.zip` | `make pack-zip SESSION=china-guangxi-20260818 ROLE=base` |
| `make pack-overview` | 生成 overview 审核包；不包含 `install.json`，不可作为可安装离线地图发布 | `make pack-overview OVERVIEW=south-china-overview YYYYMMDD=20260818 FORMAT=zip` |
| `make pack-derived-map` | 生成带 `install.json` 的派生基础地图包 | `make pack-derived-map DERIVED_MAP=china-base YYYYMMDD=20260818 FORMAT=zip` |
| `make prepare-import` | 为单个 role 生成 `huavd-map` 导入包；`ROLE=both` 时会转为 `base` | `make prepare-import ROLE=base IMPORT_FORMAT=zip` |
| `make prepare-import-all` | 将当前 session 中可用的 base/building 聚合为一个导入包 | `make prepare-import-all IMPORT_FORMAT=tar` |
| `make prepare-derived-import` | 为派生 `base-vector` 生成 `huavd-map` 导入包 | `make prepare-derived-import DERIVED_MAP=china-base YYYYMMDD=20260818` |
| `make clean` | 删除当前 session 的 staging、pack/import cache 和 outputs | `make clean SESSION=china-guangxi-20260818 ROLE=both` |
| `make all` | 执行 `build` 和 `pack` | `make all REGION=china/guangxi YYYYMMDD=20260818` |
| `make release` | 执行 `build`、`pack`、`verify` | `make release REGION=china/guangxi YYYYMMDD=20260818` |
| `make release-tar` | 执行 `build`、`pack-tar`、`verify` | `make release-tar REGION=china/guangxi YYYYMMDD=20260818` |
| `make release-zip` | 执行 `build`、`pack-zip`、`verify` | `make release-zip REGION=china/guangxi YYYYMMDD=20260818` |
| `make lint` | 对已有 style 运行跨区域一致性和 viewport 检查 | `make lint WORKDIR=/data/huavd-map-build` |
| `make diff-products` | 对比两个 region 在指定日期的基础矢量成品 | `make diff-products REGION_A=china/guangxi REGION_B=china/guangdong YYYYMMDD=20260818` |

`make release`、`make release-tar`、`make release-zip` 不会自动下载 PBF。首次构建通常先执行 `make fetch`，或通过 `INPUT=/path/to/file.osm.pbf` 指向已有文件。

`make catalog` 的默认输出是 `config/derived/catalog.json`，这是派生文件，不作为构建产物提交。需要写到其他位置时使用脚本直连入口的 `OUTPUT` 变量。

## 脚本直连入口

多数脚本支持以下通用参数：

```text
--workdir=<path>
--region=<id>
--yyyymmdd=YYYYMMDD
--session=<session>
--role=base|building|raster_bake|base_raster|both_raster|both
```

脚本也会读取同名环境变量。相对输入路径解析规则与 `make` 一致：`mirror/`、`cache/`、`staging/`、`outputs/` 开头的路径会按 `WORKDIR` 下的路径处理。

| 脚本 | 用法 |
| :--- | :--- |
| `./scripts/setup-tools.sh` | 安装工具链并校验 Native 安装；Native 来源使用 `HUAVD_NATIVE_INSTALLATION` 或 `HUAVD_NATIVE_PACKAGE` 与可信摘要配置。仅在 `INSTALL_LEGACY_RENDERER=1` 时安装旧 npm renderer |
| `./scripts/doctor.sh` | 检查命令和配置是否可用 |
| `./scripts/fetch.sh` | `--region=<id> [--workdir=<path>] [--limit-rate=10m]` |
| `./scripts/fetch-dem.sh` | `--region=<id> --session=<session> [--source=<id>] [--input=<path>] [--workdir=<path>]`；只接收已授权本地或内网 DEM 输入 |
| `./scripts/build.sh` | Shell 兼容入口；新构建应使用 `make build`。`raster_bake`、`base_raster`、`both_raster` 的正式入口已由 Makefile 切换到 Python，不应直接调用此脚本启动 raster 构建 |
| `./scripts/build-dem.sh` | `--region=<id> --session=<session> [--source=<id>] [--input=<pmtiles\|mbtiles\|tile-dir>] [--encoding=<encoding>] [--vertical-datum=<datum>] [--workdir=<path>]` |
| `./scripts/glyph.sh` | `--region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--locales=all\|tag[,tag...]] [--force]` |
| `./scripts/sprite.sh` | `--region=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--workdir=<path>] [--force]` |
| `./scripts/style.sh` | `--region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--locale=<tag>] [--pmtiles-url=<url>]` |
| `./scripts/verify.sh` | `--region=<id> --role=<base\|building\|raster_bake\|base_raster\|both_raster\|both\|dem\|all> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--strict]` |
| `./scripts/pack.sh` | `--session=<session> [--role=base\|building\|raster_bake\|base_raster\|both_raster\|both\|dem\|all] [--format=tar\|zip\|both] [--workdir=<path>]` |
| `./scripts/prepare-import.sh` | `--session=<session> [--role=base\|building\|raster_bake\|base_raster\|both_raster\|both] [--format=tar\|zip] [--output=<archive-path>] [--transfer-id=<id>] [--aggregate] [--workdir=<path>] [--region=<id>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/region-pbf-basename.sh` | `[region]`，输出 region 配置中的 `geofabrik.basename` |
| `./scripts/manifest-catalog.sh` | 生成 region catalog；默认读取 `config/regions.yaml`，写入 `config/derived/catalog.json`；可用 `CONFIG_PATH` 和 `OUTPUT` 覆盖 |
| `./scripts/init-workdir.sh` | 初始化目录；通过 `HUAVD_MAP_BUILD_HOME`、`HUAVD_MAP_BUILD_SESSION`、`HUAVD_MAP_BUILD_COPY_CONFIG=1` 等环境变量控制 |
| `./scripts/generate-region-skeletons.sh` | `--iso3166-2-csv=<path> [--existing-config=config/regions.yaml] [--output=config/regions.yaml]`；未指定 `--output` 时输出尚未登记的骨架 |

## 派生地图入口

派生地图把 `composites.yaml` 中的 target region identity 写入标准 `base-vector` artifact，并生成
`install.json`。输入由 `source-assets.yaml` 显式声明，可来自不同版本或 provider；adapter 先将其
转换为 canonical layers，随后由 conflict policy 逐图层合成。构建不执行原始 PBF merge，也不比较
OSM timestamp 或 sequence。

| 脚本 | 用法 |
| :--- | :--- |
| `./scripts/source-inventory.sh` | `--asset=<id> [--workdir=<path>]` |
| `./scripts/derived-inventory.sh` | `--derived-map=<id> [--workdir=<path>]` |
| `./scripts/adapter-run.sh` | `--asset=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--force]` |
| `./scripts/compose-layers.sh` | `--derived-map=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--force]` |
| `./scripts/build-derived-map.sh` | `--derived-map=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--glyph=0\|1] [--force]` |
| `./scripts/verify-derived-map.sh` | `--derived-map=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--workdir=<path>] [--strict]` |
| `./scripts/pack-derived-map.sh` | `--derived-map=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--format=tar\|zip\|both] [--workdir=<path>]` |
| `./scripts/prepare-derived-import.sh` | `--derived-map=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--format=tar\|zip] [--output=<archive-path>] [--transfer-id=<id>] [--workdir=<path>]` |

中国示例：

```bash
make derived-inventory DERIVED_MAP=china-base
make build-derived-map DERIVED_MAP=china-base YYYYMMDD=20260818
make verify-derived-map DERIVED_MAP=china-base YYYYMMDD=20260818
make pack-derived-map DERIVED_MAP=china-base YYYYMMDD=20260818 FORMAT=zip
```

新国家示例使用 `inputs.mode: explicit` 列出相邻省份，并在 `path_overrides` 中为每个省指定实际 PBF
路径。目标国家必须先在 `regions.yaml` 注册，随后执行：

```bash
make derived-inventory DERIVED_MAP=new-country-base
make build-derived-map DERIVED_MAP=new-country-base YYYYMMDD=20260818
```

## Overview 直连入口

概览图是独立产物，不要向单区域的 `build.sh`、`verify.sh` 或 `pack.sh` 传入 overview 参数。开始前，必须把 `config/overviews.yaml` 所列每个 region 的 PBF 和对应 `.md5` sidecar 放到 `${WORKDIR}/mirror/`，且所有 PBF 的 replication timestamp 完全相同。sequence 会写入 lineage 供审计，但不要求跨 extract 相同。

| 脚本 | 用法 |
| :--- | :--- |
| `./scripts/merge-pbf.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--force]`；验证 MD5 与同快照约束，并返回内容寻址的合并 PBF 路径 |
| `./scripts/build-overview.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--force]` |
| `./scripts/verify-overview.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]` |
| `./scripts/pack-overview.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--format=tar\|zip\|both] [--workdir=<path>]` |

以下 overview 阶段脚本由 `build-overview.sh` 调用，仅用于定点排障：

| 阶段脚本 | 用法 |
| :--- | :--- |
| `./scripts/overview-filter.sh` | `--overview=<id> --input=<pbf> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]` |
| `./scripts/overview-export.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]` |
| `./scripts/overview-normalize.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]` |
| `./scripts/overview-tippecanoe.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]` |
| `./scripts/overview-metadata.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]` |
| `./scripts/overview-manifest.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]` |
| `./scripts/overview-attribution.sh` | `--overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]` |

内部阶段脚本通常由 `build.sh` 调用。只有在排查某一层处理结果时才建议直接运行：

| 阶段脚本 | 用法 |
| :--- | :--- |
| `./scripts/tags-filter.sh` | `--input=<pbf> --region=<id> [--layers=all\|layer[,layer...]] [--workdir=<path>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/export.sh` | `--region=<id> [--layers=all\|layer[,layer...]] [--workdir=<path>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/normalize.sh` | `--region=<id> [--layers=all\|layer[,layer...]] [--workdir=<path>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/tippecanoe.sh` | `--region=<id> --role=<base\|building> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/metadata.sh` | `--pmtiles=<path> --region=<id> --role=<base\|building> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/manifest.sh` | `--region=<id> --role=<base\|building> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/attribution.sh` | `--region=<id> --role=<base\|building> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/profile-transform.sh` | `--region=<id> --layers=<layer[,layer...]> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]`；通常仅由 `build.sh` 在 profile region 中调用 |

## 质量与成品对比工具

这些脚本不构建地图数据。它们读取已有 `WORKDIR` 产物，适合在发布前或 CI 中执行。

| 脚本 | 用法 |
| :--- | :--- |
| `./scripts/style-lint.sh` | 无参数；检查 `${WORKDIR}/outputs/*.style.json` 的跨区域非 source/metadata 内容是否一致 |
| `./scripts/viewport-lint.sh` | 无参数；检查 style 中的默认 viewport 是否落在对应 base PMTiles bounds 内 |
| `./scripts/density-lint.sh` | `<REGION_A> <REGION_B> [YYYYMMDD]`；比较两个基础矢量 PMTiles 的瓦片密度 |
| `./scripts/diff-region-products.sh` | `<REGION_A> <REGION_B> [YYYYMMDD]`；比较两个基础矢量成品的 metadata 与统计信息 |
