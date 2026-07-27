# huavd-map-build

## 环境准备

本项目使用 [devbox](https://www.jetify.com/devbox) 管理开发环境。`devbox shell` 只负责进入环境和设置 `PATH`，不会自动编译或下载 osmium、tippecanoe、pmtiles；首次使用前需要手动执行一次安装。

### 前置条件

- devbox >= 0.14.2。
- 推荐 Linux x86_64。Ubuntu/Debian 可通过 `apt-get` 安装 osmium；其他 Linux 发行版会回退到源码编译。
- macOS 可进入 devbox 环境后使用源码编译 fallback，或自行用系统包管理器安装同名工具。
- 网络需要能访问 GitHub、GitHub Releases，以及 Go module 下载源。

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

### 自动安装行为

`devbox run setup` 会优先尝试预编译二进制或系统二进制包，失败后再回退到源码编译。tippecanoe 官方 Releases 当前不提供 Linux 预编译资产，默认会走源码编译；如果 `/tmp/tippecanoe.tar.gz` 已存在，setup 会直接复用，也可通过 `TIPPECANOE_SOURCE_TARBALL` 指定其他本地源码包。如果有内部制品库，可通过 `TIPPECANOE_BINARY_URL` 指定二进制包。默认版本由 `scripts/setup-tools.sh` 维护，可通过环境变量覆盖：

```bash
TIPPECANOE_VERSION=2.79.0 PMTILES_VERSION=v1.31.2 devbox run setup
TIPPECANOE_SOURCE_TARBALL=/path/to/tippecanoe.tar.gz devbox run setup
```

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
