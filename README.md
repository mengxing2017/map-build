# huavd-map-build

`huavd-map-build` 将 Geofabrik 提供的 OpenStreetMap `.osm.pbf` 区域数据构建为可离线分发的 PMTiles 地图包。项目以 Bash 脚本和声明式 YAML 配置组成，面向 HUAVD 的离线地图生产流程，也可作为基于 OSM、Tippecanoe 和 PMTiles 的区域地图构建参考。

## 功能概览

Native 图片瓦片支持通过 Python 调用独立的 `huavd-native-render`，无需将静态库放入本项目或重写 Python 流水线。源码准备、离线构建、运行环境和小范围验证见 [Native 渲染操作手册](docs/operations/native-renderer-build.md)。默认引擎为 `maplibre-native-headless`，旧引擎可显式选择。

- 从 `config/regions.yaml` 读取区域目录，下载并校验对应的 Geofabrik PBF 与 MD5 文件。
- 按 `config/layers.yaml` 中的 OSM 标签规则过滤、导出和规范化 GeoJSONSeq，构建道路、铁路、水域、水系、土地利用、建筑、行政区、自然要素、山峰、休闲区和多类标注等 16 个矢量图层。
- 使用 Tippecanoe 将矢量图层生成 gzip 压缩的 MVT PMTiles；缩放级别、密度控制和高密度区域覆盖均由 `config/tippecanoe.yaml` 配置。
- 支持 `base` 基础矢量、可选 `building` 建筑矢量、由 base/style 预烘焙的 WebP `raster_bake` 图片瓦片，以及来自已授权本地或内网输入的 `dem` 栅格地形。图片瓦片与同源 base、style、glyph、sprite 共同交付，不是孤立资产。
- 支持显式配置的多区域低缩放概览图：先验证所有源 PBF 来自同一 OSM replication snapshot，再用 `osmium merge` 合并并构建独立的 `overview-vector` PMTiles。
- 支持从已验证、同快照的本地 PBF 合成分层 `base-vector` 资产；配置可表达地级市到省、省到国家、国家到洲和洲到世界。当前提供中国 composite，产物复用 `china` 的地图身份并可生成 `install.json`。
- 统一处理多语言名称、数值和布尔属性；建筑缺失高度时可按楼层推导高度，用于 3D 建筑渲染。
- 为每个资产写入 PMTiles 元数据、构建清单、OpenStreetMap 署名信息和 SHA-512 校验文件，并验证 PMTiles 格式、图层元数据、清单和哈希。
- 将构建结果打包为 `tar.gz`、`zip` 或两者，并生成 `install.json`、`SHA256SUMS` 和可选的导入包，便于离线安装和传输。
- 可生成 MapLibre 样式、精灵图和 glyph 字体资源；提供样式、视口和图层密度检查，以及区域成品差异对比。

## 构建流程

```text
区域配置 / OSM PBF
        |
  下载与输入校验
        |
标签过滤 -> GeoJSONSeq 导出 -> 属性规范化
        |
  Tippecanoe PMTiles 构建
        |
元数据、清单、署名、校验
        |
 tar.gz / zip 离线地图包
```

基础矢量构建会处理全部基础图层；单独构建 `building` 时只处理建筑图层。`ROLE=both` 在区域未启用建筑角色时会保留基础矢量产物并记录跳过原因。

## 快速使用

首次安装工具后，按区域获取、构建、验证和打包：

```bash
devbox run setup
devbox run doctor
make fetch REGION=china/guangxi
make build REGION=china/guangxi YYYYMMDD=20260829 ROLE=both
make verify REGION=china/guangxi YYYYMMDD=20260829 ROLE=both
make pack REGION=china/guangxi YYYYMMDD=20260829 ROLE=both FORMAT=both
```

若 PBF 已在本地，可跳过下载并指定输入路径：

```bash
make build REGION=china/guangxi YYYYMMDD=20260829 \
  INPUT=/path/to/guangxi-latest.osm.pbf ROLE=base
```

使用同一手动 PBF 构建可消费的矢量底图和图片瓦片：

```bash
make build REGION=china/guangxi YYYYMMDD=20260829 \
  INPUT=/path/to/guangxi-latest.osm.pbf ROLE=base_raster
```

`base_raster` 会自动生成 glyph、sprite 和 vector/raster style，再执行 Python raster bake、质量门与 staged publication。已有同会话 base 和支撑资源时，可使用 `ROLE=raster_bake` 只重跑图片阶段。

默认工作目录为 `/tmp/huavd-map-build`。相对 `INPUT` 会在该目录中解析；可通过 `WORKDIR` 指向持久化构建目录。`make release` 会为每次发布隔离工作目录，并按构建、打包、校验的顺序执行。

## 多区域概览图

概览图配置位于 `config/overviews.yaml`，第一版只接受显式 `source_regions`。它是独立 artifact 类型，不改变 `make build`、`make verify` 或 `make pack` 的单区域行为。

概览构建不会下载源数据。先将每个配置区域的 PBF 与同名 `.md5` sidecar 放入 `${WORKDIR}/mirror/`；所有输入必须具有完全相同的 OSM replication timestamp。预检还会校验 MD5、记录每个源文件的 SHA-512 和 sequence，并拒绝缺失或不同快照的输入。不同 extract 的 sequence 仅用于审计，不作为跨文件相等条件。

```bash
make build-overview OVERVIEW=south-china-overview YYYYMMDD=20260829
make verify-overview OVERVIEW=south-china-overview YYYYMMDD=20260829
make pack-overview OVERVIEW=south-china-overview YYYYMMDD=20260829 FORMAT=both
make derived-inventory DERIVED_MAP=china-base
make build-derived-map DERIVED_MAP=china-base YYYYMMDD=20260829
make verify-derived-map DERIVED_MAP=china-base YYYYMMDD=20260829
make pack-derived-map DERIVED_MAP=china-base YYYYMMDD=20260829 FORMAT=both
```

合并 PBF 缓存按 overview id、配置 schema、源文件名、SHA-512 和 replication sequence 内容寻址，位于 `${WORKDIR}/cache/merge/<overview-id>/`。概览产物命名如下：

```text
<overview-id>-<yyyymmdd>.overview.pmtiles
<overview-id>-<yyyymmdd>.overview.pmtiles.sha512
<overview-id>-<yyyymmdd>.overview.manifest.json
<overview-id>-<yyyymmdd>.overview.attribution.json
<overview-id>-<yyyymmdd>.overview.bundle.tar.gz
<overview-id>-<yyyymmdd>.overview.bundle.zip
```

概览 bundle 当前仅用于审核，包含 PMTiles、manifest、attribution、校验文件和 `SHA256SUMS`，不会生成 `install.json`。在客户端和安装描述符共同支持 `asset-role: overview-vector` 前，不应将其发布为可安装离线地图。

## 输出产物

以 `china-guangxi-20260829` 会话为例，产物位于 `${WORKDIR}/outputs/`：

```text
china-guangxi-20260829.base.pmtiles
china-guangxi-20260829.base.pmtiles.sha512
china-guangxi-20260829.base.manifest.json
china-guangxi-20260829.base.attribution.json
china-guangxi-20260829.building.pmtiles              # 已启用时生成
china-guangxi-20260829.raster_bake.pmtiles            # 请求 raster 角色时生成
china-guangxi-20260829.raster_bake.ready.json         # 全部质量门通过后最后写入
china-guangxi-20260829.style-raster.json              # 图片底图 + 矢量标注消费样式
china-guangxi-20260829.dem.pmtiles                   # 构建 DEM 时生成
china-guangxi-20260829.bundle.tar.gz
china-guangxi-20260829.bundle.zip
```

包内包含已声明资产、各自的校验与元数据文件、`install.json` 和 `SHA256SUMS`。样式、glyph 和精灵图资源已生成时也会随包分发。

## 配置与命令

区域、数据来源与 HUAVD 元数据在 `config/regions.yaml` 中维护；图层标签和最终属性在 `config/layers.yaml` 中维护；Tippecanoe 参数在 `config/tippecanoe.yaml` 中维护。新增或变更图层时，还应同步更新对应的 `config/export-config/*.json`、Tippecanoe 图层列表和验证预期。

`config/tier-profiles.yaml` 为明确列出的单区域 `base` 资产定义低缩放 profile。profile 可以裁剪基础图层、按属性保留要素，并将 Feature 顶层的 Tippecanoe min/max zoom 写入 GeoJSONSeq；它不会改变 building role，也不会用于 multi-region overview。样式生成会自动省略 profile 未包含的 source layer，严格校验会拒绝样式引用这类缺失图层。当前 `china` 显式使用 `country-low`（z0-z10，禁用自动扩展 zoom）。未列出的 region 保持既有 16 图层和 Tippecanoe 参数。

常用命令：

```bash
make catalog                                      # 输出区域资产清单
make fetch REGION=china/guangxi                   # 下载并校验 OSM PBF
make build REGION=china/guangxi ROLE=base         # 构建基础矢量
make build REGION=china/guangxi ROLE=base_raster  # 构建基础矢量和 WebP 图片瓦片
make build REGION=china/guangxi ROLE=raster_bake  # 复用已有 base，只重跑图片阶段
make build-dem REGION=china/guangxi               # 从已授权输入构建 DEM
make build-overview OVERVIEW=south-china-overview  # 构建多区域低缩放概览图
make verify-overview OVERVIEW=south-china-overview # 验证概览图
make pack-overview OVERVIEW=south-china-overview   # 生成概览审核包
make derived-inventory DERIVED_MAP=china-base # 检查派生地图 source assets
make build-derived-map DERIVED_MAP=china-base  # 按图层合成并构建派生地图
make pack-derived-map DERIVED_MAP=china-base   # 生成可安装的派生地图包
make glyph REGION=china/guangxi                   # 生成 MapLibre glyph
make sprite REGION=china/guangxi                  # 生成样式精灵图
make style REGION=china/guangxi                   # 生成 MapLibre 样式
make lint                                         # 检查样式与视口配置
make prepare-import-all REGION=china/guangxi      # 准备离线导入包
make diff-products REGION_A=china/guangxi REGION_B=china/guangdong
```

## 环境准备

本项目使用 [devbox](https://www.jetify.com/devbox) 管理开发环境。`devbox shell` 只负责进入环境和设置 `PATH`，不会自动编译或下载 osmium、tippecanoe、pmtiles；首次使用前需要手动执行一次安装。

### 前置条件

- devbox >= 0.14.2。
- 推荐 Linux x86_64。Ubuntu/Debian 可通过 `apt-get` 安装 osmium；其他 Linux 发行版会回退到源码编译。
- macOS 可进入 devbox 环境后使用源码编译 fallback，或自行用系统包管理器安装同名工具。
- 网络需要能访问 GitHub、GitHub Releases，以及 Go module 下载源。
- 如需生成 MapLibre glyph/style，还需要本机 `PATH` 中存在 `build-glyphs`，并准备 `config/glyphs.yaml` 指向的字体文件。

### 快速启动

```bash
devbox shell
devbox run setup
devbox run doctor
```

如果已经在 `devbox shell` 中，也可以直接执行：

```bash
./scripts/setup-tools.sh
./scripts/doctor.sh
```

### 验证安装

```bash
devbox run doctor
```

### 发布构建工作目录

`make release`、`make release-tar` 和 `make release-zip` 会默认把实际工作目录隔离到 `${WORKDIR}/${SESSION}`。例如：

```bash
make release WORKDIR=/home/dev/data/map REGION=china/anhui YYYYMMDD=20260818 INPUT=/path/to/anhui.osm.pbf
```

产物会写入：

```text
/home/dev/data/map/china-anhui-20260818/outputs/
```

如需指定完整发布目录，可覆盖 `RELEASE_WORKDIR`。单独执行 `make build`、`make pack`、`make verify` 时仍直接使用 `WORKDIR`，便于对已有工作目录做增量操作。图片瓦片使用同一组入口，并通过 `ROLE=base_raster`、`raster_bake` 或 `both_raster` 选择。

### 自动安装行为

`devbox run setup` 会优先尝试预编译二进制或系统二进制包，失败后再回退到源码编译。tippecanoe 官方 Releases 当前不提供 Linux 预编译资产，默认会走源码编译；如果 `/tmp/tippecanoe.tar.gz` 已存在，setup 会直接复用，也可通过 `TIPPECANOE_SOURCE_TARBALL` 指定其他本地源码包。如果有内部制品库，可通过 `TIPPECANOE_BINARY_URL` 指定二进制包。默认版本由 `scripts/setup-tools.sh` 维护，可通过环境变量覆盖：

```bash
TIPPECANOE_VERSION=2.79.0 PMTILES_VERSION=v1.31.2 devbox run setup
TIPPECANOE_SOURCE_TARBALL=/path/to/tippecanoe.tar.gz devbox run setup
```

`setup` 会通过 cargo 安装 `versatiles_glyphs`，再在 `$HOME/.local/bin` 写入兼容的 `build-glyphs` wrapper。devbox 环境通过 `rustup` 提供 cargo，并把 `$CARGO_HOME/bin` 和 `$HOME/.local/bin` 加入 `PATH`。如果需要固定内部 fork 或版本，可覆盖：

```bash
BUILD_GLYPHS_CRATE=versatiles_glyphs BUILD_GLYPHS_VERSION=0.9.1 devbox run setup
```

如果 `devbox run setup` 或 `devbox run doctor` 仍输出：

```text
build-glyphs is not installed; glyph.sh requires a local MapLibre glyph generator
```

默认 `make build` 不受影响，因为 `GLYPH=0`。只有执行 `make glyph` 或 `make build GLYPH=1` 时，才必须先解决 cargo 安装失败、网络访问、内部 crate 源配置或 wrapper PATH 问题。

生成 glyph 还需要字体文件。默认配置读取以下路径，文件名必须与 `config/glyphs.yaml` 一致：

```text
fonts/NotoSans-Regular.ttf
fonts/NotoSansCJKsc-Regular.otf
fonts/NotoSansCJKjp-Regular.otf
fonts/NotoSansCJKkr-Regular.otf
```

字体可来自团队内部制品库或官方 Noto 发布包；在分发 bundle 前需要确认字体和生成出的 glyph PBF 的再分发许可。

### 手动安装参考

优先使用 `devbox run setup`。以下命令只作为网络受限或自动安装失败时的手动参考。

#### osmium

##### Ubuntu/Debian：

```bash
sudo apt-get update
sudo apt-get install -y osmium-tool
```

##### 源码编译：

```bash
rm -rf /tmp/osmium-tool
git clone --depth=1 https://github.com/osmcode/osmium-tool.git /tmp/osmium-tool
cd /tmp/osmium-tool
mkdir -p build
cd build
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$HOME/.local" ..
cmake --build . -j"$(nproc)"
cmake --install .
```

#### tippecanoe

##### 编译依赖

编译 tippecanoe 需要 C++ 编译器、`make`、`pkg-config`、SQLite3 头文件/库和 zlib 头文件/库。Ubuntu/Debian：

```bash
sudo apt-get update
sudo apt-get install -y build-essential pkg-config libsqlite3-dev zlib1g-dev
```

注意：只安装 `sqlite3`/`zlib1g` 运行库不够，必须安装 `libsqlite3-dev`/`zlib1g-dev` 才有 `sqlite3.h` 和 `zlib.h`。如果在 devbox/Nix 内编译，不要混用系统 `/usr/lib` 的 sqlite/zlib；Nix 编译出的二进制可能会在运行时报 `libsqlite3.so.0` 找不到或 glibc 符号冲突。`scripts/setup-tools.sh` 会区分 Nix 编译器和系统编译器，显式传入 `INCLUDES`、`LIBS` 和 rpath `LDFLAGS`。

##### devbox/Nix 环境

在 devbox 内编译时，`devbox.json` 已声明 `gcc`、`gnumake`、`pkg-config`、`sqlite`、`zlib`。如果刚拉到这些配置，或遇到 `libsqlite3.so.0` 运行期错误，请先执行：

```bash
devbox install
devbox run setup
```

如果依赖安装在非标准路径，可显式覆盖 tippecanoe 编译路径：

```bash
TIPPECANOE_INCLUDES="-I/opt/sqlite/include -I/opt/zlib/include -I. -Iclipper2/include" \
TIPPECANOE_LIBS="-L/opt/sqlite/lib -L/opt/zlib/lib" \
TIPPECANOE_LDFLAGS="-Wl,-rpath,/opt/sqlite/lib -Wl,-rpath,/opt/zlib/lib" \
devbox run setup
```

在 devbox/Nix shell 内不要直接复制下面的手动编译命令，请使用：

```bash
devbox install
devbox run setup
```

##### 系统编译器源码编译

如果要使用系统 `libsqlite3-dev`/`zlib1g-dev`，请在 devbox 外使用系统编译器执行手动编译命令。

下面的源码编译命令适用于 devbox 外的系统编译器 + 系统 `libsqlite3-dev`/`zlib1g-dev` 环境：

```bash
TIPPECANOE_VERSION=2.79.0
rm -rf /tmp/tippecanoe
if [ ! -f /tmp/tippecanoe.tar.gz ]; then
  wget -O /tmp/tippecanoe.tar.gz "https://github.com/felt/tippecanoe/archive/refs/tags/${TIPPECANOE_VERSION}.tar.gz"
fi
mkdir -p /tmp/tippecanoe
tar -xzf /tmp/tippecanoe.tar.gz -C /tmp/tippecanoe --strip-components=1
cd /tmp/tippecanoe
TIPPECANOE_INCLUDES="$(pkg-config --cflags sqlite3 zlib 2>/dev/null) -I/usr/local/include -I/usr/include -I. -Iclipper2/include"
TIPPECANOE_LIBS="$(pkg-config --libs-only-L --libs-only-other sqlite3 zlib 2>/dev/null) -L/usr/local/lib -L/usr/lib/x86_64-linux-gnu -L/lib/x86_64-linux-gnu"
TIPPECANOE_LDFLAGS=""
for lib_dir in ${TIPPECANOE_LIBS}; do
  case "${lib_dir}" in
    -L*) TIPPECANOE_LDFLAGS="${TIPPECANOE_LDFLAGS} -Wl,-rpath,${lib_dir#-L}" ;;
  esac
done
make -j"$(nproc)" INCLUDES="${TIPPECANOE_INCLUDES}" LIBS="${TIPPECANOE_LIBS}" LDFLAGS="${TIPPECANOE_LDFLAGS}"
mkdir -p "$HOME/.local/bin"
cp tippecanoe "$HOME/.local/bin/"
```

##### rpath 检查

安装后可检查 rpath 是否包含 sqlite/zlib 所在目录：

```bash
readelf -d "$HOME/.local/bin/tippecanoe" | grep -E 'RPATH|RUNPATH'
```

##### 内部预编译包

如果团队维护了内部预编译包，可让 setup 脚本优先使用该包：

```bash
TIPPECANOE_BINARY_URL="https://artifacts.example.com/tippecanoe/2.79.0/tippecanoe-linux-x86_64.tar.gz" devbox run setup
```

#### pmtiles

##### Linux x86_64 预编译包：

```bash
PMTILES_VERSION=v1.31.2
PMTILES_VERSION_NO_V="${PMTILES_VERSION#v}"
rm -rf /tmp/pmtiles-bin /tmp/pmtiles.tar.gz
wget -O /tmp/pmtiles.tar.gz "https://github.com/protomaps/go-pmtiles/releases/download/${PMTILES_VERSION}/go-pmtiles_${PMTILES_VERSION_NO_V}_Linux_x86_64.tar.gz"
mkdir -p /tmp/pmtiles-bin "$HOME/.local/bin"
tar -xzf /tmp/pmtiles.tar.gz -C /tmp/pmtiles-bin
install -m 0755 "$(find /tmp/pmtiles-bin -type f -name pmtiles -print -quit)" "$HOME/.local/bin/pmtiles"
```

##### Go module 安装

若必须从 Go module 安装，`v1.31.2` 的 CLI 入口在 module 根目录：

```bash
PMTILES_VERSION=v1.31.2
go install "github.com/protomaps/go-pmtiles@${PMTILES_VERSION}"
```
