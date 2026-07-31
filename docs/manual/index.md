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
- 网络需要能访问 GitHub、GitHub Releases、Geofabrik 下载源和 Go module 下载源。
- 构建 tippecanoe 需要 C++ 编译器、`make`、`pkg-config`、SQLite3 开发头文件/库和 zlib 开发头文件/库。
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

`devbox run setup` 会安装或检查以下命令：

| 命令 | 用途 |
| :--- | :--- |
| `osmium` | 下载后的 PBF tag 过滤和 GeoJSONSeq 导出 |
| `tippecanoe` | 将 GeoJSONSeq 转换为 PMTiles |
| `pmtiles` | 读取和修改 PMTiles metadata |

安装完成后必须执行：

```bash
devbox run doctor
```

输出 `doctor: OK` 后再开始下载和构建数据。

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

## 命令使用索引

日常使用优先通过 `make` 入口执行。`scripts/*.sh` 是同一套能力的直连脚本，适合 CI、排障或只重跑某个内部阶段时使用。

所有命令默认在仓库根目录执行。构建数据写入 `WORKDIR`，默认是 `/tmp/huavd-map-build`；仓库目录只保存脚本、配置和文档。

### 通用变量

`make` 变量可以通过环境变量声明，也可以在命令行临时覆盖：

```bash
export REGION=china/guangxi
export YYYYMM=202607
make build

make build REGION=china/guangxi YYYYMM=202607 ROLE=base
```

| 变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `WORKDIR` | `/tmp/huavd-map-build` | 构建工作目录，包含 `mirror/`、`staging/`、`cache/`、`outputs/` |
| `REGION` | `china/guangxi` | region id，必须存在于 `config/regions.yaml` |
| `YYYYMM` | 当前 UTC 月 | 输出版本月份，格式为 6 位数字，例如 `202607` |
| `SESSION` | `{region-slug}-{YYYYMM}` | 构建会话名，例如 `china-guangxi-202607`；通常不需要手动设置 |
| `INPUT` | 空 | `make build` 的输入 PBF；为空时自动使用 `mirror/{geofabrik.basename}` |
| `ROLE` | `both` | 构建或处理的资产角色：`base`、`building`、`both` |
| `FORMAT` | `both` | `make pack` 的包格式：`tar`、`zip`、`both` |
| `IMPORT_FORMAT` | `zip` | `make prepare-import` 的导入包格式：`zip` 或 `tar` |
| `GLYPH` | `0` | `make build` 是否同时生成 glyph 和 style：`0` 或 `1` |
| `HUAVD_MAP_BUILD_MACHINE_HOME` | `/opt/huavd-map-build` | 构建机初始化目标目录，用于 `init-build-machine-workdir` |

`SESSION` 与 `YYYYMM` 同时设置时，以显式 `SESSION` 为准；脚本会从 `SESSION` 末尾反推 `YYYYMM`。`ROLE=both` 会处理 base 和 building，其中 building 只有在 region 配置为 `huavd.asset_role: building-vector` 且 `huavd.source_type: derived-building` 时才可用。

### Makefile 入口

| 命令 | 用途 | 常用示例 |
| :--- | :--- | :--- |
| `make setup` | 安装或检查 `osmium`、`tippecanoe`、`pmtiles` 等工具 | `make setup` |
| `make doctor` | 检查外部命令、YAML/JSON 解析和关键配置 | `make doctor` |
| `make init` | `make init-workdir` 的别名 | `make init` |
| `make init-workdir` | 初始化当前 `WORKDIR` 目录结构 | `make init-workdir SESSION=china-guangxi-202607` |
| `make install-config` | 初始化 `WORKDIR` 并复制当前 `config/` | `make install-config WORKDIR=/data/huavd-map-build` |
| `make init-build-machine-workdir` | 初始化构建机固定目录 | `make init-build-machine-workdir SESSION=china-guangxi-202607` |
| `make install-build-machine-config` | 初始化构建机固定目录并复制配置 | `make install-build-machine-config` |
| `make catalog` | 从 `config/regions.yaml` 生成 region catalog 快照 | `make catalog` |
| `make fetch` | 下载 region 配置中的 Geofabrik PBF 和 `.md5`，并执行 MD5 校验 | `make fetch REGION=china/guangxi` |
| `make build` | 从 PBF 构建 PMTiles、metadata、manifest、attribution 和 sha512 | `make build REGION=china/guangxi YYYYMM=202607 ROLE=base` |
| `make glyph` | 生成当前 session 的 glyphs 目录 | `make glyph REGION=china/guangxi YYYYMM=202607` |
| `make style` | 生成当前 session 的 MapLibre style JSON | `make style REGION=china/guangxi YYYYMM=202607` |
| `make verify` | 验证 PMTiles header、metadata、manifest 和 SHA-512 | `make verify REGION=china/guangxi YYYYMM=202607 ROLE=both` |
| `make pack` | 生成 tar/zip 分发包 | `make pack SESSION=china-guangxi-202607 ROLE=both FORMAT=both` |
| `make pack-tar` | 只生成 `.bundle.tar.gz` | `make pack-tar SESSION=china-guangxi-202607 ROLE=base` |
| `make pack-zip` | 只生成 `.bundle.zip` | `make pack-zip SESSION=china-guangxi-202607 ROLE=base` |
| `make prepare-import` | 为单个 role 生成 `huavd-map` 导入包；`ROLE=both` 时会转为 `base` | `make prepare-import ROLE=base IMPORT_FORMAT=zip` |
| `make prepare-import-all` | 将当前 session 中可用的 base/building 聚合为一个导入包 | `make prepare-import-all IMPORT_FORMAT=tar` |
| `make clean` | 删除当前 session 的 staging、pack/import cache 和 outputs | `make clean SESSION=china-guangxi-202607 ROLE=both` |
| `make all` | 执行 `build` 和 `pack` | `make all REGION=china/guangxi YYYYMM=202607` |
| `make release` | 执行 `build`、`pack`、`verify` | `make release REGION=china/guangxi YYYYMM=202607` |
| `make release-tar` | 执行 `build`、`pack-tar`、`verify` | `make release-tar REGION=china/guangxi YYYYMM=202607` |
| `make release-zip` | 执行 `build`、`pack-zip`、`verify` | `make release-zip REGION=china/guangxi YYYYMM=202607` |

`make release`、`make release-tar`、`make release-zip` 不会自动下载 PBF。首次构建通常先执行 `make fetch`，或通过 `INPUT=/path/to/file.osm.pbf` 指向已有文件。

`make catalog` 的默认输出是 `config/derived/catalog.json`，这是派生文件，不作为构建产物提交。需要写到其他位置时使用脚本直连入口的 `OUTPUT` 变量。

### 脚本直连入口

多数脚本支持以下通用参数：

```text
--workdir=<path>
--region=<id>
--yyyymm=YYYYMM
--session=<session>
--role=base|building|both
```

脚本也会读取同名环境变量。相对输入路径解析规则与 `make` 一致：`mirror/`、`cache/`、`staging/`、`outputs/` 开头的路径会按 `WORKDIR` 下的路径处理。

| 脚本 | 用法 |
| :--- | :--- |
| `./scripts/setup-tools.sh` | 安装工具链；通过 `TIPPECANOE_VERSION`、`TIPPECANOE_SOURCE_TARBALL`、`TIPPECANOE_BINARY_URL`、`PMTILES_VERSION`、`INSTALL_PREFIX` 等环境变量控制 |
| `./scripts/doctor.sh` | 检查命令和配置是否可用 |
| `./scripts/fetch.sh` | `--region=<id> [--workdir=<path>] [--limit-rate=10m]` |
| `./scripts/build.sh` | `--input=<path-to.osm.pbf> --region=<id> [--yyyymm=YYYYMM] [--role=base\|building\|both] [--workdir=<path>] [--glyph=0\|1] [--force]` |
| `./scripts/glyph.sh` | `--region=<id> [--yyyymm=YYYYMM] [--workdir=<path>] [--locales=all\|tag[,tag...]] [--force]` |
| `./scripts/style.sh` | `--region=<id> [--yyyymm=YYYYMM] [--workdir=<path>] [--locale=<tag>] [--pmtiles-url=<url>]` |
| `./scripts/verify.sh` | `--region=<id> --role=<base\|building\|both> [--yyyymm=YYYYMM] [--session=<session>] [--strict]` |
| `./scripts/pack.sh` | `--session=<session> [--role=base\|building\|both] [--format=tar\|zip\|both] [--workdir=<path>]` |
| `./scripts/prepare-import.sh` | `--session=<session> [--role=base\|building\|both] [--format=tar\|zip] [--output=<archive-path>] [--transfer-id=<id>] [--workdir=<path>] [--region=<id>] [--yyyymm=YYYYMM]` |
| `./scripts/region-pbf-basename.sh` | `[region]`，输出 region 配置中的 `geofabrik.basename` |
| `./scripts/manifest-catalog.sh` | 生成 region catalog；默认读取 `config/regions.yaml`，写入 `config/derived/catalog.json`；可用 `CONFIG_PATH` 和 `OUTPUT` 覆盖 |
| `./scripts/init-workdir.sh` | 初始化目录；通过 `HUAVD_MAP_BUILD_HOME`、`HUAVD_MAP_BUILD_SESSION`、`HUAVD_MAP_BUILD_COPY_CONFIG=1` 等环境变量控制 |
| `./scripts/generate-region-skeletons.rb` | `--iso3166-2-csv=<path> [--existing-config=config/regions.yaml] [--output=config/regions.yaml]` |

内部阶段脚本通常由 `build.sh` 调用。只有在排查某一层处理结果时才建议直接运行：

| 阶段脚本 | 用法 |
| :--- | :--- |
| `./scripts/tags-filter.sh` | `--input=<pbf> --region=<id> [--layers=all\|layer[,layer...]] [--workdir=<path>] [--yyyymm=YYYYMM]` |
| `./scripts/export.sh` | `--region=<id> [--layers=all\|layer[,layer...]] [--workdir=<path>] [--yyyymm=YYYYMM]` |
| `./scripts/normalize.sh` | `--region=<id> [--layers=all\|layer[,layer...]] [--workdir=<path>] [--yyyymm=YYYYMM]` |
| `./scripts/tippecanoe.sh` | `--region=<id> --role=<base\|building> [--workdir=<path>] [--yyyymm=YYYYMM]` |
| `./scripts/metadata.sh` | `--pmtiles=<path> --region=<id> --role=<base\|building> [--workdir=<path>] [--yyyymm=YYYYMM]` |
| `./scripts/manifest.sh` | `--region=<id> --role=<base\|building> [--workdir=<path>] [--yyyymm=YYYYMM]` |
| `./scripts/attribution.sh` | `--region=<id> --role=<base\|building> [--workdir=<path>] [--yyyymm=YYYYMM]` |

### 常用命令组合

默认 region 快速构建：

```bash
make fetch
make release
```

使用已有 PBF，不走网络下载：

```bash
make release REGION=china/guangxi YYYYMM=202607 INPUT=/data/osm/guangxi-260726.osm.pbf ROLE=base
```

生成 PMTiles 后再补 glyph 和 style：

```bash
make glyph REGION=china/guangxi YYYYMM=202607
make style REGION=china/guangxi YYYYMM=202607
make pack REGION=china/guangxi YYYYMM=202607 ROLE=base FORMAT=zip
```

构建时同时生成 glyph 和 style：

```bash
make build REGION=china/guangxi YYYYMM=202607 GLYPH=1
make pack REGION=china/guangxi YYYYMM=202607 ROLE=base FORMAT=zip
```

准备 `huavd-map` 导入包：

```bash
make prepare-import REGION=china/guangxi YYYYMM=202607 ROLE=base IMPORT_FORMAT=zip
```

只重跑基础 PMTiles 验证：

```bash
./scripts/verify.sh --region=china/guangxi --yyyymm=202607 --role=base --strict
```

## 构建一次地图数据

推荐使用“一次声明、自动继承”的操作模式。先声明构建上下文，后续 `make` 命令会自动读取这些环境变量，无需在每条命令里重复传参。

所有 `make` 命令都应在项目仓库根目录执行。`WORKDIR` 是数据工作目录，不是执行 `make` 的目录；不要在 `${WORKDIR}` 或 `${WORKDIR}/mirror` 中直接运行 `make release`。

```bash
export REPO_ROOT=/path/to/huavd-map-build
cd "${REPO_ROOT}"
export REGION=china/guangxi
export YYYYMM=202607
# export WORKDIR=/tmp/huavd-map-build
# export ROLE=both
```

`WORKDIR` 默认是 `/tmp/huavd-map-build`，可以省略。`ROLE` 默认是 `both`，会构建 base，并在 region 启用 building metadata 时同时构建 building；如果只需要基础图层，可设置 `export ROLE=base`。`SESSION` 会由 `REGION` 和 `YYYYMM` 自动推导，例如 `china/guangxi` 与 `202607` 会得到 `china-guangxi-202607`，日常操作不需要手动指定。

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

其中 `geofabrik.basename` 来自 `config/regions.yaml`，与 `make fetch` 下载和校验的文件名保持一致。`YYYYMM` 只用于输出 session 和产物版本，不参与输入 PBF 文件名推导。对于 `china/guangxi`，当前配置的默认输入会解析为：

```text
/tmp/huavd-map-build/mirror/guangxi-latest.osm.pbf
```

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
export YYYYMM=202607

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
  export YYYYMM=202607
  make fetch
  make release
done
```

### CI 场景

CI 可以在 job 环境中声明变量，然后使用相同的短命令：

```bash
export REGION=china/guangxi
export YYYYMM=202607
export WORKDIR=/tmp/huavd-map-build-ci
export ROLE=base

devbox run doctor
make fetch
make release
```

如果 CI 环境不能访问 Geofabrik，就不要执行 `make fetch`；应先把 PBF 作为 CI artifact 或缓存放入当前 `WORKDIR`，或通过 `INPUT` 指向已有文件：

```bash
export REGION=china/guangxi
export YYYYMM=202607
export WORKDIR=/tmp/huavd-map-build-ci
export ROLE=base
export INPUT=/cache/maps/guangxi-latest.osm.pbf

devbox run doctor
make release
```

现有的命令行变量覆盖方式仍然兼容，适合临时切换参数；推荐文档中的主流程使用环境变量继承模式。

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

浏览器或内部镜像下载出的文件名可能是带日期的快照名，例如 `guangxi-260726.osm.pbf`。这种文件名不会由 `REGION` 和 `YYYYMM` 自动推导，推荐直接用 `INPUT` 指定。

方案 A：保留实际下载文件名，通过 `INPUT` 指定：

```bash
export REPO_ROOT=/path/to/huavd-map-build
cd "${REPO_ROOT}"
export REGION=china/guangxi
export YYYYMM=202607
export WORKDIR=/tmp/huavd-map-build
export INPUT=/path/to/guangxi-260726.osm.pbf

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
export YYYYMM=202607
export WORKDIR=/tmp/huavd-map-build

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
china-guangxi-202607.base.pmtiles
china-guangxi-202607.base.pmtiles.sha512
china-guangxi-202607.base.manifest.json
china-guangxi-202607.base.attribution.json
china-guangxi-202607.building.pmtiles
china-guangxi-202607.building.pmtiles.sha512
china-guangxi-202607.building.manifest.json
china-guangxi-202607.building.attribution.json
china-guangxi-202607.import.zip
china-guangxi-202607.import.zip.sha512
china-guangxi-202607.bundle.tar.gz
china-guangxi-202607.bundle.zip
```

`ROLE=building` 只有在 `config/regions.yaml` 中对应 region 启用 building metadata 时才会构建。否则使用 `ROLE=both` 会跳过 building 并给出 warning。

## 构建产物与运行时 map_root 的边界

`huavd-map-build` 的 `${WORKDIR}/outputs/` 是构建输出目录，不是 `huavd-map` 的运行时地图目录。不要让 `huavd-map` 直接扫描 `/tmp/huavd-map-build/outputs`，也不要把 `WORKDIR` 默认值改成 `/tmp/huavd-map`。

`huavd-map` 的 PMTiles 消费入口是 `offline-maps` 状态机：先创建元数据记录，再把 PMTiles 放入 staging 目录，经过 SHA-512 校验和 import 后进入 `installed` 或 `active` 状态。`huavd-map-build` 只负责生成可交付的导入包和描述符，不执行导入、激活，也不写入 `huavd-map` 的主落盘目录。

导入元数据中的 `name` 必须是不带 `.pmtiles` 扩展名的 stem，例如：

```text
china-guangxi-202607.base
```

`huavd-map` 会根据 `name` 自动追加 `.pmtiles`。如果把 `name` 写成 `china-guangxi-202607.base.pmtiles`，运行时文件名会变成 `china-guangxi-202607.base.pmtiles.pmtiles`。

## 准备导入包

已有 PMTiles、manifest、attribution 和 SHA-512 sidecar 后，可以生成给 `huavd-map` 导入工具消费的压缩包：

```bash
export REGION=china/guangxi
export YYYYMM=202607
export ROLE=base

make prepare-import
```

需要 tar.gz 格式时：

```bash
make prepare-import IMPORT_FORMAT=tar
```

默认输出文件：

```text
${WORKDIR}/outputs/china-guangxi-202607.import.zip
${WORKDIR}/outputs/china-guangxi-202607.import.zip.sha512
```

压缩包内容：

```text
import-package/
  install.json
  .staging/
    {transfer_id}/
      china-guangxi-202607.base.pmtiles
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
