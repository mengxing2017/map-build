# 标准地图构建

本页的 `make build` 生成地图，不自动生成路网。需要同一 PBF 的导航路网时，参见 [地图与路网构建](./map-and-routing.md)。

[返回手册目录](./index.md)

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

## z19 标准矢量配置

构建工具支持通过 base 专属覆盖与 `standard-z19` 图层策略启用真实 z0–19。目前公共区域目录未启用该策略；合成局部提取区域仅用于测试。广西全域和其他 region 仍使用各自既有配置，独立 building、DEM 和 overview 不受影响。

使用前须先配置自己的局部提取区域，并在 Tippecanoe 区域覆盖中设置 `roles: [base]`、`max_zoom: 19`、`layer_zoom_profile: standard-z19` 和 `extend_zooms_if_still_dropping: false`。没有独立 Geofabrik 下载端点的局部区域必须提供已按行政边界提取并核验的本地 PBF，不能用父区域 PBF 冒充区域输入：

```bash
export REGION=your/configured/local-region
export YYYYMMDD=20261003
export ROLE=base
export WORKDIR=/data/huavd-qixing-vector-z19
export INPUT=/path/to/verified/qixing/source.osm.pbf
unset SESSION

make python-catalog-validate
make python-catalog-shadow
make build
make verify
```

配置按 defaults、高密度基线、角色设置、区域与角色覆盖、显式 tier profile 的顺序解析；局部区域通过 `layer_zoom_profile=standard-z19` 启用高层级图层策略。admin 和行政线仍保留各自截止层级，高等级地名保留既有 label tier 规则。

z19 深度校验会从 staged 道路、建筑和水体位置抽样解码最高层 MVT；仅把 header 改为 19 不能通过验收。构建后还需完成样式资源闭合、打包与客户端联调。HMI 的 source.maxzoom、图层显示上限和相机 zoom 是不同约束；包内有 z19 数据不代表目标设备已验收。

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

### 日常开发

声明一次 region 和构建日期，后续命令自动继承：

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

## 单独验证

只重跑基础 PMTiles 验证：

```bash
./scripts/verify.sh --region=china/guangxi --yyyymmdd=20260818 --role=base --strict
```

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

`make release` 会把本次会话隔离在 `${WORKDIR}/${SESSION}`；后续不应让根目录的 `make prepare-import` 去查找产物。使用 `make prepare-import-release`（单个默认 role）或 `make prepare-import-release-all`（聚合可用 role）会自动使用相同的 release 工作目录。也可以用 `make release-import` 或 `make release-import-all` 一次完成 build、pack、verify 和导入包准备。

使用上述方案 A 或方案 B 的手动 PBF 做小范围图片验证时，保留相同的 `WORKDIR`、`REGION`、`YYYYMMDD`、`INPUT`（方案 A）或 mirror 软链（方案 B），只增加图片范围参数：

```bash
BAKE_BBOX=108.2,22.7,108.4,22.9 \
BAKE_MIN_ZOOM=12 BAKE_MAX_ZOOM=14 \
make release ROLE=base_raster FORMAT=zip

make prepare-import-release ROLE=base_raster IMPORT_FORMAT=zip
```

示例 bbox 仅适用于覆盖广西南宁附近的输入；其他地区应改为输入范围内、包含道路和水体的窗口。第二条命令生成的 `.import.zip` 与 bundle 都位于 `${WORKDIR}/${SESSION}/outputs/`，其中包含 `raster_bake`、同源 `base`、图片底图样式和 glyph/sprite 支撑资源。要验证已经存在的同会话 base 可被复用，可仅执行第一条命令并改为 `ROLE=raster_bake`；此时不重新读取 PBF，也不触发 `fetch`。

如果下载源同时提供 `.md5`，先按 `.md5` 文件中的实际文件名校验：

```bash
(cd "${WORKDIR}/mirror" && md5sum -c guangxi-260726.osm.pbf.md5)
```

各 region 的 Geofabrik 下载 URL 定义在 `config/regions.yaml` 的 `geofabrik.pbf_url` 字段。手动下载只替代 `make fetch`，后续 `make build`、`make verify`、`make pack` 和 `make release` 的用法不变。

## 清理当前 session

清理当前 session 的 staging、pack cache 和 outputs：

```bash
make clean
```

该目标不会删除 Geofabrik mirror、tags-filter/config cache，也不会清理 setup 编译缓存。
