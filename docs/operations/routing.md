# RouteWeft 独立审核数据集

标准区域地图包默认带路网；构建、打包和包级协议见 [地图与路网构建](../manual/map-and-routing.md)。本页说明路网分支的独立审核入口，它们也可用于排查标准包的路网门禁。独立 `pack-routing` 仍生成审核包，不替代标准地图包。

## 工具准备

普通 routing 构建不联网，也不依赖地图渲染器。Python 需要 PyYAML。

```bash
make setup-routeweft ROUTEWEFT_SOURCE=/absolute/path/to/clean/routeweft WORKDIR=/tmp/routing
make doctor-routeweft WORKDIR=/tmp/routing
```

源码必须是 `config/routeweft.lock.json` 锁定的干净提交。未提供 `ROUTEWEFT_SOURCE` 时，只有显式 setup 会从锁定仓库获取提交。setup 使用 Cargo.lock 和仓库工具链编译，回执记录提交、二进制及 Cargo.lock 哈希、平台、rustc 和时间。Rust 依赖必须预先可用或允许 setup 下载。

已有二进制无需 Rust 环境：设置绝对 `ROUTEWEFT_BIN`，并提供 `ROUTEWEFT_SHA256` 或 `ROUTEWEFT_RECEIPT`。显式 SHA-256 是操作者信任入口，不声称能单凭哈希证明源码提交。每次调用重新核对二进制哈希。doctor 使用默认微型 PBF 实际运行 version/preflight/build/verify，检查 schema=1、format=1、profile=driving-v1、命令和限制策略能力。不要将真实构建的 INPUT 传给默认工具探针；显式提供 INPUT 时，doctor 会对该文件执行严格策略探针。

## REGION 与执行

普通构建直接复用 config/regions.yaml 的 REGION、同一份原始 PBF 和内置驾车参数，不读取额外区域白名单，也不需要 ROUTING_CONFIG。默认预算为输入不超过 512 MiB，build/preflight 3600 秒，verify 300 秒，单次查询 30 秒；无效转向限制采用 reject。

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

默认 smoke 从已验证 graph.json 中选取一条至少 10 米的有向道路，在其内部取点执行 nearest 和正向 route，验证数据集身份、有限成本、路线几何与分段连续性。没有可用道路或查询失败则停止发布 ready。它不声明已验证人工 NoRoute、所有转向限制或完整区域可达性。

所有步骤固定同一 REGION、日期与 WORKDIR。相对 INPUT 按 WORKDIR 解析。路网输入冻结、preflight、ready-last 发布和包内复验机制不变。

### 专项测试夹具

backend/tests/fixtures/routing/nanning-audit.yaml 仅用于固定南宁切片的回归测试，包含人工限制审核与查询案例。生产 Make 构建不读取它。诊断 CLI 的 --config 仅用于显式审核测试，不是地图包构建要求；普通入口只需 REGION。

## 产物与恢复

- `outputs/<session>.routing/<dataset-id>/`：原始 manifest.json、graph.json，构建/查询/进程回执。routing-build.json 保留能力握手、完整 preflight/build CLI 包络、逐关系诊断及审核策略，不仅保留 manifest 计数。
- `outputs/<session>.routing.ready.json`：最后原子提交，含文件大小/哈希、工具身份及配置哈希。
- `outputs/<session>.routing.bundle.{tar.gz,zip}`：独立审核包，含 routing-package.json、署名和许可链接；没有 install.json。包清单记录限制策略、审核集合和保守阻断的覆盖限制。
- 归档旁的 `.verified.json`：归档哈希、大小以及新目录解包后 verify/query 结果。
- `staging/routing/<attempt>/process-log.json`：有限 stdout/stderr、退出码、耗时和异常；Linux 下附 sampled_peak_rss_kib，采样可能错过峰值，不是精确资源配额。失败时另有 failure.json，保留结构化 error.details、命令及退出码，定位问题应使用诊断 code 而非解析 message。失败 attempt 保留以诊断，可由操作者确认后清理；不会删除旧有效版本。

同 session 排他锁立即拒绝并发。重复构建创建新 attempt，只有既有不可变 graph/manifest 一致且再次通过质量门才复用目录。ready 缺失、文件损坏、配置或工具身份变化均拒绝消费。尚未实现缓存。审核包拒绝链接、路径穿越、重复条目及超限展开；每种格式都在新目录重新 verify/smoke 后原子提交。

从旧工具或缺少限制策略/完整构建审计的 ready 升级时，需要以新锁定工具重建；不要手工修改 ready 或跨版本复用旧回执。

数据包提供 OSM 署名与 ODbL 链接，不捆绑 RouteWeft 可执行文件。正式分发仍需完成 ODbL 材料及 RouteWeft 项目许可审核。

## 验证与当前限制

```bash
PYTHONPATH=backend/src python3 -m unittest discover -s backend/tests -p test_routing.py -v
ROUTEWEFT_TEST_BIN=/absolute/routeweft ROUTEWEFT_TEST_SHA256=<sha256> PYTHONPATH=backend/src python3 -m unittest discover -s backend/tests -p test_routing.py -v
```

第二条启用真实 CLI 合成 PBF 全流程，覆盖构建、验证、成功查询、明确 NoRoute、重建和两种包的异地解包复核。普通测试不下载 PBF。

另设置 `ROUTEWEFT_TEST_NANNING_PBF=/absolute/nanning.osm.pbf` 可启用固定南宁夹具的真实输入验收，包含严格拒绝、结构化诊断、显式保守阻断及两种包的审计留存；输入必须匹配夹具哈希。


当前独立接口不将历史地图包与路由包自动配对。地图和路由资产配对时必须具有一致的原始 PBF SHA-256 证据。
