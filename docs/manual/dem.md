# DEM 高程地图

[返回手册目录](./index.md)

DEM（数字高程）是独立于 OSM PBF 的离线栅格资产，使用 `config/dem.yaml` 中已声明的授权源（不要在脚本里硬编码公共下载 URL）。`make build`/`make release` 默认不跑 DEM，需要按下面的端到端流程单独走：

```bash
unset HUAVD_MAP_PACKAGE_VERSION \
      HUAVD_MAP_PACKAGE_VERSION_DEM

export REGION=china/guangxi
export YYYYMMDD=20260818
export DEM_SOURCE=srtm                # config/dem.yaml 中声明的源 id
export DEM_ENCODING=terrarium         # mapbox-terrain-rgb | terrarium | heightmap-u16
export DEM_INPUT=/data/srtm/guangxi.tif  # 已有授权 TIFF；或配合 make fetch-dem 拉取

make fetch-dem
make build-dem
make verify-dem
make pack   ROLE=all FORMAT=zip      # 一次性把 base/building/dem 打入 bundle
make prepare-import-all
```

`make fetch-dem` 把授权 DEM 拷贝到 `${WORKDIR}/mirror/dem/`，并写入可被
`build-dem.sh` 识别的 metadata；`make build-dem` 依赖 `pmtiles` CLI 把 TIFF 栅格
生成 DEM PMTiles。`build-dem.sh:99` 会调用 `region_package_version "${REGION}" dem`，
**DEM 现在强依赖 `package_version` 字段**：未设置 `huavd.default_package_version_template`
或对应 region 模板时（例如自定义 region 还没填 `package_version_template`），
脚本会 `die` 退出，避免写出没有版本号的 DEM manifest。

`make verify-dem` 总是 `--strict` 模式，会校验：

- `manifest.huavd_record.package_version` 非空且匹配 `^[A-Za-z0-9._+-]+$`。
- PMTiles magic / spec_version / raster tile_type。
- metadata 包含 `dem-encoding`（`mapbox-terrain-rgb` / `terrarium` / `heightmap-u16`）和 `huavd:vertical-datum`。
- PMTiles / manifest / sha512 sidecar 三者一致。

DEM 在 `install.json` 中作为 `offline_maps[]` 的 `asset-role=dem-raster` 条目出现，
`bundles[].bundle-version` 取 base role 的 `package-version`（不是 dem 自己的）。
