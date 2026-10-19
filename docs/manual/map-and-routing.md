# 地图与路网构建

标准矢量地图包（`base`、`both`）和栅格＋矢量地图包（`base_raster`、`both_raster`，以及携带 base 的 `raster_bake` 包）默认必须带同源路网。`make build` 在地图完成后用会话冻结的原始 PBF 构建路网；`make pack` 校验并收录路网。路网失败、缺失或源指纹不一致时不生成新包。`ROUTING=0` 不能关闭此要求。

路网读取原始 OSM PBF，不读取 PMTiles。地图和路网是同源数据的两个分支，地图不是路网的输入。

## 准备

地图区域必须已配置在 `config/regions.yaml`。路网区域须在 `ROUTING_CONFIG` 中显式启用，提供 profile、资源预算以及经过审核的成功与 NoRoute 查询。默认 `config/routing.yaml` 无启用区域，需要配置后才能构建标准包。测试夹具不是生产默认配置。完整字段见 [路网操作说明](../operations/routing.md)。

先执行普通地图工具准备，再安装锁定的 RouteWeft：

```bash
make setup-routeweft ROUTEWEFT_SOURCE=/absolute/path/to/clean/routeweft WORKDIR=/tmp/map-build
make doctor-routeweft WORKDIR=/tmp/map-build
```

## 构建和打包

下列示例中的城市区域必须已经配置；不能把城市切片标为整个省域。

```bash
export WORKDIR=/tmp/map-build
export REGION=china/nanning
export YYYYMMDD=20260803
export INPUT=/absolute/path/to/city.osm.pbf
export ROUTING_CONFIG=/absolute/path/to/reviewed-routing.yaml

# 标准矢量地图及其路网
make build ROLE=both
make pack ROLE=both FORMAT=both

# 栅格＋矢量地图及其路网，需要 Native 渲染器
make build ROLE=both_raster
make pack ROLE=both_raster FORMAT=both
```

`make release` 也执行上述默认路网构建。它将实际工作目录隔离为 `${WORKDIR}/${SESSION}`，工具须安装在实际目录，或通过带 SHA-256 的受信二进制注入。底层 `build execute-vector` 仍是单分支接口，调用后须执行 `build-routing` 才能通过标准打包门禁；`build-routing` 本身不生成地图。

## 包内容与接入

归档沿用 `<session>.bundle.tar.gz` 和 `.bundle.zip`。其中包含：

- 地图 PMTiles、manifest、署名和样式资源。
- `install.json`：原有 `huavd-map-install/v1` 地图安装描述。
- `routing/`：RouteWeft 数据集、构建/查询审计及 OSM 署名。
- `package.json`：`huavd-map-package/v1` 包级清单，声明路网 required、格式/profile、同源 SHA-256、限制策略及逐文件哈希。
- `SHA256SUMS`、`SHA512SUMS`：覆盖地图、路网和清单。

打包从 ready 校验路网，再复制到包目录，对副本重跑 verify 和查询质量门。所有地图 manifest 的 `source.sha256` 必须与路网一致；历史缺少该字段的地图必须重建。

消费者必须识别 `package.json.required_capabilities` 中的 `routeweft-dataset-v1`，将必需路网与地图共同安装。仅识别旧 `install.json` 的客户端尚不能保证联合安装；本仓库生成完整数据包，不代表外部客户端已经升级。`building` 单资产、DEM、overview 和 derived-map 独立工作流不在本次标准区域包范围内。

## 输入限制

用户提供的广西省域 PBF 不能自动套用南宁审核配置。RouteWeft 的容量、覆盖范围及限制关系审核必须先通过，不能因为文件小于 512 MiB 就认定整个省可路由。默认严格拒绝无效限制；显式 `block_ways` 需要固定源哈希与完整审核集合，会减少道路覆盖和可达性。未满足条件时停止出包，不静默省略路网。
