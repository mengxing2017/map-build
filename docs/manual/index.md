# 安装与使用手册

## 适用范围

本手册说明如何在开发机或构建机上安装 `huavd-map-build` 的工具链，并完成一次从 OSM PBF 到 PMTiles、manifest、attribution、bundle 的标准构建。

默认工作目录是：

```text
/tmp/huavd-map-build
```

默认 region 是：

```text
china/guangxi
```

## 前置条件

- `devbox >= 0.14.2`。
- 推荐 Linux x86_64。Ubuntu/Debian 可通过系统包安装部分工具；其他发行版会更多依赖源码编译。
- 网络需要能访问 GitHub、GitHub Releases、Geofabrik 下载源、Go module 下载源和 Rust crate 下载源。
- 构建 tippecanoe 需要 C++ 编译器、`make`、`pkg-config`、SQLite3 开发头文件/库和 zlib 开发头文件/库。
- 如需生成 MapLibre glyph/style，还需要通过 cargo 安装出的 `build-glyphs` 命令，以及 `config/glyphs.yaml` 指向的字体文件。
- `pnpm` 只用于本文档预览和构建，不参与 PMTiles 数据构建。

如果系统已经全局安装了 `osmium`、`tippecanoe`、`pmtiles`，只要它们在 `PATH` 中且 `devbox run doctor` 通过，就可以复用。`devbox.json` 中的 `gcc`、`sqlite`、`zlib` 等声明仍用于提供稳定的编译和运行依赖，不建议仅因为本机全局存在同名软件就删除。

## 安装工具链

首次使用建议从 devbox 进入环境：

```bash
devbox shell
devbox install
devbox run setup
devbox run doctor
```

如果已经在 `devbox shell` 中，也可以直接执行脚本：

```bash
./scripts/setup-tools.sh
./scripts/doctor.sh
```

`devbox run setup` 会安装或检查以下核心命令：

| 命令 | 用途 |
| :--- | :--- |
| `osmium` | 下载后的 PBF tag 过滤和 GeoJSONSeq 导出 |
| `tippecanoe` | 将 GeoJSONSeq 转换为 PMTiles |
| `pmtiles` | 读取和修改 PMTiles metadata |

它也会安装并检查 glyph 相关工具，其中 `versatiles_glyphs` 通过 cargo 安装，并由 setup 写入 `build-glyphs` wrapper：

| 命令 | 用途 | 缺失影响 |
| :--- | :--- | :--- |
| `fonttools` | 检查或调试字体文件 | 不影响默认 PMTiles 构建 |
| `build-glyphs` | 从字体生成 MapLibre glyph PBF | `make glyph` 和 `make build GLYPH=1` 会失败 |

安装完成后必须执行：

```bash
devbox run doctor
```

优先在输出 `doctor: OK` 后再开始下载和构建数据。如果 `doctor` 只报告 `build-glyphs missing`，默认 `make build` 仍可运行，因为 `GLYPH=0` 不生成 glyph/style。准备生成离线文字渲染资源前必须先处理 cargo 安装或 PATH 问题。

## tippecanoe 安装说明

tippecanoe 官方 Releases 当前不提供 Linux 预编译资产，默认会从源码 tarball 编译。setup 脚本优先复用本地源码包：

```text
/tmp/tippecanoe.tar.gz
```

也可以显式指定源码包：

```bash
TIPPECANOE_SOURCE_TARBALL=/tmp/tippecanoe.tar.gz devbox run setup
```

如果团队维护内部预编译包，可以让 setup 脚本优先下载二进制：

```bash
TIPPECANOE_BINARY_URL="https://artifacts.example.com/tippecanoe/2.79.0/tippecanoe-linux-x86_64.tar.gz" devbox run setup
```

在 Ubuntu/Debian 上使用系统编译器手动编译前，需要安装开发依赖：

```bash
sudo apt-get update
sudo apt-get install -y build-essential pkg-config libsqlite3-dev zlib1g-dev
```

只安装 `sqlite3` 或 `zlib1g` 运行库不够，缺少 `libsqlite3-dev` 或 `zlib1g-dev` 会导致 `sqlite3.h`、`zlib.h` 找不到。在 devbox/Nix 环境中优先使用 `devbox run setup`，不要混用系统 `/usr/lib` 的 sqlite/zlib。

## Glyph 和 Style 前置条件

`scripts/glyph.sh` 默认读取 `config/glyphs.yaml` 中的 `generator.command`，当前值是 `build-glyphs`。`setup` 会通过 cargo 安装 `versatiles_glyphs`，并在 `$HOME/.local/bin/build-glyphs` 写入兼容 wrapper。devbox shell 会把 `$HOME/.local/bin` 和 `$CARGO_HOME/bin` 加入 `PATH`。

可用环境变量覆盖 cargo 安装来源：

```bash
BUILD_GLYPHS_CRATE=versatiles_glyphs BUILD_GLYPHS_VERSION=0.9.1 devbox run setup
```

如果使用内部 fork，可同时设置 `BUILD_GLYPHS_BINARY` 指定 cargo 安装出的二进制名；setup 仍会提供 `build-glyphs` wrapper。

默认 glyph 配置需要以下字体文件存在于仓库根目录下的 `fonts/`：

```text
fonts/NotoSans-Regular.ttf
fonts/NotoSansCJKsc-Regular.otf
fonts/NotoSansCJKjp-Regular.otf
fonts/NotoSansCJKkr-Regular.otf
```

这些字体文件当前不是构建脚本自动下载项。团队可以从内部制品库或官方 Noto 发布包准备，并保持文件名与 `config/glyphs.yaml` 完全一致。发布 bundle 前需要确认字体及生成出的 glyph PBF 的再分发许可。

生成 glyph 和 style 的关系如下：

| 命令 | 产物 | 说明 |
| :--- | :--- | :--- |
| `make glyph` | `${WORKDIR}/outputs/${SESSION}.glyphs/` | 按 locale 和 fontstack 输出 `{range}.pbf` 与 `.sha512` |
| `make style` | `${WORKDIR}/outputs/${SESSION}.style.json` | 写入 MapLibre `glyphs` URL 模板 |
| `make build GLYPH=1` | PMTiles、glyphs、style | 在 PMTiles 构建结束后自动补 glyph 和 style |

MapLibre style 的 `glyphs` 字段必须包含 `{fontstack}` 和 `{range}.pbf` 占位。项目默认 URL 模板是：

```text
huavd-map://glyphs/{locale}/{fontstack}/{range}.pbf
```

`make pack` 不会主动生成 glyph/style，只会在这些产物已经存在时把它们写入 bundle。

## 命令使用索引

日常使用优先通过 `make` 入口执行。`scripts/*.sh` 是同一套能力的直连脚本，适合 CI、排障或只重跑某个内部阶段时使用。

所有命令默认在仓库根目录执行。构建数据写入 `WORKDIR`，默认是 `/tmp/huavd-map-build`；仓库目录只保存脚本、配置和文档。

### 通用变量

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
| `ROLE` | `both` | 构建或处理的资产角色：`base`、`building`、`both`、`dem`、`all`；`build` 仅接受前三者，`pack`/`verify` 可处理 DEM |
| `FORMAT` | `both` | `make pack` 的包格式：`tar`、`zip`、`both` |
| `IMPORT_FORMAT` | `zip` | `make prepare-import` 的导入包格式：`zip` 或 `tar` |
| `GLYPH` | `0` | `make build` 是否同时生成 glyph 和 style：`0` 或 `1` |
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

### package-version 解析规则

`manifest.huavd_record.package_version`、`install.json` 的 `offline_maps[].package-version` 与 `bundles[].bundle-version` 都从同一个值派生。`scripts/lib/config.sh:region_package_version()` 按以下优先级解析：

1. **per-role env**：`HUAVD_MAP_PACKAGE_VERSION_BASE` / `_BUILDING` / `_DEM`（按 role 大写）。
2. **全局 env**：`HUAVD_MAP_PACKAGE_VERSION`。
3. **region 模板**：沿 `geofabrik.parent_region` 上溯读取 `huavd.package_version_template`。
4. **per-role 默认**：`huavd.package_version_template_per_role[<role>]`（`{yyyymmdd}.{role}` 之外常用 `-building` / `-dem` 模式）。
5. **全局默认**：`huavd.default_package_version_template`，缺省回落 `{yyyymmdd}.{role}`。

命中规则 1–2 后跳过模板渲染，并 `INFO package_version source=env (...=...)` 日志记录来源，便于排查 CI 中漏 `unset` 的覆盖。env 值必须匹配 `^[A-Za-z0-9._+-]+$`，包含空格或其它字符会 `die` 退出。

模板支持两个占位符：

- `{yyyymmdd}` → 当前 `YYYYMMDD`（如 `20260818`）。
- `{role}` → 当前 role（`base` / `building` / `dem`）。

**历史契约**：当 region 自带模板（不在 `huavd.default_package_version_template` 之下）且 role 是 `building` 或 `dem` 时，第一个 `.{yyyymmdd}` 会被替换为 `-<role>.{yyyymmdd}`。仓库当前没有 region 使用这种模板，仅作记录：

| region 模板 | base | building | dem |
| :--- | :--- | :--- | :--- |
| `v1.0.{yyyymmdd}.cn` | `v1.0.20260818.cn` | `v1.0-building.20260818.cn` | `v1.0-dem.20260818.cn` |
| `1.0.{yyyymmdd}.base` | `1.0.20260818.base` | `1.0-building.20260818.base` | `1.0-dem.20260818.base` |

注：纯 `{yyyymmdd}.{role}`（无前缀）和不含 `.{yyyymmdd}` 的模板不会触发替换；`per-role env` / `全局 env` 也不经过这一步。

### Makefile 入口

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
| `make composite-inventory` | 检查分层合成所需的本地 PBF、MD5 与 OSM 快照 | `make composite-inventory COMPOSITE=china-base-from-provinces` |
| `make build-composite` | 合并配置的子区域 PBF 并构建可安装的 `base-vector` | `make build-composite COMPOSITE=china-base-from-provinces YYYYMMDD=20260818` |
| `make glyph` | 生成当前 session 的 glyphs 目录 | `make glyph REGION=china/guangxi YYYYMMDD=20260818` |
| `make sprite` | 从 `config/icons/manifest.yaml` 生成当前 session 的 PNG sprite 和索引 JSON | `make sprite REGION=china/guangxi YYYYMMDD=20260818` |
| `make style` | 生成当前 session 的 MapLibre style JSON | `make style REGION=china/guangxi YYYYMMDD=20260818` |
| `make verify` | 验证 PMTiles header、metadata、manifest、SHA-512；`--strict` 还会校验 `package_version` 与 install.json `package-version` / `bundle-version` | `make verify REGION=china/guangxi YYYYMMDD=20260818 ROLE=both` |
| `make verify-dem` | 严格模式验证 DEM PMTiles、metadata、manifest 与 SHA-512 | `make verify-dem REGION=china/guangxi YYYYMMDD=20260818` |
| `make verify-overview` | 验证 overview 的 PMTiles 格式、图层、组成信息和哈希 | `make verify-overview OVERVIEW=south-china-overview YYYYMMDD=20260818` |
| `make verify-composite` | 严格验证合成产物、目录身份和 PBF lineage | `make verify-composite COMPOSITE=china-base-from-provinces YYYYMMDD=20260818` |
| `make pack` | 生成 tar/zip 分发包 | `make pack SESSION=china-guangxi-20260818 ROLE=both FORMAT=both` |
| `make pack-tar` | 只生成 `.bundle.tar.gz` | `make pack-tar SESSION=china-guangxi-20260818 ROLE=base` |
| `make pack-zip` | 只生成 `.bundle.zip` | `make pack-zip SESSION=china-guangxi-20260818 ROLE=base` |
| `make pack-overview` | 生成 overview 审核包；不包含 `install.json`，不可作为可安装离线地图发布 | `make pack-overview OVERVIEW=south-china-overview YYYYMMDD=20260818 FORMAT=zip` |
| `make pack-composite` | 生成带 `install.json` 的分层基础地图包 | `make pack-composite COMPOSITE=china-base-from-provinces YYYYMMDD=20260818 FORMAT=zip` |
| `make prepare-import` | 为单个 role 生成 `huavd-map` 导入包；`ROLE=both` 时会转为 `base` | `make prepare-import ROLE=base IMPORT_FORMAT=zip` |
| `make prepare-import-all` | 将当前 session 中可用的 base/building 聚合为一个导入包 | `make prepare-import-all IMPORT_FORMAT=tar` |
| `make prepare-composite-import` | 为分层合成的 `base-vector` 生成 `huavd-map` 导入包 | `make prepare-composite-import COMPOSITE=china-base-from-provinces YYYYMMDD=20260818` |
| `make clean` | 删除当前 session 的 staging、pack/import cache 和 outputs | `make clean SESSION=china-guangxi-20260818 ROLE=both` |
| `make all` | 执行 `build` 和 `pack` | `make all REGION=china/guangxi YYYYMMDD=20260818` |
| `make release` | 执行 `build`、`pack`、`verify` | `make release REGION=china/guangxi YYYYMMDD=20260818` |
| `make release-tar` | 执行 `build`、`pack-tar`、`verify` | `make release-tar REGION=china/guangxi YYYYMMDD=20260818` |
| `make release-zip` | 执行 `build`、`pack-zip`、`verify` | `make release-zip REGION=china/guangxi YYYYMMDD=20260818` |
| `make lint` | 对已有 style 运行跨区域一致性和 viewport 检查 | `make lint WORKDIR=/data/huavd-map-build` |
| `make diff-products` | 对比两个 region 在指定日期的基础矢量成品 | `make diff-products REGION_A=china/guangxi REGION_B=china/guangdong YYYYMMDD=20260818` |

`make release`、`make release-tar`、`make release-zip` 不会自动下载 PBF。首次构建通常先执行 `make fetch`，或通过 `INPUT=/path/to/file.osm.pbf` 指向已有文件。

`make catalog` 的默认输出是 `config/derived/catalog.json`，这是派生文件，不作为构建产物提交。需要写到其他位置时使用脚本直连入口的 `OUTPUT` 变量。

### 脚本直连入口

多数脚本支持以下通用参数：

```text
--workdir=<path>
--region=<id>
--yyyymmdd=YYYYMMDD
--session=<session>
--role=base|building|both
```

脚本也会读取同名环境变量。相对输入路径解析规则与 `make` 一致：`mirror/`、`cache/`、`staging/`、`outputs/` 开头的路径会按 `WORKDIR` 下的路径处理。

| 脚本 | 用法 |
| :--- | :--- |
| `./scripts/setup-tools.sh` | 安装工具链；通过 `TIPPECANOE_VERSION`、`TIPPECANOE_SOURCE_TARBALL`、`TIPPECANOE_BINARY_URL`、`PMTILES_VERSION`、`INSTALL_PREFIX` 等环境变量控制 |
| `./scripts/doctor.sh` | 检查命令和配置是否可用 |
| `./scripts/fetch.sh` | `--region=<id> [--workdir=<path>] [--limit-rate=10m]` |
| `./scripts/fetch-dem.sh` | `--region=<id> --session=<session> [--source=<id>] [--input=<path>] [--workdir=<path>]`；只接收已授权本地或内网 DEM 输入 |
| `./scripts/build.sh` | `--input=<path-to.osm.pbf> --region=<id> [--yyyymmdd=YYYYMMDD] [--role=base\|building\|both] [--workdir=<path>] [--glyph=0\|1] [--force] [--force-building]` |
| `./scripts/build-dem.sh` | `--region=<id> --session=<session> [--source=<id>] [--input=<pmtiles\|mbtiles\|tile-dir>] [--encoding=<encoding>] [--vertical-datum=<datum>] [--workdir=<path>]` |
| `./scripts/glyph.sh` | `--region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--locales=all\|tag[,tag...]] [--force]` |
| `./scripts/sprite.sh` | `--region=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--workdir=<path>] [--force]` |
| `./scripts/style.sh` | `--region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--locale=<tag>] [--pmtiles-url=<url>]` |
| `./scripts/verify.sh` | `--region=<id> --role=<base\|building\|both\|dem\|all> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--strict]` |
| `./scripts/pack.sh` | `--session=<session> [--role=base\|building\|both\|dem\|all] [--format=tar\|zip\|both] [--workdir=<path>]` |
| `./scripts/prepare-import.sh` | `--session=<session> [--role=base\|building\|both] [--format=tar\|zip] [--output=<archive-path>] [--transfer-id=<id>] [--aggregate] [--workdir=<path>] [--region=<id>] [--yyyymmdd=YYYYMMDD]` |
| `./scripts/region-pbf-basename.sh` | `[region]`，输出 region 配置中的 `geofabrik.basename` |
| `./scripts/manifest-catalog.sh` | 生成 region catalog；默认读取 `config/regions.yaml`，写入 `config/derived/catalog.json`；可用 `CONFIG_PATH` 和 `OUTPUT` 覆盖 |
| `./scripts/init-workdir.sh` | 初始化目录；通过 `HUAVD_MAP_BUILD_HOME`、`HUAVD_MAP_BUILD_SESSION`、`HUAVD_MAP_BUILD_COPY_CONFIG=1` 等环境变量控制 |
| `./scripts/generate-region-skeletons.rb` | `--iso3166-2-csv=<path> [--existing-config=config/regions.yaml] [--output=config/regions.yaml]` |

### 分层合成入口

分层合成与 overview 不同：它会把 `config/composites.yaml` 中登记的 target region identity
写入标准 `base-vector` artifact，并在打包时生成 `install.json`。`sources.mode` 支持
`direct-children`、`descendants` 和 `explicit`，可用于地级市合成省、省合成国家、国家合成洲和
洲合成世界；每个 target 都必须在 `config/regions.yaml` 有既有地图身份。

开始前，需要将解析出的每个 region PBF 和对应 `.md5` sidecar 放入 `${WORKDIR}/mirror/`。
文件名由 `inputs.basename_template` 或 `basename_overrides` 决定，不依赖源 region 是否配置
Geofabrik 下载 URL。`local-mirror` 是当前唯一 provider，合成流程不联网；可先通过受控下载、
内网同步或离线介质准备数据。所有输入必须来自完全相同的 OSM replication timestamp 和 sequence；
缺少任何一个输入、MD5 不匹配或快照不一致都会在 merge 前失败。

| 脚本 | 用法 |
| :--- | :--- |
| `./scripts/composite-inventory.sh` | `--composite=<id> [--workdir=<path>]`；列出本地 PBF 库的缺失、MD5 与快照问题 |
| `./scripts/merge-composite-pbf.sh` | `--composite=<id> [--workdir=<path>] [--force]` |
| `./scripts/build-composite.sh` | `--composite=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--glyph=0\|1] [--force]` |
| `./scripts/verify-composite.sh` | `--composite=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--workdir=<path>] [--strict]` |
| `./scripts/pack-composite.sh` | `--composite=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--format=tar\|zip\|both] [--workdir=<path>]` |
| `./scripts/prepare-composite-import.sh` | `--composite=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--format=tar\|zip] [--output=<archive-path>] [--transfer-id=<id>] [--workdir=<path>]` |

中国示例：

```bash
make composite-inventory COMPOSITE=china-base-from-provinces
make build-composite COMPOSITE=china-base-from-provinces YYYYMMDD=20260818
make verify-composite COMPOSITE=china-base-from-provinces YYYYMMDD=20260818
make pack-composite COMPOSITE=china-base-from-provinces YYYYMMDD=20260818 FORMAT=zip
```

### Overview 直连入口

概览图是独立产物，不要向单区域的 `build.sh`、`verify.sh` 或 `pack.sh` 传入 overview 参数。开始前，必须把 `config/overviews.yaml` 所列每个 region 的 PBF 和对应 `.md5` sidecar 放到 `${WORKDIR}/mirror/`，且所有 PBF 的 replication timestamp 与 sequence 完全相同。

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

### 质量与成品对比工具

这些脚本不构建地图数据。它们读取已有 `WORKDIR` 产物，适合在发布前或 CI 中执行。

| 脚本 | 用法 |
| :--- | :--- |
| `./scripts/style-lint.sh` | 无参数；检查 `${WORKDIR}/outputs/*.style.json` 的跨区域非 source/metadata 内容是否一致 |
| `./scripts/viewport-lint.sh` | 无参数；检查 style 中的默认 viewport 是否落在对应 base PMTiles bounds 内 |
| `./scripts/density-lint.sh` | `<REGION_A> <REGION_B> [YYYYMMDD]`；比较两个基础矢量 PMTiles 的瓦片密度 |
| `./scripts/diff-region-products.sh` | `<REGION_A> <REGION_B> [YYYYMMDD]`；比较两个基础矢量成品的 metadata 与统计信息 |

### 常用命令组合

端到端一次构建（日常 region 模板，monthly 路线）：

```bash
unset HUAVD_MAP_PACKAGE_VERSION \
      HUAVD_MAP_PACKAGE_VERSION_BASE \
      HUAVD_MAP_PACKAGE_VERSION_BUILDING \
      HUAVD_MAP_PACKAGE_VERSION_DEM

export REGION=china/guangxi
export YYYYMMDD=20260818
# WORKDIR 默认 /tmp/huavd-map-build，需要显式换盘时再 export WORKDIR

make fetch                      # 下载 Geofabrik PBF + MD5
make release ROLE=both          # build + pack + verify（含 --strict 校验 package_version）
make prepare-import-all         # 聚合 base/building 的 .import.zip

# ${WORKDIR}/outputs/ 产物：
#   china-guangxi-20260818.base.pmtiles          ← vector tiles
#   china-guangxi-20260818.base.manifest.json    ← .huavd_record.package_version = "20260818.base"
#   china-guangxi-20260818.building.pmtiles      ← building role (region 启用时)
#   china-guangxi-20260818.building.manifest.json
#                                              .huavd_record.package_version = "20260818-building"
#   china-guangxi-20260818.bundle.zip            ← 含 install.json
#   china-guangxi-20260818.import.zip            ← huavd-map 导入包
```

默认 region 快速构建：

```bash
make fetch
make release
```

使用已有 PBF，不走网络下载：

```bash
make release REGION=china/guangxi YYYYMMDD=20260818 INPUT=/data/osm/guangxi-260726.osm.pbf ROLE=base
```

生成 PMTiles 后再补 glyph 和 style：

```bash
make glyph REGION=china/guangxi YYYYMMDD=20260818
make style REGION=china/guangxi YYYYMMDD=20260818
make pack REGION=china/guangxi YYYYMMDD=20260818 ROLE=base FORMAT=zip
```

构建时同时生成 glyph 和 style：

```bash
make build REGION=china/guangxi YYYYMMDD=20260818 GLYPH=1
make pack REGION=china/guangxi YYYYMMDD=20260818 ROLE=base FORMAT=zip
```

准备 `huavd-map` 导入包：

```bash
make prepare-import REGION=china/guangxi YYYYMMDD=20260818 ROLE=base IMPORT_FORMAT=zip
```

只重跑基础 PMTiles 验证：

```bash
./scripts/verify.sh --region=china/guangxi --yyyymmdd=20260818 --role=base --strict
```

## 构建一次地图数据

推荐使用“一次声明、自动继承”的操作模式。先声明构建上下文，后续 `make` 命令会自动读取这些环境变量，无需在每条命令里重复传参。

所有 `make` 命令都应在项目仓库根目录执行。`WORKDIR` 是数据工作目录，不是执行 `make` 的目录；不要在 `${WORKDIR}` 或 `${WORKDIR}/mirror` 中直接运行 `make release`。

```bash
export REPO_ROOT=/path/to/huavd-map-build
cd "${REPO_ROOT}"
export REGION=china/guangxi
export YYYYMMDD=20260818
# export WORKDIR=/tmp/huavd-map-build
# export ROLE=both
```

`WORKDIR` 默认是 `/tmp/huavd-map-build`，可以省略。`ROLE` 默认是 `both`，会构建 base，并在 region 启用 building metadata 时同时构建 building；如果只需要基础图层，可设置 `export ROLE=base`。`SESSION` 会由 `REGION` 和 `YYYYMMDD` 自动推导，例如 `china/guangxi` 与 `20260818` 会得到 `china-guangxi-20260818`，日常操作不需要手动指定。

下载 Geofabrik PBF 和 MD5：

```bash
make fetch
```

一键构建、打包并验证：

```bash
make release
```

`make release` 不包含下载步骤，它要求 PBF 已经存在于 `${WORKDIR}/mirror/`，或已通过 `INPUT` 指定本地 PBF。首次构建通常先执行 `make fetch`，再执行 `make release`。

只需要其中一种打包格式时：

```bash
make release-tar
make release-zip
```

如果只需构建和打包，不立即验证：

```bash
make all
```

### 分步操作

需要单独控制每一步时，继续复用同一组环境变量：

```bash
make fetch
make build
make verify
make pack
```

`make build` 默认读取：

```text
mirror/{geofabrik.basename}
```

其中 `geofabrik.basename` 来自 `config/regions.yaml`，与 `make fetch` 下载和校验的文件名保持一致。`YYYYMMDD` 只用于输出 session 和产物版本，不参与输入 PBF 文件名推导。对于 `china/guangxi`，当前配置的默认输入会解析为：

```text
/tmp/huavd-map-build/mirror/guangxi-latest.osm.pbf
```

### 人工定版

默认情况下 `manifest.huavd_record.package_version` 和 `install.json` 的
`offline_maps[].package-version`、`bundles[].bundle-version` 都由
`config/regions.yaml` 的 `huavd.package_version_template`（含父子继承）渲染，
具体规则见上文 `package-version 解析规则` 小节。

如果要锁住与月份无关的 RC 版本号，设 `HUAVD_MAP_PACKAGE_VERSION` 即可跳过模板：

```bash
export HUAVD_MAP_PACKAGE_VERSION="1.4.0-rc2"
make fetch REGION=china/guangxi YYYYMMDD=20260818
make release REGION=china/guangxi YYYYMMDD=20260818
# ${WORKDIR}/outputs/china-guangxi-20260818.base.pmtiles  ✓
# ${WORKDIR}/outputs/china-guangxi-20260818.base.manifest.json
#   .huavd_record.package_version = "1.4.0-rc2"
# ${WORKDIR}/outputs/china-guangxi-20260818.bundle.zip  (含 install.json)
#   .offline_maps[0]."package-version" = "1.4.0-rc2"
#   .bundles[0]."bundle-version"     = "1.4.0-rc2"
```

per-role 不一致时分别覆盖（`per-role env` 永远优先于 `全局 env`）：

```bash
export HUAVD_MAP_PACKAGE_VERSION_BASE="1.4.0-base"
export HUAVD_MAP_PACKAGE_VERSION_BUILDING="1.4.0-bld"
# HUAVD_MAP_PACKAGE_VERSION_DEM 不设 -> dem 仍走 region 模板
make release REGION=china/guangxi YYYYMMDD=20260818 ROLE=both
# base      package-version = "1.4.0-base"
# building  package-version = "1.4.0-bld"
# dem       package-version = 走全局默认 ("20260818-dem")
```

发布构建后用 `verify --strict` 一次性确认所有产物落盘正确：

```bash
make verify REGION=china/guangxi YYYYMMDD=20260818 ROLE=all --strict
# OK   manifest package_version (role=base)
# OK   manifest package_version (role=building)
# OK   manifest package_version (role=dem)
# OK   install.json offline_maps package-version
# OK   install.json bundles bundle-version
```

构建机或 CI runner 残留的 `HUAVD_MAP_PACKAGE_VERSION*` 会静默吃掉 region 模板
改动，发布 job 的第一步应显式 `unset`。env 包含空格或其它非法字符（不在
`[A-Za-z0-9._+-]+`）会 `die` 退出，不会写出一份半成品 manifest。

## 多级操作场景

### 快速上手

全部使用 Makefile 默认值，适合首次体验默认广西 region：

```bash
make fetch
make release
```

### 日常开发

声明一次 region 和月份，后续命令自动继承：

```bash
export REGION=china/sichuan
export YYYYMMDD=20260818

make fetch
make build
make verify
make pack
```

### 批处理

批量构建多个 region 时，在循环内更新环境变量：

```bash
for region in china/guangxi china/sichuan china/yunnan; do
  export REGION="${region}"
  export YYYYMMDD=20260818
  make fetch
  make release
done
```

### CI 场景

CI 可以在 job 环境中声明变量，然后使用相同的短命令：

```bash
export REGION=china/guangxi
export YYYYMMDD=20260818
export WORKDIR=/tmp/huavd-map-build-ci
export ROLE=base

devbox run doctor
make fetch
make release
```

如果 CI 环境不能访问 Geofabrik，就不要执行 `make fetch`；应先把 PBF 作为 CI artifact 或缓存放入当前 `WORKDIR`，或通过 `INPUT` 指向已有文件：

```bash
export REGION=china/guangxi
export YYYYMMDD=20260818
export WORKDIR=/tmp/huavd-map-build-ci
export ROLE=base
export INPUT=/cache/maps/guangxi-latest.osm.pbf

devbox run doctor
make release
```

现有的命令行变量覆盖方式仍然兼容，适合临时切换参数；推荐文档中的主流程使用环境变量继承模式。

### Release pipeline: 锁版本号

CI 同一个 region 既有日常构建（每月走 `regions.yaml` 模板），又有发布构建（需要锁定 `1.4.0-rc2` 这类与月份无关的版本）。`huavd-map-build` 的 manifest、install.json、bundle 都通过同一套 `region_package_version()` 解析器，详见上文 `package-version 解析规则` 小节。

#### 日常构建 job

显式 `unset` 是为了避免上游 job 残留 `HUAVD_MAP_PACKAGE_VERSION*` 影响本次构建：

```bash
# 入口：显式清空覆盖
unset HUAVD_MAP_PACKAGE_VERSION \
      HUAVD_MAP_PACKAGE_VERSION_BASE \
      HUAVD_MAP_PACKAGE_VERSION_BUILDING \
      HUAVD_MAP_PACKAGE_VERSION_DEM

export REGION=china/guangxi
export YYYYMMDD=20260818

make fetch
make release ROLE=both
make verify ROLE=all --strict

# 产物在 ${WORKDIR}/outputs/ 下：
#   china-guangxi-20260818.base.pmtiles
#   china-guangxi-20260818.base.manifest.json  .huavd_record.package_version = "20260818.base"
#   china-guangxi-20260818.building.pmtiles
#   china-guangxi-20260818.building.manifest.json  .huavd_record.package_version = "20260818-building"
#   china-guangxi-20260818.bundle.zip  install.json .offline_maps[0]."package-version" = "20260818.base"
```

#### 发布构建 job

```bash
unset HUAVD_MAP_PACKAGE_VERSION \
      HUAVD_MAP_PACKAGE_VERSION_BASE \
      HUAVD_MAP_PACKAGE_VERSION_BUILDING \
      HUAVD_MAP_PACKAGE_VERSION_DEM

export REGION=china/guangxi
export YYYYMMDD=20260818
# 发布锁版本，覆盖 base / building，dem 不动
export HUAVD_MAP_PACKAGE_VERSION_BASE="1.4.0-base"
export HUAVD_MAP_PACKAGE_VERSION_BUILDING="1.4.0-bld"

make fetch
make release ROLE=both
make verify ROLE=all --strict
# OK   manifest package_version (role=base)         => "1.4.0-base"
# OK   manifest package_version (role=building)     => "1.4.0-bld"
# OK   manifest package_version (role=dem)          => 走全局默认 ("20260818-dem")
# OK   install.json offline_maps package-version
# OK   install.json bundles bundle-version
```

如果不区分 role，所有产物都用同一个版本号：

```bash
unset HUAVD_MAP_PACKAGE_VERSION_BASE \
      HUAVD_MAP_PACKAGE_VERSION_BUILDING \
      HUAVD_MAP_PACKAGE_VERSION_DEM
export HUAVD_MAP_PACKAGE_VERSION="1.4.0-rc2"
make release REGION=china/guangxi YYYYMMDD=20260818 ROLE=both
# 所有 manifest/install.json 的 package-version 都是 "1.4.0-rc2"
```

> 构建机或 runner 上一次构建残留的 `HUAVD_MAP_PACKAGE_VERSION*` 会静默吃掉
> region 模板修改，所以每个 job 入口都先 `unset`，避免排查“明明改了 regions.yaml
> 怎么产物没变”的怪问题。

### 手动下载地图数据

无法使用 `make fetch` 时，仍然可以手动准备地图数据。适用场景包括浏览器下载、内网中转、使用自定义镜像源，或在无网络环境导入已有 `.osm.pbf` 文件。

如果使用 `make fetch`，需要准备或下载的文件名由 `config/regions.yaml` 的 `geofabrik.basename` 决定：

```text
{geofabrik.basename}
{geofabrik.basename}.md5
```

以 `china/guangxi` 为例，当前配置值是：

```text
guangxi-latest.osm.pbf
guangxi-latest.osm.pbf.md5
```

浏览器或内部镜像下载出的文件名可能是带日期的快照名，例如 `guangxi-260726.osm.pbf`。这种文件名不会由 `REGION` 和 `YYYYMMDD` 自动推导，推荐直接用 `INPUT` 指定。

方案 A：保留实际下载文件名，通过 `INPUT` 指定：

```bash
export REPO_ROOT=/path/to/huavd-map-build
cd "${REPO_ROOT}"
export REGION=china/guangxi
export YYYYMMDD=20260818
export WORKDIR=/tmp/huavd-map-build
export INPUT=/path/to/guangxi-260726.osm.pbf
export HUAVD_MAP_PACKAGE_VERSION="1.4.0-rc2"  # 锁 RC 版本，跳过 region 模板

make release
```

如果不想切换当前目录，也可以使用：

```bash
export REPO_ROOT=/path/to/huavd-map-build
make -C "${REPO_ROOT}" release
```

方案 B：放入默认 mirror 目录，并按配置 basename 建立软链，让 `make build` 自动读取：

```bash
export REPO_ROOT=/path/to/huavd-map-build
cd "${REPO_ROOT}"
export REGION=china/guangxi
export YYYYMMDD=20260818
export WORKDIR=/tmp/huavd-map-build
export HUAVD_MAP_PACKAGE_VERSION="1.4.0-rc2"  # 锁 RC 版本，跳过 region 模板

mkdir -p "${WORKDIR}/mirror"
# 将实际下载的 PBF 和 MD5 放入 mirror 后，链接为配置中的默认输入名
ln -sf guangxi-260726.osm.pbf "${WORKDIR}/mirror/guangxi-latest.osm.pbf"
ln -sf guangxi-260726.osm.pbf.md5 "${WORKDIR}/mirror/guangxi-latest.osm.pbf.md5"

make release
```

如果下载源同时提供 `.md5`，先按 `.md5` 文件中的实际文件名校验：

```bash
(cd "${WORKDIR}/mirror" && md5sum -c guangxi-260726.osm.pbf.md5)
```

各 region 的 Geofabrik 下载 URL 定义在 `config/regions.yaml` 的 `geofabrik.pbf_url` 字段。手动下载只替代 `make fetch`，后续 `make build`、`make verify`、`make pack` 和 `make release` 的用法不变。

## 产物位置

构建产物写入：

```text
${WORKDIR}/outputs/
```

常见文件名：

```text
china-guangxi-20260818.base.pmtiles
china-guangxi-20260818.base.pmtiles.sha512
china-guangxi-20260818.base.manifest.json
china-guangxi-20260818.base.attribution.json
china-guangxi-20260818.building.pmtiles
china-guangxi-20260818.building.pmtiles.sha512
china-guangxi-20260818.building.manifest.json
china-guangxi-20260818.building.attribution.json
china-guangxi-20260818.import.zip
china-guangxi-20260818.import.zip.sha512
china-guangxi-20260818.bundle.tar.gz
china-guangxi-20260818.bundle.zip
```

`ROLE=building` 只有在 `config/regions.yaml` 中对应 region 启用 building metadata 时才会构建。否则使用 `ROLE=both` 会跳过 building 并给出 warning。

## 构建产物与运行时 map_root 的边界

`huavd-map-build` 的 `${WORKDIR}/outputs/` 是构建输出目录，不是 `huavd-map` 的运行时地图目录。不要让 `huavd-map` 直接扫描 `/tmp/huavd-map-build/outputs`，也不要把 `WORKDIR` 默认值改成 `/tmp/huavd-map`。

`huavd-map` 的 PMTiles 消费入口是 `offline-maps` 状态机：先创建元数据记录，再把 PMTiles 放入 staging 目录，经过 SHA-512 校验和 import 后进入 `installed` 或 `active` 状态。`huavd-map-build` 只负责生成可交付的导入包和描述符，不执行导入、激活，也不写入 `huavd-map` 的主落盘目录。

导入元数据中的 `name` 必须是不带 `.pmtiles` 扩展名的 stem，例如：

```text
china-guangxi-20260818.base
```

`huavd-map` 会根据 `name` 自动追加 `.pmtiles`。如果把 `name` 写成 `china-guangxi-20260818.base.pmtiles`，运行时文件名会变成 `china-guangxi-20260818.base.pmtiles.pmtiles`。

## 准备导入包

已有 PMTiles、manifest、attribution 和 SHA-512 sidecar 后，可以生成给 `huavd-map` 导入工具消费的压缩包：

```bash
export REGION=china/guangxi
export YYYYMMDD=20260818
export ROLE=base

make prepare-import
```

需要 tar.gz 格式时：

```bash
make prepare-import IMPORT_FORMAT=tar
```

默认输出文件：

```text
${WORKDIR}/outputs/china-guangxi-20260818.import.zip
${WORKDIR}/outputs/china-guangxi-20260818.import.zip.sha512
```

压缩包内容：

```text
import-package/
  install.json
  .staging/
    {transfer_id}/
      china-guangxi-20260818.base.pmtiles
```

实际 archive 顶层就是 `install.json` 和 `.staging/`；上面的 `import-package/` 只是建议解压目录名。`prepare-import` 会读取 `${WORKDIR}/outputs/${SESSION}.${ROLE}.manifest.json` 和 `${WORKDIR}/outputs/${SESSION}.${ROLE}.pmtiles.sha512`，复制 PMTiles 到导入包 staging 缓存，并校验复制后的 SHA-512。脚本不会发送 HTTP 请求，也不要求 `huavd-map` 服务正在运行。

需要把当前 session 中可用的 role 聚合为一个导入包时：

```bash
make prepare-import-all
```

如果当前 region 没有 building 产物，`prepare-import-all` 会跳过 building 并给出 warning。导入包中的 `install.json` 包含 `offline_maps[]` 和可选的 `bundles[]` 元数据，接收端据此在 `huavd-map` 侧创建记录、复制 staging 文件并调用 import。

手动导入时，先把 `.import.zip` 解压到 `huavd-map` 约定的 `import-package/` 目录，使 `install.json` 与 `.staging/{transfer_id}/` 保持相对路径关系不变。之后在 `huavd-map` 侧按 `install.json` 创建 `offline-maps` 记录并执行 import；如果消费侧已经实现一键导入端点，则直接让该端点读取解压后的 `install.json`。

## Pack 产物与 install.json

`make pack`、`make pack-tar`、`make pack-zip` 生成的是分发包，不是 `huavd-map` 运行时直接读取的目录。打包时会保留既有文件：

```text
*.pmtiles
*.pmtiles.sha512
*.manifest.json
*.attribution.json
```

同时在包内新增：

```text
install.json
```

`install.json` 描述如何把包内 PMTiles 作为 `offline-maps` 单资产导入到 `huavd-map`，包括稳定的 `id`、不带扩展名的 `name`、`source-id`、`asset-role`、`source-type`、`coord-system`、`checksum` 和 staging 文件名。bundle 只表达多个 offline-map 的数据库关联关系，不复制 PMTiles 字节，也不替代 `huavd-map` 的导入状态机。

## DEM 角色

DEM（数字高程）是独立于 OSM PBF 的离线栅格资产，使用 `config/dem.yaml` 中已声明的授权源（不要在脚本里硬编码公共下载 URL）。`make build`/`make release` 默认不跑 DEM，需要按下面的端到端流程单独走：

```bash
unset HUAVD_MAP_PACKAGE_VERSION \
      HUAVD_MAP_PACKAGE_VERSION_DEM

export REGION=china/guangxi
export YYYYMMDD=20260818
export DEM_SOURCE=srtm                # config/dem.yaml 中声明的源 id
export DEM_ENCODING=terrarium         # mapbox-terrain-rgb | terrarium | heightmap-u16
export DEM_INPUT=/data/srtm/guangxi.tif  # 已有授权 TIFF；或配合 make fetch-dem 拉取

make fetch-dem
make build-dem
make verify-dem
make pack   ROLE=all FORMAT=zip      # 一次性把 base/building/dem 打入 bundle
make prepare-import-all
```

`make fetch-dem` 把授权 DEM 拷贝到 `${WORKDIR}/mirror/dem/`，并写入可被
`build-dem.sh` 识别的 metadata；`make build-dem` 依赖 `pmtiles` CLI 把 TIFF 栅格
生成 DEM PMTiles。`build-dem.sh:99` 会调用 `region_package_version "${REGION}" dem`，
**DEM 现在强依赖 `package_version` 字段**：未设置 `huavd.default_package_version_template`
或对应 region 模板时（例如自定义 region 还没填 `package_version_template`），
脚本会 `die` 退出，避免写出没有版本号的 DEM manifest。

`make verify-dem` 总是 `--strict` 模式，会校验：

- `manifest.huavd_record.package_version` 非空且匹配 `^[A-Za-z0-9._+-]+$`。
- PMTiles magic / spec_version / raster tile_type。
- metadata 包含 `dem-encoding`（`mapbox-terrain-rgb` / `terrarium` / `heightmap-u16`）和 `huavd:vertical-datum`。
- PMTiles / manifest / sha512 sidecar 三者一致。

DEM 在 `install.json` 中作为 `offline_maps[]` 的 `asset-role=dem-raster` 条目出现，
`bundles[].bundle-version` 取 base role 的 `package-version`（不是 dem 自己的）。

## 清理当前 session

清理当前 session 的 staging、pack cache 和 outputs：

```bash
make clean
```

该目标不会删除 Geofabrik mirror、tags-filter/config cache，也不会清理 setup 编译缓存。

## 文档预览

安装文档依赖：

```bash
pnpm install
```

启动预览服务：

```bash
pnpm dev
```

默认访问地址：

```text
http://127.0.0.1:22592/
```

构建静态文档：

```bash
pnpm run docs:build
```
