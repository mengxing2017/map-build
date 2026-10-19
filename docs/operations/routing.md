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

## 城市配置与执行

`config/routing.yaml` 默认没有启用区域。地图区域存在不代表支持路由；省域输入不能仅因低于 512 MiB 就启用。通过 `ROUTING_CONFIG` 指定审核配置，只有真实验收通过后才写入默认白名单。配置示例（坐标、范围及源哈希须按实际审核结果填写）：

```yaml
schema: 1
regions:
  china/nanning:
    enabled: true
    profile: driving
    max_input_bytes: 104857600
    source_sha256: <reviewed-city-PBF-SHA256>
    build_timeout_s: 600
    preflight_timeout_s: 600
    verify_timeout_s: 120
    query_timeout_s: 30
    invalid_restrictions: reject
    query_budget:
      radius-m: 50
      timeout-ms: 1000
    smoke:
      - command: nearest
        coordinates: '<longitude>,<latitude>'
        expect: ok
      - command: route
        coordinates: '<lon1>,<lat1>;<lon2>,<lat2>'
        expect: ok
        distance_m: [100, 2000]
        duration_s: [10, 600]
      - command: route
        coordinates: '<reviewed-disconnected-or-restricted-pair>'
        expect: NoRoute
```

`diagnostic_max` 可按诊断字段设置上限。无路只接受指定错误 kind 和退出码 3，超时/预算耗尽不能充当无路结论。方向和限制案例应分别添加到 smoke。坐标和成本示例不是南宁验收结果。

默认 `invalid_restrictions: reject`。只有显式设置为 `block_ways` 并提供固定 `source_sha256` 及 `restriction_review` 才允许保守阻断。review 必须包含非空 `reason`、全部 `blocked_way_ids` 和 `diagnostics`（每项为 `relation_id` 与 `code`）。预检及构建的实际审计必须与此集合完全一致；不同、截断或未知诊断均拒绝发布。此模式不修复原始限制，会减少道路覆盖和可达性，不会由严格失败自动切换。

每条 smoke 可通过 `query_budget` 覆盖全局查询预算，例如精确的单行道用例使用 `{radius-m: 0.01}`。成本范围仍须按审核结果填写。

```bash
make preflight-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml INPUT=/absolute/city.osm.pbf
make build-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml INPUT=/absolute/city.osm.pbf
make verify-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml
make smoke-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml
make pack-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml FORMAT=both
```

所有步骤须固定同一日期/session。相对 INPUT 按 WORKDIR 解析。只接受普通非符号链接输入，复制为独立只读会话快照并在构建前后复核 SHA-256；不使用普通硬链接冒充冻结。构建自动执行 preflight，独立 preflight 只产生 attempt 和审计，不写 ready。preflight 使用完整内存建图，耗时和内存量级接近构建，不是廉价文件头检查。构建使用不预建的唯一 dataset 路径，失败不重试、不自动切换策略。

### 南宁切片验收夹具

`backend/tests/fixtures/routing/nanning-audit.yaml` 是固定输入的测试夹具，默认 `config/routing.yaml` 仍无启用区域。该夹具仅匹配 bbox `108.25,22.75,108.42,22.88`、complete_ways 提取、SHA-256 为 `e7eee17e89b65bdff18bdc1be45e59952a1a3774fc9845a9488e67968f31c4ba` 的城市切片。手动验收时，将上述命令的 `ROUTING_CONFIG` 替换为夹具路径，INPUT 指向匹配的城市 PBF。完整广西省域 PBF 不能作为此夹具输入。该夹具使用保守阻断模式，产物只作独立审核，不代表完整道路覆盖或联合安装能力。

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
