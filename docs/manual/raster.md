# 图片地图构建

[返回手册目录](./index.md)

Native 安装与图片 ZIP 快速流程见 [图片地图操作](../operations/native-renderer-build.md)。准备本地 PBF 见 [标准地图构建](./build.md#手动下载地图数据)。

```bash
make release REGION=china/guangxi YYYYMMDD=20260818 \
  INPUT=/data/osm/guangxi-260726.osm.pbf ROLE=base_raster FORMAT=zip
```

该命令先通过 Python vector pipeline 构建并验证 `base` 矢量 PMTiles，再以它为输入生成 `raster_bake` WebP PMTiles；包内同时包含图片底图样式、矢量标注和 glyph/sprite 资源。`base_raster` 会自动启用资源生成。只重跑图片阶段时可保留已验证的 base 和支撑资源，使用 `ROLE=raster_bake`，无需重新提供 PBF。

Python vector build 会在 stderr 实时输出各阶段的 `START`、`DONE` 或 `FAIL`，并带有 `stage=<当前>/<总数>`。stdout 在构建结束前保持为空是正常的，因为它只用于最终结构化 job JSON。

交付 `ROLE=raster_bake` 时，`make pack` 和 `make prepare-import` 会自动将已验证的 `base` 一并纳入同一安装 bundle；图片底图不作为孤立的离线地图交付。安装描述会逐条解析 `styles-url`，校验对应样式、SHA-512 sidecar、glyph 和 sprite 引用都在归档内闭合。

图片构建会在 `${WORKDIR}/cache/bake/${SESSION}/parameters.json` 写入 base 身份、渲染器身份、配置覆盖和最终生效参数。瓦片按精确 Web Mercator geographic bounds 渲染，而不是假定相机 zoom 与 XYZ zoom 等价。每个新瓦片先写入临时文件，经 WebP 容器、尺寸和 `dwebp` 解码校验后原子发布，并写入匹配内容摘要的 `.webp.sha512` 验证标记；缓存复用要求容器、尺寸和该标记均有效。异常缓存会隔离到同一缓存目录的 `quarantine/`。同一 workspace 的任务互斥执行，单片渲染和编码默认 120 秒超时。当前 Python 正式入口尚未执行旧 Shell 的 2x2 macro-tile 逐像素视觉网格比较，因此不能把 `metrics.json.quality.visual_grid_validation=not-run` 解释为通过。

在启动长任务前，先基于已验证的 `base` 估算矩形覆盖的瓦片数量。`BAKE_MAX_TILES` 是可选预算；当计划超过它时，命令会在启动渲染器前以输入错误退出。计划写入 `${WORKDIR}/cache/bake/${SESSION}/plan.json`，按缩放级别列出瓦片数量和坐标范围。

```bash
make raster-estimate REGION=china/guangxi YYYYMMDD=20260818 BAKE_MAX_TILES=200000
```

正常构建完成后，同一缓存目录的 `metrics.json` 会记录计划、初始缓存命中、结构损坏隔离、未验证缓存复验、渲染批次与重试次数、MVT 预检、worker 队列、渲染/组装/转换耗时以及中间文件大小，用于比较相同样本下的配置调整。finalization 会从 PMTiles 抽取首、中、末 zoom 的中心样本并再次解码，同时核对 addressed tile count、tile 计划、输入指纹和清单中的覆盖摘要。

`raster_bake` 会先在 `outputs/.staging/` 完成转换、metadata、manifest 和验证，再发布正式文件与 `${SESSION}.raster_bake.ready.json`。`pack` 和 `prepare-import` 只接受与 PMTiles、manifest、attribution 摘要一致的 ready marker，避免把中断构建的半成品纳入交付。

直接诊断 Python raster pipeline 时可执行：

```bash
PYTHONPATH=backend/src python -m huavd_map_build build raster-bake \
  --region china/guangxi --yyyymmdd 20260818 \
  --workdir /tmp/huavd-map-build --no-publish
```

`--no-publish` 只在 `cache/bake/${SESSION}/` 保留候选 PMTiles，不写正式 outputs 或 ready marker。默认不传该参数时会执行 metadata、manifest、attribution、PMTiles/WebP 抽样、消费者资源闭合和 ready-last 发布。

默认引擎由 `config/bake.yaml` 选择，当前为 `maplibre-native-headless`。
它自动使用 devbox Vulkan 软件渲染，不需要 DISPLAY 或 Xvfb；doctor 会执行真实渲染自检。
自检通过仍不等于地图视觉与客户端验收通过。旧 npm `mbgl-renderer` 需要图形显示环境，
仅在显式覆盖引擎时使用，不再作为默认安装和检查项目。

兼容旧 `maplibre-native` 命令协议（不是默认 Native XYZ 协议）时：

```bash
PYTHONPATH=backend/src python -m huavd_map_build build raster-bake \
  --region china/guangxi --yyyymmdd 20260818 \
  --workdir /tmp/huavd-map-build \
  --renderer-engine maplibre-native --renderer-command /path/to/mbgl-render
```
