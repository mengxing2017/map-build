# 地图与路网完整构建

本页给出标准矢量包和栅格＋矢量包的完整操作。两种包都默认带路网：地图供显示，路网供路径计算，二者读取同一原始 OSM PBF；路网不读取 PMTiles。细节分别见 [标准矢量构建](./build.md) 和 [栅格地图构建](./raster.md)。

## 选择交付类型

| ROLE | 地图资产 | 路网 | 条件 |
| :--- | :--- | :--- | :--- |
| `base` | 基础矢量 PMTiles | 必需 | 复用地图 REGION 和原始 PBF |
| `both` | 基础矢量＋可选独立建筑矢量 | 必需 | building 仅在区域启用时生成 |
| `base_raster` | 基础矢量＋WebP 栅格图片 | 必需 | Native 渲染器可用 |
| `both_raster` | 基础矢量＋可选建筑＋WebP 栅格 | 必需 | Native 渲染器可用 |
| `raster_bake` | 复用已有 base，重建栅格图片 | 必需 | 同会话 base、资源和冻结 PBF 均保留 |

这里的图片地图由矢量样式预渲染，不是卫星影像或 DEM。building 单资产、DEM、overview 和 derived-map 独立流程不在本页标准区域包范围内。

## 共同准备

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

路网使用内置驾车参数、容量和超时预算，数据质量策略来自 `config/regions.yaml` 的 routing 默认配置和区域覆盖。构建后从实际路网中自动选取道路，检查 nearest 和正向 route；不要求用户填写查询坐标或人工 NoRoute 案例。自动检查只验证基本查询能力，不能替代覆盖范围和导航效果验收。

```bash
# 首次准备地图工具、Python 依赖、字体、RouteWeft 及其锁定 Rust 工具链
make setup
make python-doctor python-catalog-validate

# setup 已安装路网工具；需要单独重装时才使用 make setup-routeweft
# 不传 INPUT，使用内置微型数据检查工具合约
make doctor-routeweft INPUT=

# 对真实输入先做路网预检，避免地图长任务完成后才发现源不支持
make preflight-routing
```

统一 setup 会自动安装路网工具及锁定 Rust 工具链，可能下载源码和依赖；需在 devbox 环境执行。已有干净的锁定 RouteWeft 源码时，可用 `make setup-routeweft ROUTEWEFT_SOURCE=/absolute/path/to/routeweft`。已有受信二进制可设置 `ROUTEWEFT_BIN` 和 `ROUTEWEFT_SHA256`，详见 [工具准备](../operations/routing.md#工具准备)。普通 build 不会自动下载安装工具。preflight 会实际建图，开销接近路网构建；通过预检仍不替代构建后的查询质量门。

本项目默认配置对非法限速采用 `use_default` 估算成本，对异常转向采用 `block_ways` 保守排除关联道路；不需要固定源哈希或人工道路清单。完整诊断、计数和排除证据必须通过校验，否则拒绝发布。排除会减少覆盖和可达性，实际清单写入构建回执及包清单。需要严格质量门的区域可将相应策略设为 `reject`，详见[数据质量业务策略](../operations/routing.md#数据质量业务策略)。区域容量仍受工具预算限制，小于 512 MiB 不代表一定能构建整个省。

## 标准矢量地图＋路网

```bash
export ROLE=both
make build GLYPH=1
make verify
make verify-routing
make smoke-routing
make pack FORMAT=both
```

不需要独立建筑资产时设置 ROLE=base。build 先完成矢量过滤、导出、标准化、瓦片、metadata、manifest 与地图质量验证，再读取冻结 PBF 构建路网并通过查询质量门。pack 会补齐缺少的样式支撑资源，并把地图和路网共同归档。

只在配置明确启用时使用 z19，配置和深度验证要求见 [z19 标准矢量配置](./build.md#z19-标准矢量配置)。不应把渲染器相机 zoom 或 header 改动当作存在真实高层级矢量数据。

## 栅格＋矢量地图＋路网

```bash
make check-native-renderer
export ROLE=base_raster
# 仅供覆盖南宁附近的输入参考，其他区域须换成自己的窗口
export BAKE_BBOX=108.2,22.7,108.4,22.9
export BAKE_MIN_ZOOM=12
export BAKE_MAX_ZOOM=14
export BAKE_MAX_TILES=200000

make build
make verify
make verify-routing
make smoke-routing
make pack FORMAT=both
```

需要独立建筑资产时设 ROLE=both_raster。此流程自动生成 base、样式、glyph/sprite，再渲染 WebP PMTiles，最后构建路网。BAKE_BBOX 与 zoom 参数只控制图片瓦片，不裁剪路网，也不减小 PBF 路由容量要求。Native 安装、瓦片预算、缓存及视觉验收见 [栅格地图构建](./raster.md)。

已有同会话 base 时可先估算并仅重跑图片：

```bash
make raster-estimate
make build ROLE=raster_bake
make verify ROLE=raster_bake
make smoke-routing
make pack ROLE=raster_bake FORMAT=both
```

此模式不重新生成 base，但仍用会话冻结 PBF 构建路网，不能删除 staging 源文件。

## 一键发布与目录

准备完成后，一键发布可替代相应分步命令：

```bash
# 二选一；显式指定地图产物工作目录
make release RELEASE_WORKDIR="${WORKDIR}" ROLE=both GLYPH=1 FORMAT=both
make release RELEASE_WORKDIR="${WORKDIR}" ROLE=base_raster FORMAT=both
```

release 不执行 fetch。未设置 RELEASE_WORKDIR 时，它将目录切换到 `${WORKDIR_ROOT}/${SESSION}`；RouteWeft 会复用项目工具目录 `tools/routeweft/`，也可用 ROUTEWEFT_TOOLS 指定工具根目录。后续分步命令也必须使用实际 WORKDIR。不要用 `make -j release` 并发执行这些依赖产物的步骤。

本地 INPUT 无需下载。若配置有可用 Geofabrik 下载端点，可先 unset INPUT、执行 `make fetch`，再在同一个 WORKDIR 执行所选流程。下载名由 geofabrik.basename 决定，产物日期不决定输入文件名。

## 输出与验证

工作目录 outputs 下有 `<session>.base.pmtiles`、可选 `.building.pmtiles`、图片模式下的 `.raster_bake.pmtiles`，以及各自 manifest、署名、摘要和样式资源。路网位于 `<session>.routing/<dataset-id>/`，由 `<session>.routing.ready.json` 标记有效版本。最终交付为 `<session>.bundle.tar.gz` 和 `.bundle.zip`，各有 SHA-512 侧文件。

`make verify` 只代表地图验证；路网还需 verify-routing/smoke-routing。pack 锁定当前路网 ready、核验文件哈希，再复制并对包内副本执行 verify 与查询质量门。所有地图 manifest 的 source.sha256 必须等于路网指纹；旧地图缺少该字段时需重建。缺失、源不一致或质量门失败均停止新包生成，ROUTING=0 不能绕过。

## 包内容与接入

归档中包括：

- 地图 PMTiles、manifest、署名、样式、glyph 和 sprite。
- `install.json`：原有 `huavd-map-install/v1` 地图安装描述。
- `routing/`：RouteWeft 数据集、构建/查询审计及 OSM 署名。
- `package.json`：`huavd-map-package/v1` 包级清单，声明 routing.required=true、格式/profile、同源 SHA-256、限制策略及逐文件哈希。
- `SHA256SUMS`、`SHA512SUMS`：覆盖地图、路网和清单。

消费者必须识别 package.json.required_capabilities 中的 routeweft-dataset-v2，并将必需路网与地图共同安装。只识别旧 install.json 的客户端不具备联合安装保证；旧地图 import 工作流也不能作为已验收的地图＋路网安装入口。生成完整 bundle 不代表外部客户端已升级。

`build-routing`、`pack-routing` 仍是独立路网审核接口，不生成地图；底层 Python execute-vector/raster-bake 也只处理各自地图分支。正式完整交付采用本页 Make build/pack 或 release 流程。
