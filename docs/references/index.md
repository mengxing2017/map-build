# 契约与外部工具

## 外部工具

| 工具 | 用途 |
| :--- | :--- |
| devbox | 开发环境与工具声明 |
| osmium | OSM PBF tags-filter、export |
| tippecanoe | GeoJSONSeq 到 PMTiles |
| pmtiles | PMTiles metadata edit、header show |
| jq/yq | JSON/YAML 解析 |
| wget | Geofabrik 和 release 下载 |

## 外部数据源

Geofabrik PBF 和 MD5 地址配置在 `config/regions.yaml`。`scripts/fetch.sh` 使用 `wget --timestamping` 下载到 `${WORKDIR}/mirror` 并执行 `md5sum -c`。

## PMTiles 约束

当前校验以 PMTiles v3 为目标：

- magic 为 `PMTiles`。
- spec version 为 `3`。
- tile type 为 `1`，即 MVT。
- internal compression 与 tile compression 为 gzip。
- root directory 必须完整位于文件前 16KiB 内。

## HUAVD 契约

本项目生成的 manifest 和 metadata 会写入 HUAVD 字段：

```text
huavd:source-id
huavd:asset-role
huavd:build-time
huavd:region
huavd:data-license
```

地图产品契约和跨服务边界以 HUAVD 总体文档为真值源；本项目只负责离线地图构建产物。
