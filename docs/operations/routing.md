# RouteWeft 独立审核数据集

本集成提供独立 CLI 构建、验证、质量门和 tar.gz/zip 审核包；不提供客户端联合安装，不修改地图 Role 或 install.json。`ROUTING` 默认为 0；`ROUTING=1 make release` 明确失败，当前尚不支持联合发布。

## 工具准备

普通 routing 构建不联网，也不依赖地图渲染器。Python 需要 PyYAML。

```bash
make setup-routeweft ROUTEWEFT_SOURCE=/absolute/path/to/clean/routeweft WORKDIR=/tmp/routing
make doctor-routeweft WORKDIR=/tmp/routing
```

源码必须是 `config/routeweft.lock.json` 锁定的干净提交。未提供 `ROUTEWEFT_SOURCE` 时，只有显式 setup 会从锁定仓库获取提交。setup 使用 Cargo.lock 和仓库工具链编译，回执记录提交、二进制及 Cargo.lock 哈希、平台、rustc 和时间。Rust 依赖必须预先可用或允许 setup 下载。

已有二进制无需 Rust 环境：设置绝对 `ROUTEWEFT_BIN`，并提供 `ROUTEWEFT_SHA256` 或 `ROUTEWEFT_RECEIPT`。显式 SHA-256 是操作者信任入口，不声称能单凭哈希证明源码提交。每次调用重新核对二进制哈希。doctor 使用本仓库生成的微型 PBF 实际 build/verify，检查 schema=1、format=1、profile=driving-v1。

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
    verify_timeout_s: 120
    query_timeout_s: 30
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

```bash
make build-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml INPUT=/absolute/city.osm.pbf
make verify-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml
make smoke-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml
make pack-routing REGION=china/nanning YYYYMMDD=20260803 WORKDIR=/tmp/routing ROUTING_CONFIG=/absolute/config.yaml FORMAT=both
```

四步须固定同一日期/session。相对 INPUT 按 WORKDIR 解析。只接受普通非符号链接输入，复制为独立只读会话快照并在构建前后复核 SHA-256；不使用普通硬链接冒充冻结。配置可锁定已审核输入哈希。构建使用不预建的唯一 dataset 路径，失败不重试、不降低质量。

## 产物与恢复

- `outputs/<session>.routing/<dataset-id>/`：原始 manifest.json、graph.json，构建/查询/进程回执。
- `outputs/<session>.routing.ready.json`：最后原子提交，含文件大小/哈希、工具身份及配置哈希。
- `outputs/<session>.routing.bundle.{tar.gz,zip}`：独立审核包，含 routing-package.json、署名和许可链接；没有 install.json。
- 归档旁的 `.verified.json`：归档哈希、大小以及新目录解包后 verify/query 结果。
- `staging/routing/<attempt>/process-log.json`：有限 stdout/stderr、退出码、耗时和异常。失败 attempt 保留以诊断，可由操作者确认后清理；不会删除旧有效版本。

同 session 排他锁立即拒绝并发。重复构建创建新 attempt，只有既有不可变 graph/manifest 一致且再次通过质量门才复用目录。ready 缺失、文件损坏、配置或工具身份变化均拒绝消费。尚未实现缓存。审核包拒绝链接、路径穿越、重复条目及超限展开；每种格式都在新目录重新 verify/smoke 后原子提交。

数据包提供 OSM 署名与 ODbL 链接，不捆绑 RouteWeft 可执行文件。正式分发仍需完成 ODbL 材料及 RouteWeft 项目许可审核。

## 验证与当前限制

```bash
PYTHONPATH=backend/src python3 -m unittest discover -s backend/tests -p test_routing.py -v
ROUTEWEFT_TEST_BIN=/absolute/routeweft ROUTEWEFT_TEST_SHA256=<sha256> PYTHONPATH=backend/src python3 -m unittest discover -s backend/tests -p test_routing.py -v
```

第二条启用真实 CLI 合成 PBF 全流程，覆盖构建、验证、成功查询、明确 NoRoute、重建和两种包的异地解包复核。普通测试不下载 PBF。


当前独立接口不将历史地图包与路由包自动配对。地图和路由资产配对时必须具有一致的原始 PBF SHA-256 证据。
