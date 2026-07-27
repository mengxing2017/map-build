# 构建管线

## 主流程

`scripts/build.sh` 是主编排入口。一次标准 build 的阶段如下：

1. 校验 region、role、YYYYMM 和输入 PBF。
2. 将输入 PBF 链接到 `${WORKDIR}/staging/${SESSION}/source.osm.pbf`。
3. `scripts/tags-filter.sh` 按 layer 运行 `osmium tags-filter`。
4. `scripts/export.sh` 按 layer 运行 `osmium export`，输出 GeoJSONSeq。
5. `scripts/normalize.sh` 过滤并归一化 properties。
6. `scripts/tippecanoe.sh` 按 role 生成 PMTiles。
7. `scripts/metadata.sh` 写入 PMTiles metadata。
8. `scripts/manifest.sh` 生成 manifest。
9. `scripts/attribution.sh` 生成 attribution。
10. `scripts/verify.sh` 校验 PMTiles 和伴随文件。
11. 写出 `.sha512` sidecar。

## 输入输出

默认工作目录：

```text
/tmp/huavd-map-build
```

关键路径：

| 路径 | 内容 |
| :--- | :--- |
| `${WORKDIR}/mirror/` | Geofabrik PBF 和 MD5 |
| `${WORKDIR}/cache/tags-filter/` | per-layer 过滤后的 PBF |
| `${WORKDIR}/cache/configs/` | YAML 转 JSON 缓存 |
| `${WORKDIR}/staging/${SESSION}/layers/` | per-layer GeoJSONSeq |
| `${WORKDIR}/outputs/` | PMTiles、manifest、attribution、bundle |

产物命名：

```text
{region-slug}-{yyyymm}.{role}.pmtiles
{region-slug}-{yyyymm}.{role}.pmtiles.sha512
{region-slug}-{yyyymm}.{role}.manifest.json
{region-slug}-{yyyymm}.{role}.attribution.json
{region-slug}-{yyyymm}.bundle.tar.gz
{region-slug}-{yyyymm}.bundle.zip
```

## Role

`ROLE=base` 生成基础地图 PMTiles。`ROLE=building` 生成建筑专用 PMTiles。`ROLE=both` 会依次处理可构建的 role。

building role 只有在 `config/regions.yaml` 中同时满足以下配置时才启用：

```yaml
huavd:
  asset_role: "building-vector"
  source_type: "derived-building"
```

否则 `ROLE=both` 会跳过 building 并输出 warning。

## 验证范围

`scripts/verify.sh` 当前校验：

- PMTiles magic、spec version、compression、tile type、zoom。
- root directory 是否完整位于前 16KiB。
- PMTiles metadata JSON 是否可读。
- metadata bounds 是否与 header bounds 匹配。
- manifest `output.size_bytes` 是否匹配文件大小。
- manifest `output.sha512` 和 sidecar SHA512 是否匹配。

它不校验瓦片内容、每个 zoom/layer 的实际覆盖情况，也不做 manifest JSON Schema 校验。
