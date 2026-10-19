# 栅格＋矢量地图与路网构建

[返回手册目录](./index.md)

此处“栅格地图”是由 OSM 矢量与样式预渲染得到的 WebP 图片 PMTiles，不是卫星影像或 DEM。标准交付同时包含 `base` 矢量地图、`raster_bake` 图片地图、样式支撑资源和同源导航路网。图片范围 BAKE_BBOX 只控制渲染窗口，不裁剪原始 PBF，也不缩小路网输入范围。

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

## 工具与输入预检

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

图片构建还需要可用的 Native 渲染器：

```bash
make check-native-renderer
```

未安装或自检失败时，先按 [Native 安装操作](../operations/native-renderer-build.md) 准备引擎，再继续。`python-doctor` 检查 Python 依赖；Native 自检检查渲染能力；两者均不替代最终数据质量与视觉验收。

## 构建完整图片地图包

```bash
export ROLE=base_raster
# 以下窗口仅适用于覆盖南宁附近的输入，其他区域须替换
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

`base_raster` 依次构建 base、支撑资源、WebP 栅格 PMTiles 和同源路网。需要区域启用的独立建筑矢量资产时，将 ROLE 改为 `both_raster`。资源生成自动启用。任何路网步骤失败都不能得到新的完整标准包，`ROUTING=0` 也不能省略路网。

一键执行相同流程时，保持实际目录不变：

```bash
make release RELEASE_WORKDIR="${WORKDIR}" ROLE=base_raster FORMAT=both
```

不固定 RELEASE_WORKDIR 时，release 使用 `${WORKDIR_ROOT}/${SESSION}`，RouteWeft 必须安装在该实际目录或通过受信二进制环境变量提供。后续单独 build/verify/pack 也必须使用实际 WORKDIR。不要并行运行 `make -j release`。

输出位于 `${WORKDIR}/outputs/`：

```text
<session>.base.pmtiles
<session>.raster_bake.pmtiles
<session>.raster_bake.ready.json
<session>.style.json
<session>.style-raster.json
<session>.glyphs/
<session>.sprite/
<session>.routing/<dataset-id>/
<session>.routing.ready.json
<session>.bundle.tar.gz
<session>.bundle.zip
```

PMTiles 各有 manifest、attribution 和摘要侧文件。归档内 `routing/` 是必需资产；`package.json` 记录同源指纹、路网 profile/format 和逐文件哈希，`install.json` 继续描述地图。完整安装兼容要求见 [包内容与接入](./map-and-routing.md#包内容与接入)。不能将只处理地图的 `.import.zip` 当作已经验收的地图＋路网联合安装包。

## 复用 base，调整图片范围

先完成上面的完整构建，保留同一 WORKDIR、REGION、YYYYMMDD 和会话冻结的 PBF：

```bash
# 基于已有 base 估算本次窗口的瓦片数
make raster-estimate
# 修改 BAKE_BBOX 或缩放级别后，仅重跑图片阶段及默认路网构建
make build ROLE=raster_bake
make verify ROLE=raster_bake
make smoke-routing
make pack ROLE=raster_bake FORMAT=both
```

`ROLE=raster_bake` 不重建 base，不重新 fetch 或读取外部 INPUT；但 Make 仍会从 `staging/<session>/source.osm.pbf` 构建路网。因此不能删除冻结 PBF，也不能只拷贝 base PMTiles 后就运行此流程。pack 自动携带 base、栅格及同源路网。

## 渲染、缓存与底层诊断

Python vector build 会在 stderr 实时输出各阶段的 `START`、`DONE` 或 `FAIL`，并带有 `stage=<当前>/<总数>`。stdout 在构建结束前保持为空是正常的，因为它只用于最终结构化 job JSON。

交付 `ROLE=raster_bake` 时，`make pack` 和 `make prepare-import` 会自动将已验证的 `base` 一并纳入同一安装 bundle；图片底图不作为孤立的离线地图交付。标准 bundle 还必须包含路网；旧的地图 import 描述不能据此视为已经支持路网联合安装。安装描述会逐条解析 `styles-url`，校验对应样式、SHA-512 sidecar、glyph 和 sprite 引用都在归档内闭合。

图片构建会在 `${WORKDIR}/cache/bake/${SESSION}/parameters.json` 写入 base 身份、渲染器身份、配置覆盖和最终生效参数。瓦片按精确 Web Mercator geographic bounds 渲染，而不是假定相机 zoom 与 XYZ zoom 等价。每个新瓦片先写入临时文件，经 WebP 容器、尺寸和 `dwebp` 解码校验后原子发布，并写入匹配内容摘要的 `.webp.sha512` 验证标记；缓存复用要求容器、尺寸和该标记均有效。异常缓存会隔离到同一缓存目录的 `quarantine/`。同一 workspace 的任务互斥执行，单片渲染和编码默认 120 秒超时。当前 Python 正式入口尚未执行旧 Shell 的 2x2 macro-tile 逐像素视觉网格比较，因此不能把 `metrics.json.quality.visual_grid_validation=not-run` 解释为通过。

像素缓存身份只包含会改变单张图片的输入：base 摘要、烘焙样式摘要、瓦片尺寸与像素比、WebP 编码参数、渲染器身份，以及实际供数来源（含启用子集提取时的范围与缩放）。总预算、并发数、批次大小、覆盖范围和整份配置文件摘要不进入像素身份，它们记录在 `parameters.json` 的 `run_identity`、`plan` 与 `inputs` 中。因此调整这些运行参数可以复用已通过校验的图片；样式、base、编码或供数来源变化仍会失效。

在启动长任务前，先基于已验证的 `base` 估算矩形覆盖的瓦片数量。`max_tiles`（默认 20 万）是软基线：计划超过基线时，按计划张数的 `max_tiles_headroom_ratio`（默认 0.1）自动计算生效预算，不需要逐省配置或每次传参；估算输出的 `budget_source`、`configured_max_tiles` 与 `max_tiles` 分别表示预算来源、基线和生效额度。显式 `BAKE_MAX_TILES` 是硬上限，不会被自动放宽；将 `max_tiles_headroom_ratio` 置 `null` 可恢复严格基线。`raster-estimate` 只根据 base 头信息（或显式 `BAKE_BBOX`）与配置输出计划，不写缓存文件；完整计划由 `ROLE=raster_bake` 在渲染前写入 `${WORKDIR}/cache/bake/${SESSION}/plan.json`，按缩放级别列出瓦片数量和坐标范围。

```bash
make raster-estimate BAKE_MAX_TILES=200000
```

上面的 `BAKE_MAX_TILES` 在此例中是显式硬上限；真实构建需要硬性限制时才传。只做估算或常规长任务时留空即可，超过 20 万的部分会按 `max_tiles_headroom_ratio` 自动放开，并在估算 JSON 中标记 `budget_source: auto-headroom`。

`make build ROLE=raster_bake` 不需要先执行估算：它在写缓存前自动生成完整计划并计算生效预算，同时在 stderr 打印 `raster plan: tiles=... max_tiles=... configured_max_tiles=... budget_source=... batch_tiles=...` 摘要，便于在长时间渲染开始前确认本次额度。

正常构建完成后，同一缓存目录的 `metrics.json` 会记录计划、初始缓存命中、结构损坏隔离、未验证缓存复验、渲染批次与重试次数、MVT 预检、worker 队列、渲染/组装/转换耗时以及中间文件大小，用于比较相同样本下的配置调整。finalization 会从 PMTiles 抽取首、中、末 zoom 的中心样本并再次解码，同时核对 addressed tile count、tile 计划、输入指纹和清单中的覆盖摘要。`metrics.json` 的 `phases_ms.assembly` 是装配、转换和回读的聚合说明，细分耗时在 `assembly_phases_ms`。

图片渲染默认按 `batch_tiles: 10000` 串行分批，无需手动计算；批内沿用 `BAKE_JOBS` 受限并发。批次只限制一次调度的工作量，不减少计划总数，也不会绕过生效预算（显式硬上限仍会拦截）。需要调整检查点粒度时用正整数 `BAKE_BATCH_TILES`（或 `--batch-tiles`）覆盖，置 `config/bake.yaml` 的 `batch_tiles: null` 可恢复单批。`raster-estimate` 的输出除了 `within_limit`，还会给出 `batch_tiles` 与按完整计划计算的 `estimated_batches`（首次无缓存时的批次数上限；续跑按实际缺失队列重新分批）。每批结束后原子写入 `${WORKDIR}/cache/bake/${SESSION}/progress.json`（含 `status`、`queued_tiles`、`batches_completed`/`batches_total`、`rendered_tiles`、`failed_tiles` 与失败样本），全部批次完成后才装配候选归档并全量回读。中断后重跑不会跳过校验，仍按 WebP 与侧车摘要扫描只补缺失或损坏项；遗留 `.bake.lock` 需要先确认原进程已退出，不能直接删除活动锁。

`raster_bake` 会先在 `outputs/.staging/` 完成转换、metadata、manifest 和验证，再发布正式文件与 `${SESSION}.raster_bake.ready.json`。`pack` 和 `prepare-import` 只接受与 PMTiles、manifest、attribution 摘要一致的 ready marker，避免把中断构建的半成品纳入交付。

直接诊断 Python raster pipeline 时可执行：

```bash
devbox run -- env PYTHONPATH=backend/src .venv/bin/python -m huavd_map_build build raster-bake \
  --region "${REGION}" --yyyymmdd "${YYYYMMDD}" \
  --workdir "${WORKDIR}" --no-publish
```

`--no-publish` 只在 `cache/bake/${SESSION}/` 保留候选 PMTiles，不写正式 outputs 或 ready marker。默认不传该参数时会执行 metadata、manifest、attribution、PMTiles/WebP 抽样、消费者资源闭合和 ready-last 发布。

默认引擎由 `config/bake.yaml` 选择，当前为 `maplibre-native-headless`。
它自动使用 devbox Vulkan 软件渲染，不需要 DISPLAY 或 Xvfb；doctor 会执行真实渲染自检。
自检通过仍不等于地图视觉与客户端验收通过。旧 npm `mbgl-renderer` 需要图形显示环境，
仅在显式覆盖引擎时使用，不再作为默认安装和检查项目。

兼容旧 `maplibre-native` 命令协议（不是默认 Native XYZ 协议）时：

```bash
devbox run -- env PYTHONPATH=backend/src .venv/bin/python -m huavd_map_build build raster-bake \
  --region "${REGION}" --yyyymmdd "${YYYYMMDD}" \
  --workdir "${WORKDIR}" \
  --renderer-engine maplibre-native --renderer-command /path/to/mbgl-render
```


上面的底层 Python `build raster-bake` 命令仅用于诊断图片分支，不构建路网，也不生成完整 bundle。正式交付使用本页 Make 流程；对已有地图单独运行路网分支时，INPUT 必须指向与地图 manifest SHA-256 一致的会话冻结 PBF。
