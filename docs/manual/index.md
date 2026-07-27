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

## 构建一次地图数据

推荐使用“一次声明、自动继承”的操作模式。先声明构建上下文，后续 `make` 命令会自动读取这些环境变量，无需在每条命令里重复传参。

```bash
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

其中 `geofabrik.basename` 来自 `config/regions.yaml`，与 `make fetch` 下载和校验的文件名保持一致。对于 `china/guangxi`，默认输入会解析为：

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

需要准备两个文件：

```text
{geofabrik.basename}
{geofabrik.basename}.md5
```

以 `china/guangxi` 为例，文件名是：

```text
guangxi-latest.osm.pbf
guangxi-latest.osm.pbf.md5
```

方案 A：放入默认 mirror 目录，让 `make build` 自动读取：

```bash
export REGION=china/guangxi
export YYYYMM=202607
export WORKDIR=/tmp/huavd-map-build

mkdir -p "${WORKDIR}/mirror"
# 将 guangxi-latest.osm.pbf 和 guangxi-latest.osm.pbf.md5 放入该目录后校验
(cd "${WORKDIR}/mirror" && md5sum -c guangxi-latest.osm.pbf.md5)

make release
```

方案 B：下载到任意路径，通过环境变量指定输入：

```bash
export REGION=china/guangxi
export YYYYMM=202607
export INPUT=/path/to/guangxi-latest.osm.pbf

make release
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
china-guangxi-202607.bundle.tar.gz
china-guangxi-202607.bundle.zip
```

`ROLE=building` 只有在 `config/regions.yaml` 中对应 region 启用 building metadata 时才会构建。否则使用 `ROLE=both` 会跳过 building 并给出 warning。

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
