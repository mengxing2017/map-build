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
