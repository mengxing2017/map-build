# 运行与故障处理

## 环境安装

首次使用：

```bash
devbox shell
devbox run setup
devbox run doctor
```

如果 `/tmp/tippecanoe.tar.gz` 已存在，setup 会复用它。也可以显式指定：

```bash
TIPPECANOE_SOURCE_TARBALL=/tmp/tippecanoe.tar.gz devbox run setup
```

## 构建示例

下载配置中的 PBF：

```bash
make fetch REGION=china/guangxi
```

构建 PMTiles：

```bash
make build REGION=china/guangxi YYYYMM=202607 ROLE=both INPUT=mirror/guangxi-latest.osm.pbf
```

验证并打包：

```bash
make verify REGION=china/guangxi YYYYMM=202607 ROLE=both
make pack SESSION=china-guangxi-202607 ROLE=both FORMAT=both
```

## 常见问题

### sqlite3.h 或 zlib.h 缺失

只安装运行库不够，编译 tippecanoe 需要开发头文件和库。devbox 环境中应通过 `devbox.json` 的 sqlite/zlib `out`、`dev` 输出提供依赖。

### libsqlite3.so.0 找不到

通常是 devbox/Nix 编译器与系统 `/usr/lib` sqlite/zlib 混用造成的。优先重新执行：

```bash
devbox install
devbox run setup
devbox run doctor
```

不要把系统 `libsqlite3.so.0` 复制或软链到全局目录作为长期修复。

### build-glyphs is not installed

如果看到：

```text
build-glyphs is not installed; glyph.sh requires a local MapLibre glyph generator
```

这是 glyph/style 生成前置条件缺失。默认 `make build` 使用 `GLYPH=0`，只构建 PMTiles 时可以暂时忽略；以下命令会失败，必须先安装：

```bash
make glyph REGION=china/guangxi YYYYMM=202607
make build REGION=china/guangxi YYYYMM=202607 GLYPH=1
```

在 devbox/Nix 环境中，不建议用全局 npm 安装作为标准处理方式。应先确认团队选择的 glyph 生成器来源，并让它在 devbox shell 的 `PATH` 中可见：

```bash
command -v build-glyphs
devbox run doctor
```

推荐处理方式：

- 如果 devbox/Nix 可提供稳定包，将 glyph 生成器加入 `devbox.json` 并提交 lock 更新。
- 在构建机镜像或内部制品中预装受控版本的 `build-glyphs`。
- 提供内部 wrapper，暴露同名 `build-glyphs` 命令。

fontnik 可以作为候选实现评估，但不要在未确认 Nix 兼容性时把 `npm install --global fontnik` 写入构建机标准流程。仅把 fontnik 加入 `package.json` 依赖也不够；当前 `glyph.sh` 不会调用 `pnpm exec`，仍要求 `build-glyphs` 作为普通命令出现在 `PATH` 中。

如果安装后 `glyph.sh` 报字体文件不存在，请按 `config/glyphs.yaml` 准备默认字体：

```text
fonts/NotoSans-Regular.ttf
fonts/NotoSansCJKsc-Regular.otf
fonts/NotoSansCJKjp-Regular.otf
fonts/NotoSansCJKkr-Regular.otf
```

字体可以来自内部制品库或官方 Noto 发布包；发布前需要确认字体和生成出的 glyph PBF 的再分发许可。

### PMTiles verify 失败

先确认文件和伴随产物存在：

```bash
ls -lh /tmp/huavd-map-build/outputs
```

再单独运行：

```bash
WORKDIR=/tmp/huavd-map-build ./scripts/verify.sh --region=china/guangxi --yyyymm=202607 --role=base
```

`root directory within 16 KiB range` 是 PMTiles v3 约束，不应简单删除。

## 清理

当前 session 清理：

```bash
make clean SESSION=china-guangxi-202607
```

该目标会删除当前 session 的 staging、pack cache 和 outputs 文件。它不会清理 mirror、tags-filter/config cache 或 setup 编译缓存。
