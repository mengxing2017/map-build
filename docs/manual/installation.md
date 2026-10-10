# 环境安装与渲染资源

[返回手册目录](./index.md)

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

图片构建默认使用 Native 渲染器。团队须先配置完整 Native 安装或可信本地运行包，
setup 自动校验并创建固定入口，doctor 执行真实渲染自检。
安装来源配置和两条命令生成图片 ZIP 的流程见 [图片地图操作](../operations/native-renderer-build.md)。

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
