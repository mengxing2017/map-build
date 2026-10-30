# RouteWeft 独立审核数据集

标准区域地图包默认带路网；构建、打包和包级协议见 [地图与路网构建](../manual/map-and-routing.md)。本页说明路网分支的独立审核入口，它们也可用于排查标准包的路网门禁。独立 `pack-routing` 仍生成审核包，不替代标准地图包。

## 工具准备

普通 routing 构建不联网，也不依赖地图渲染器。Python 需要 PyYAML。

```bash
make setup WORKDIR=/tmp/routing
make doctor WORKDIR=/tmp/routing
```

`./scripts/setup-tools.sh` / `make setup` 默认安装 RouteWeft；`./scripts/doctor.sh` / `make doctor` 默认执行路网工具身份及真实微型建图检查，不受 ROUTING=0 影响。工具默认安装到项目 `tools/routeweft/`，不读取地图 WORKDIR 下的工具。可通过 `HUAVD_TOOLS_DIR` 修改项目工具根目录，或通过 `ROUTEWEFT_TOOLS` 单独指定 RouteWeft 根目录。切换地图 WORKDIR 不需要重新安装。单独重装路网工具仍可执行 `make setup-routeweft`；离线本地源码可通过 ROUTEWEFT_SOURCE 指定。

源码必须是 `config/routeweft.lock.json` 锁定的干净提交。未提供 `ROUTEWEFT_SOURCE` 时，只有显式 setup 会从锁定仓库获取提交。setup 使用 Cargo.lock 和仓库工具链编译，回执记录提交、二进制及 Cargo.lock 哈希、平台、rustc 和时间。setup 自动检查锁定源码 rust-toolchain.toml 的版本，缺失时由 rustup 安装对应 minimal 工具链，并明确使用该版本运行 Cargo；rustup 由 devbox 提供。Rust 依赖须预先可用或允许 setup 下载。

已有二进制无需 Rust 环境：设置绝对 `ROUTEWEFT_BIN`，并提供 `ROUTEWEFT_SHA256` 或 `ROUTEWEFT_RECEIPT`。显式 SHA-256 是操作者信任入口，不声称能单凭哈希证明源码提交。每次调用重新核对二进制哈希。doctor 使用默认微型 PBF 实际运行 version/preflight/build/verify，检查 schema=1、format=1、profile=driving-v1、命令和限制策略能力。不要将真实构建的 INPUT 传给默认工具探针；显式提供 INPUT 时，doctor 会对该文件执行严格策略探针。

### 找不到工具回执

出现 `RouteWeft installation receipt not found`（旧版本为 `provide ROUTEWEFT_SHA256 or a build receipt`）时，表示项目工具目录没有锁定工具的安装回执，并非 PBF 或 REGION 配置错误。先安装工具并自检，再重试路网构建：

```bash
make setup-routeweft WORKDIR=/home/dev/data/map/guangxi
make doctor-routeweft WORKDIR=/home/dev/data/map/guangxi INPUT=
make build-routing WORKDIR=/home/dev/data/map/guangxi \
  REGION=china/guangxi YYYYMMDD=20261020 \
  INPUT=/home/dev/data/source-map/guangxi-260803.osm.pbf
```

setup 会生成工具及 receipt.json，正常使用不需要手填 SHA-256。已有干净锁定源码可增加 ROUTEWEFT_SOURCE。release 的隔离工作目录也会复用共享工具；自定义共享目录时保持 HUAVD_TOOLS_DIR 或 ROUTEWEFT_TOOLS 设置一致。地图 build 会先执行工具合约检查，再启动地图生成；工具检查不使用真实 INPUT。

## REGION 与执行

普通构建直接复用 config/regions.yaml 的 REGION、同一份原始 PBF 和内置驾车参数。默认使用 external 磁盘构建、format 2 和 regional 图容量。预算为输入不超过 512 MiB、scratch 16 GiB、查询加载分配估算 8 GiB；build/preflight 3600 秒，verify 和单次查询进程各 300 秒。查询计算本身仍限 10 秒。无效限速和异常转向采用 `config/regions.yaml` 中的通用业务策略，详见下文。

external 构建自身完成语义检查，不调用仍受 200 万对象限制的内存 preflight。独立 preflight-routing 执行一次 external 试构建与 verify，保留 attempt 审计但不发布 ready；正式 build-routing 不重复建图。显式审核配置可设置 builder: external、graph_capacity: regional、max_scratch_bytes 和 max_load_bytes；未指定 builder 的历史审核夹具继续使用 memory/v1。regional 仍受上游对象、图大小、跨度和数据质量限制，不保证任意省域成功。

```bash
export REGION=your/configured/local-region
export YYYYMMDD=20260803
export WORKDIR=/tmp/routing
export INPUT=/absolute/path/to/source.osm.pbf
make preflight-routing
make build-routing
make verify-routing
make smoke-routing
make pack-routing FORMAT=both
```

默认 smoke 从已验证 graph.bin（历史审核夹具为 graph.json） 中选取一条至少 10 米的有向道路，在其内部取点执行 nearest 和正向 route，验证数据集身份、有限成本、路线几何与分段连续性。没有可用道路或查询失败则停止发布 ready。它不声明已验证人工 NoRoute、所有转向限制或完整区域可达性。

所有步骤固定同一 REGION、日期与 WORKDIR。相对 INPUT 按 WORKDIR 解析。路网输入冻结、preflight、ready-last 发布和包内复验机制不变。

### 专项测试夹具

backend/tests/fixtures/routing/nanning-audit.yaml 仅用于固定南宁切片的回归测试，包含人工限制审核与查询案例。生产 Make 构建不读取它。诊断 CLI 的 `--config` 用于指定显式审核配置；普通入口的区域 ID 仅来自 `config/regions.yaml`，不使用日期或源快照白名单。

## 产物与恢复

- `outputs/<session>.routing/<dataset-id>/`：原始 manifest.json、graph.bin（v1 为 graph.json），构建/查询/进程回执。routing-build.json 保留能力握手、内存模式的完整 preflight/build CLI 包络，或外存模式的 external-build-validation 标记及完整 build 包络、逐关系诊断及审核策略，不仅保留 manifest 计数。
- `outputs/<session>.routing.ready.json`：最后原子提交，含文件大小/哈希、工具身份及配置哈希。
- `outputs/<session>.routing.bundle.{tar.gz,zip}`：独立审核包，含 routing-package.json、署名和许可链接；没有 install.json。包清单记录限制策略、审核集合和保守阻断的覆盖限制。
- 归档旁的 `.verified.json`：归档哈希、大小以及新目录解包后 verify/query 结果。
- `staging/routing/<attempt>/process-log.json`：有限 stdout/stderr、退出码、耗时和异常；Linux 下附 sampled_peak_rss_kib，采样可能错过峰值，不是精确资源配额。失败时另有 failure.json，保留结构化 error.details、命令及退出码，定位问题应使用诊断 code 而非解析 message。失败 attempt 保留以诊断，可由操作者确认后清理；不会删除旧有效版本。

同 session 排他锁立即拒绝并发。重复构建创建新 attempt，只有既有不可变 graph/manifest 一致且再次通过质量门才复用目录。ready 缺失、文件损坏、配置或工具身份变化均拒绝消费。尚未实现缓存。审核包拒绝链接、路径穿越、重复条目及超限展开；每种格式都在新目录重新 verify/smoke 后原子提交。

从旧工具或缺少限制策略/完整构建审计的 ready 升级时，需要以新锁定工具重建；不要手工修改 ready 或跨版本复用旧回执。

数据包提供 OSM 署名与 ODbL 链接，不捆绑 RouteWeft 可执行文件。正式分发仍需完成 ODbL 材料及 RouteWeft 项目许可审核。

## 验证与当前限制

### 新版转向审计兼容与预算

升级到锁定的 `5fdb38ce` 后，报告区分 `planned_blocked_way_ids` 与
`applied_blocked_way_ids`，并通过 `blockways_failure` 返回不可恢复关系。
本项目只接受计划集合、已应用集合和旧别名一致且没有 blocker 的成功报告；
ready 和审核包保留集合，消费时再次核验。阶段耗时 `build_metrics` 保留在回执中，
但不参与同一数据集重复构建的确定性审计比较。

普通入口仍采用目录中的 `block_ways` 策略。需要隔离结构异常关系时，可显式配置
`invalid_restrictions: quarantine_ways`，同时必须填写匹配输入的 `source_sha256`。
这是一种可能降低覆盖和可达性的独立策略，不推断空角色，不表示源数据已修复。
本项目检查工具支持、政策标记、完整审计和最终排除集合，并额外调用 `coverage`
确认被排除道路的残留边数为零；覆盖结果与 smoke 一起保存，打包时重验。

固定广东样本的审核配置与调用示例：

```bash
PYTHONPATH=backend/src .venv/bin/python -m huavd_map_build routing build \
  --config=config/routing/china-guangdong-20260803-quarantine.yaml \
  --region=china/guangdong --yyyymmdd=20261028 \
  --workdir=/tmp/routeweft-guangdong-quarantine \
  --input=/home/dev/data/source-map/guangdong-260803.osm.pbf
```

该配置使用明确的 12 GiB 加载估算预算及 `smoke_mode: graph-edge-v1`，
自动选择实际图边执行基础 nearest/route 检查。基础 smoke 和零残留边检查
不替代省级连通性、长距离路线质量或外部引擎对照验收。

RouteWeft alpha.2 的完整审计报告可超过旧版 256 条限制。本项目按新版
`restriction_audit` 校验完整扫描、无截断、观察/保留数量、实际序列化字节数、
限额和完成轮次，并按 `(attempt, relation_id)` 校验诊断顺序及唯一性。
固定硬边界为 32,768 条、16 MiB 审计 JSON、64 MiB 逻辑内存计费和 257 轮，
不信任报告自行声明的更大限额。未携带新版摘要的旧报告仍限 256 条。
单条诊断的成员上限与 maxspeed 审计边界不变。进程 stdout/stderr 各自有
32 MiB 上限，以容纳审计及结果包络；超限仍终止子进程并拒绝发布。

通过 CLI `--config` 指定的显式区域审核配置可选以下字段（普通入口继续使用工具默认值）：

```yaml
max_restriction_diagnostics: 8192   # 1..32768，工具默认 4096
max_restriction_audit_bytes: 16777216  # 1..16777216
max_blockways_attempts: 80         # 1..257，block_ways/quarantine_ways，工具默认 64
```

以上字段传给 full preflight 与 build；external 路径由 build 执行验证。
配置越界或工具未声明所需预算能力时，在建图前拒绝执行。增加预算不能解决
缺少安全 from/to 成员等关系语义错误，也不能绕过 verify、审计及 smoke 门禁。

`restriction_review.diagnostics[]` 可增加 `attempt` 以审核具体轮次；一旦使用，
所有条目都须显式填写。未填写轮次的旧审查配置仍按完整的关系/错误列表比较，
不会自动去重跨轮次事件。

```bash
PYTHONPATH=backend/src python3 -m unittest discover -s backend/tests -p test_routing.py -v
ROUTEWEFT_TEST_BIN=/absolute/routeweft ROUTEWEFT_TEST_SHA256=<sha256> PYTHONPATH=backend/src python3 -m unittest discover -s backend/tests -p test_routing.py -v
```

第二条启用真实 CLI 合成 PBF 全流程，覆盖构建、验证、成功查询、明确 NoRoute、重建和两种包的异地解包复核。普通测试不下载 PBF。

另设置 `ROUTEWEFT_TEST_NANNING_PBF=/absolute/nanning.osm.pbf` 可启用固定南宁夹具的真实输入验收，包含严格拒绝、结构化诊断、显式保守阻断及两种包的审计留存；输入必须匹配夹具哈希。


当前独立接口不将历史地图包与路由包自动配对。地图和路由资产配对时必须具有一致的原始 PBF SHA-256 证据。

升级此版本后执行 `make setup-routeweft ROUTEWEFT_SOURCE=/absolute/path/to/routeweft` 安装锁定的新工具，再重新构建路网。新标准包声明 `routeweft-dataset-v2` 与 `routing.graph_capacity=regional`，消费者必须支持相应格式和容量；旧 ready 不可跨构建配置复用。

## 数据质量业务策略

区域 ID 唯一来自 `config/regions.yaml`。该文件顶层 `routing` 定义所有区域、所有日期的默认策略，区域条目的 `routing` 可覆盖单个字段，不按父区域隐式继承：

```yaml
routing:
  invalid_maxspeed: use_default
  invalid_restrictions: block_ways
```

- `invalid_maxspeed: use_default`：无法解析的通用限速使用道路类别默认速度估算成本，方向限速回退到已解析的通用速度。有效限速保持上游语义。默认速度不代表核实后的法定限速。设为 `reject` 可要求严格拒绝。
- `invalid_restrictions: block_ways`：由上游根据当前输入识别异常转向关系，保守排除其现存关联道路并重建图；不忽略限制，不猜测缺失转向。无法安全排除时构建仍失败。设为 `reject` 可要求严格拒绝。

普通 Make/CLI 无需额外开关、日期白名单或人工道路 ID 清单。缺少 routing 配置时兼容回落到 reject。字段拼写错误、未知策略及错误类型会在目录加载时拒绝。

生产限速策略优先级：CLI `--invalid-maxspeed`、显式环境变量 `ROUTING_INVALID_MAXSPEED`、区域字段、目录默认字段、reject。Make 不再注入 reject 覆盖目录设置。显式 `--config` 是独立审核模式，其配置优先于环境变量，可保留源哈希和 restriction_review 做精确回归；生产流程不会自动加载它。

构建报告必须与 manifest 一致：限制计数须匹配完整诊断及去重后的排除道路集合，每条排除道路须有关系成员证据。诊断重复、缺失、截断、未知错误代码或计数不一致均阻止 ready 发布。限速审计上限为 256 项且估算文本大小不超过 64 KiB；转向诊断在新版完整审计摘要下最多 32,768 项，未携带新版摘要的旧报告仍限 256 项，每关系最多 256 个成员。其他审计预算见上文；超限失败，不截断后继续发布。上游自身的资源和安全排除限制仍生效。

实际策略参与配置摘要。ready、构建回执、独立包和标准联合包均记录策略、限速回退、`blocked_way_ids`、`restriction_diagnostics`，包中注明可能减少道路覆盖和可达性。策略改变或旧 ready 缺少完整审计字段时必须重建，不能手工改 ready。无异常输入不产生排除清单。

独立 `pack-routing` 仍生成 `installable=false` 的审计包；标准地图联合包通过原有 `make pack` 入口生成。本次业务策略不改变安装协议。

### 广西 20260803 已审核交付

`config/routing/china-guangxi-20260803-audit.yaml` 绑定广西输入 SHA-256，显式选择 external/regional/v2、use_default 及 block_ways，核对 14 个异常关系和 21 条道路的完整排除集合。它包含省域正常路线、绕行和真实不连通分量的 NoRoute 查询，不可用于其他源快照。

该配置仅供显式 `routing build/verify/smoke/pack --config=config/routing/china-guangxi-20260803-audit.yaml` 审核使用，不被普通 Make/CLI 自动加载，也不是区域业务配置。所有步骤保持 REGION、YYYYMMDD 和 WORKDIR 一致。该配置用于独立路网审计交付，pack 输出 `installable=false` 的审计包。发布证据见 [广西发布记录](../../report/routeweft-guangxi-release-20261020.md)。
