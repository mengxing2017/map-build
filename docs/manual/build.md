# 标准矢量地图与路网构建

[返回手册目录](./index.md)

`make build ROLE=base|both` 默认生成矢量地图和同源导航路网，`make pack` 将两者放入同一 bundle。缺少路网、校验失败或源 PBF SHA-256 不一致时停止出包。栅格＋矢量流程见 [图片地图构建](./raster.md)，两种地图的统一流程与包协议见 [地图与路网构建](./map-and-routing.md)。

## 声明输入与区域

所有命令在仓库根目录、devbox 环境内执行。下面的区域和 PBF 路径是占位值，执行前必须替换；区域须已登记在 `config/regions.yaml`。地图和路网直接共用 REGION，无需额外路网配置或区域白名单。

```bash
cd /path/to/huavd-map-build
devbox shell

export REGION=your/configured/local-region
export YYYYMMDD=20260803
export WORKDIR=/data/huavd-map-build/local-region-20260803
export INPUT=/absolute/path/to/verified/source.osm.pbf
unset SESSION
```

`SESSION` 自动取 `{region-slug}-{YYYYMMDD}`。`INPUT` 使用绝对路径，`YYYYMMDD` 是产物日期，不从文件名推导。下文分步命令始终使用同一个 `WORKDIR`，产物位于 `${WORKDIR}/outputs/`。

路网使用内置驾车参数、容量和超时预算，默认严格拒绝无效转向限制。构建后从实际路网中自动选取道路，检查 nearest 和正向 route；不要求用户填写查询坐标或人工 NoRoute 案例。自动检查只验证基本查询能力，不能替代覆盖范围和导航效果验收。

用户提供的 `/home/dev/data/source-map/guangxi-260803.osm.pbf` 是省域输入。只有配置的 REGION 确实代表广西，且该省域输入通过 RouteWeft 容量、限制关系和查询审核时，才可将其作为 INPUT。城市构建应先使用经核验的城市提取文件，不能把城市切片标成广西全域。

## 工具与输入预检

```bash
# 首次准备地图工具、Python 依赖和字体等资源
make setup
make python-doctor python-catalog-validate

# 首次安装锁定的路网工具；此步骤可能下载源码和 Rust 依赖
make setup-routeweft
# 不传 INPUT，使用内置微型数据检查工具合约
make doctor-routeweft INPUT=

# 对真实输入先做路网预检，避免地图长任务完成后才发现源不支持
make preflight-routing
```

已有干净的锁定 RouteWeft 源码时，可用 `make setup-routeweft ROUTEWEFT_SOURCE=/absolute/path/to/routeweft`。已有受信二进制可设置 `ROUTEWEFT_BIN` 和 `ROUTEWEFT_SHA256`，详见 [工具准备](../operations/routing.md#工具准备)。普通 build 不会自动下载安装工具。preflight 会实际建图，开销接近路网构建；通过预检仍不替代构建后的查询质量门。

## 构建、验证和打包

```bash
export ROLE=both
# 同时准备地图样式依赖的 glyph；pack 也会补齐缺少的样式支撑资源
make build GLYPH=1
make verify
make verify-routing
make smoke-routing
make pack FORMAT=both
```

`ROLE=base` 只生成基础矢量地图及路网；`ROLE=both` 还会在区域启用建筑资产时生成独立 building PMTiles，未启用时跳过可选 building。两者都强制包含路网，`ROUTING=0` 不能关闭。构建按地图阶段、路网阶段顺序执行；路网读取会话冻结的原始 PBF，不从道路显示图层或 PMTiles 反推。

`make verify` 检查地图；`verify-routing` 检查路网 ready、审计和文件哈希，`smoke-routing` 执行查询质量门。`pack` 再次校验包内路网副本及查询，并要求地图 manifest 的 `source.sha256` 与路网一致。不能只凭 `make verify` 判断路网可用。

输出包括：

```text
outputs/<session>.base.pmtiles
outputs/<session>.base.manifest.json
outputs/<session>.base.attribution.json
outputs/<session>.building.pmtiles          # 区域启用时
outputs/<session>.routing/<dataset-id>/
outputs/<session>.routing.ready.json
outputs/<session>.bundle.tar.gz
outputs/<session>.bundle.zip
```

bundle 内包含地图、样式/glyph/sprite、`routing/` 数据集与署名、`install.json`、`package.json` 以及 SHA-256/SHA-512 清单。客户端需要支持包级必需路网能力，详见 [包内容与接入](./map-and-routing.md#包内容与接入)。独立 `pack-routing` 审核包不能替代这里的地图 bundle。

## 一键发布与工作目录

在上述上下文和工具准备完成后，可用下列命令替代分步构建：

```bash
# 固定实际目录，确保使用前面已安装的工具和输入上下文
make release RELEASE_WORKDIR="${WORKDIR}" ROLE=both GLYPH=1 FORMAT=both
```

release 执行 build、pack、verify，build 和 pack 已包含路网门禁。它不下载 PBF。未显式设置 `RELEASE_WORKDIR` 时，release 实际使用 `${WORKDIR_ROOT}/${SESSION}`（WORKDIR_ROOT 默认取原 WORKDIR）；工具必须装在该实际目录，后续分步命令也必须指向它。不要用 `make -j release` 并发执行依赖构建产物的发布步骤。

## 下载输入与离线输入

已有本地 PBF 时直接使用上面的 INPUT，不必 fetch。需要从区域目录下载时：

```bash
unset INPUT
make fetch
# build 将读取 WORKDIR/mirror 下区域配置的 geofabrik.basename
make build ROLE=both GLYPH=1
make verify
make smoke-routing
make pack ROLE=both FORMAT=both
```

`fetch` 依据 `config/regions.yaml` 下载 PBF 与 MD5，区域必须具有可用下载端点。若自行下载了校验侧文件，应先按其实际文件名运行 `md5sum -c`；带日期的文件推荐保留原名，用绝对 INPUT 指定。使用 release 且未固定实际目录时，不要假定父目录 mirror 就是 release 的 mirror。

## z19 标准矢量配置

base 专属覆盖支持真实 z0–19。公共区域目录未默认启用；局部区域应先在 Tippecanoe 区域覆盖配置 `roles: [base]`、`max_zoom: 19`、`layer_zoom_profile: standard-z19` 和 `extend_zooms_if_still_dropping: false`，并准备与区域边界一致的输入。

```bash
make python-catalog-validate
make python-catalog-shadow
make build ROLE=base GLYPH=1
make verify ROLE=base
make smoke-routing
make pack ROLE=base FORMAT=both
```

配置按 defaults、高密度基线、角色设置、区域与角色覆盖、显式 tier profile 顺序解析。admin/行政线及高等级地名保留各自层级规则。z19 深度校验会从 staged 道路、建筑和水体抽样解码最高层 MVT；仅修改 header 不能通过。包内存在 z19 数据仍需客户端样式、source.maxzoom 与设备性能验收。

## 清理

`make clean` 清理当前地图 session 的已知 staging、缓存及地图产物；不会完整清理路网版本、路网 attempt、mirror 或工具安装缓存。更换区域或输入后，应重新构建并通过同源校验，不应手工修改 ready。
