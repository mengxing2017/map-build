# 图片地图构建

[返回手册目录](./index.md)

Native 安装与图片 ZIP 快速流程见 [图片地图操作](../operations/native-renderer-build.md)。准备本地 PBF 见 [标准地图构建](./build.md#手动下载地图数据)。

```bash
devbox run -- make python-doctor python-catalog-validate
devbox run -- make release REGION=china/guangxi YYYYMMDD=20260818 \
  WORKDIR_ROOT=/data/huavd-map-build \
  INPUT=/home/dev/Downloads/guangxi-261003.osm.pbf ROLE=base_raster FORMAT=zip
```

在仓库根目录执行上述命令，也可先进入 `devbox shell` 后直接运行 `make`。
`WORKDIR_ROOT` 是 release 工作目录的父目录；该例的实际工作目录为
`/data/huavd-map-build/china-guangxi-20260818`，最终 ZIP 为
`/data/huavd-map-build/china-guangxi-20260818/outputs/china-guangxi-20260818.bundle.zip`。
省略目录参数时默认父目录为 `/tmp/huavd-map-build`；需要长期保留产物时应显式指定。
若希望直接指定完整工作目录，可使用 `RELEASE_WORKDIR=/data/my-map-run`，
产物位于其 `outputs/` 下。后续单独执行 `build`、`verify`、`pack` 或 `raster-estimate`
时，应传入实际工作目录 `WORKDIR=/data/huavd-map-build/china-guangxi-20260818`。
`YYYYMMDD` 是产物构建日期，不会根据 PBF 文件名自动推断；请按实际发布日期设置。

`python-catalog-validate` 检查配置，`python-doctor` 检查工具和 Python 依赖；
它们不能替代构建后的 `deep-verify` 数据质量检查。`make build` 会先执行
`python-doctor`，在过滤或生成瓦片前发现依赖加载失败。
例如普通 shell 中缺少 `libstdc++.so.6` 会导致 Shapely 及 `mapbox_vector_tile`
无法加载，应切换到 devbox 环境，不应跳过深度检查。

该命令先通过 Python vector pipeline 构建并验证 `base` 矢量 PMTiles，再以它为输入生成 `raster_bake` WebP PMTiles；包内同时包含图片底图样式、矢量标注和 glyph/sprite 资源。`base_raster` 会自动启用资源生成。只重跑图片阶段时可保留已验证的 base 和支撑资源，使用 `ROLE=raster_bake`，无需重新提供 PBF。

Python vector build 会在 stderr 实时输出各阶段的 `START`、`DONE` 或 `FAIL`，并带有 `stage=<当前>/<总数>`。stdout 在构建结束前保持为空是正常的，因为它只用于最终结构化 job JSON。

交付 `ROLE=raster_bake` 时，`make pack` 和 `make prepare-import` 会自动将已验证的 `base` 一并纳入同一安装 bundle；图片底图不作为孤立的离线地图交付。安装描述会逐条解析 `styles-url`，校验对应样式、SHA-512 sidecar、glyph 和 sprite 引用都在归档内闭合。

图片构建会在 `${WORKDIR}/cache/bake/${SESSION}/parameters.json` 写入 base 身份、渲染器身份、配置覆盖和最终生效参数。瓦片按精确 Web Mercator geographic bounds 渲染，而不是假定相机 zoom 与 XYZ zoom 等价。每个新瓦片先写入临时文件，经 WebP 容器、尺寸和 `dwebp` 解码校验后原子发布，并写入匹配内容摘要的 `.webp.sha512` 验证标记；缓存复用要求容器、尺寸和该标记均有效。异常缓存会隔离到同一缓存目录的 `quarantine/`。同一 workspace 的任务互斥执行，单片渲染和编码默认 120 秒超时。当前 Python 正式入口尚未执行旧 Shell 的 2x2 macro-tile 逐像素视觉网格比较，因此不能把 `metrics.json.quality.visual_grid_validation=not-run` 解释为通过。

像素缓存身份只包含会改变单张图片的输入：base 摘要、烘焙样式摘要、瓦片尺寸与像素比、WebP 编码参数、渲染器身份，以及实际供数来源（含启用子集提取时的范围与缩放）。总预算、并发数、批次大小、覆盖范围和整份配置文件摘要不进入像素身份，它们记录在 `parameters.json` 的 `run_identity`、`plan` 与 `inputs` 中。因此调整这些运行参数可以复用已通过校验的图片；样式、base、编码或供数来源变化仍会失效。

在启动长任务前，先基于已验证的 `base` 估算矩形覆盖的瓦片数量。`max_tiles`（默认 20 万）是软基线：计划超过基线时，按计划张数的 `max_tiles_headroom_ratio`（默认 0.1）自动计算生效预算，不需要逐省配置或每次传参；估算输出的 `budget_source`、`configured_max_tiles` 与 `max_tiles` 分别表示预算来源、基线和生效额度。显式 `BAKE_MAX_TILES` 是硬上限，不会被自动放宽；将 `max_tiles_headroom_ratio` 置 `null` 可恢复严格基线。`raster-estimate` 只根据 base 头信息（或显式 `BAKE_BBOX`）与配置输出计划，不写缓存文件；完整计划由 `ROLE=raster_bake` 在渲染前写入 `${WORKDIR}/cache/bake/${SESSION}/plan.json`，按缩放级别列出瓦片数量和坐标范围。

```bash
devbox run -- make raster-estimate REGION=china/guangxi YYYYMMDD=20260818 \
  WORKDIR=/data/huavd-map-build/china-guangxi-20260818 BAKE_MAX_TILES=200000
```

上面的 `BAKE_MAX_TILES` 在此例中是显式硬上限；真实构建需要硬性限制时才传。只做估算或常规长任务时留空即可，超过 20 万的部分会按 `max_tiles_headroom_ratio` 自动放开，并在估算 JSON 中标记 `budget_source: auto-headroom`。

`make build ROLE=raster_bake` 不需要先执行估算：它在写缓存前自动生成完整计划并计算生效预算，同时在 stderr 打印 `raster plan: tiles=... max_tiles=... configured_max_tiles=... budget_source=... batch_tiles=...` 摘要，便于在长时间渲染开始前确认本次额度。

正常构建完成后，同一缓存目录的 `metrics.json` 会记录计划、初始缓存命中、结构损坏隔离、未验证缓存复验、渲染批次与重试次数、MVT 预检、worker 队列、渲染/组装/转换耗时以及中间文件大小，用于比较相同样本下的配置调整。finalization 会从 PMTiles 抽取首、中、末 zoom 的中心样本并再次解码，同时核对 addressed tile count、tile 计划、输入指纹和清单中的覆盖摘要。`metrics.json` 的 `phases_ms.assembly` 是装配、转换和回读的聚合说明，细分耗时在 `assembly_phases_ms`。

图片渲染默认按 `batch_tiles: 10000` 串行分批，无需手动计算；批内沿用 `BAKE_JOBS` 受限并发。批次只限制一次调度的工作量，不减少计划总数，也不会绕过生效预算（显式硬上限仍会拦截）。需要调整检查点粒度时用正整数 `BAKE_BATCH_TILES`（或 `--batch-tiles`）覆盖，置 `config/bake.yaml` 的 `batch_tiles: null` 可恢复单批。`raster-estimate` 的输出除了 `within_limit`，还会给出 `batch_tiles` 与按完整计划计算的 `estimated_batches`（首次无缓存时的批次数上限；续跑按实际缺失队列重新分批）。每批结束后原子写入 `${WORKDIR}/cache/bake/${SESSION}/progress.json`（含 `status`、`queued_tiles`、`batches_completed`/`batches_total`、`rendered_tiles`、`failed_tiles` 与失败样本），全部批次完成后才装配候选归档并全量回读。中断后重跑不会跳过校验，仍按 WebP 与侧车摘要扫描只补缺失或损坏项；遗留 `.bake.lock` 需要先确认原进程已退出，不能直接删除活动锁。

`raster_bake` 会先在 `outputs/.staging/` 完成转换、metadata、manifest 和验证，再发布正式文件与 `${SESSION}.raster_bake.ready.json`。`pack` 和 `prepare-import` 只接受与 PMTiles、manifest、attribution 摘要一致的 ready marker，避免把中断构建的半成品纳入交付。

直接诊断 Python raster pipeline 时可执行：

```bash
devbox run -- env PYTHONPATH=backend/src .venv/bin/python -m huavd_map_build build raster-bake \
  --region china/guangxi --yyyymmdd 20260818 \
  --workdir /data/huavd-map-build/china-guangxi-20260818 --no-publish
```

`--no-publish` 只在 `cache/bake/${SESSION}/` 保留候选 PMTiles，不写正式 outputs 或 ready marker。默认不传该参数时会执行 metadata、manifest、attribution、PMTiles/WebP 抽样、消费者资源闭合和 ready-last 发布。

默认引擎由 `config/bake.yaml` 选择，当前为 `maplibre-native-headless`。
它自动使用 devbox Vulkan 软件渲染，不需要 DISPLAY 或 Xvfb；doctor 会执行真实渲染自检。
自检通过仍不等于地图视觉与客户端验收通过。旧 npm `mbgl-renderer` 需要图形显示环境，
仅在显式覆盖引擎时使用，不再作为默认安装和检查项目。

兼容旧 `maplibre-native` 命令协议（不是默认 Native XYZ 协议）时：

```bash
devbox run -- env PYTHONPATH=backend/src .venv/bin/python -m huavd_map_build build raster-bake \
  --region china/guangxi --yyyymmdd 20260818 \
  --workdir /data/huavd-map-build/china-guangxi-20260818 \
  --renderer-engine maplibre-native --renderer-command /path/to/mbgl-render
```
