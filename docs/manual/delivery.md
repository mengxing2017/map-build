# 产物、打包与导入

[返回手册目录](./index.md)

## 产物位置

直接执行 `make build`、`make verify`、`make pack` 或 `make prepare-import` 时，构建产物写入：

```text
${WORKDIR}/outputs/
```

`make release`、`make release-import` 及对应的 release 导入入口会将同一 session 隔离在：

```text
${WORKDIR}/${SESSION}/outputs/
```

常见文件名：

```text
china-guangxi-20260818.base.pmtiles
china-guangxi-20260818.base.pmtiles.sha512
china-guangxi-20260818.base.manifest.json
china-guangxi-20260818.base.attribution.json
china-guangxi-20260818.building.pmtiles
china-guangxi-20260818.building.pmtiles.sha512
china-guangxi-20260818.building.manifest.json
china-guangxi-20260818.building.attribution.json
china-guangxi-20260818.import.zip
china-guangxi-20260818.import.zip.sha512
china-guangxi-20260818.bundle.tar.gz
china-guangxi-20260818.bundle.zip
```

`ROLE=building` 只有在 `config/regions.yaml` 中对应 region 启用 building metadata 时才会构建。否则使用 `ROLE=both` 会跳过 building 并给出 warning。

## 构建产物与运行时 map_root 的边界

`huavd-map-build` 的 `${WORKDIR}/outputs/` 是构建输出目录，不是 `huavd-map` 的运行时地图目录。不要让 `huavd-map` 直接扫描 `/tmp/huavd-map-build/outputs`，也不要把 `WORKDIR` 默认值改成 `/tmp/huavd-map`。

`huavd-map` 的 PMTiles 消费入口是 `offline-maps` 状态机：先创建元数据记录，再把 PMTiles 放入 staging 目录，经过 SHA-512 校验和 import 后进入 `installed` 或 `active` 状态。`huavd-map-build` 只负责生成可交付的导入包和描述符，不执行导入、激活，也不写入 `huavd-map` 的主落盘目录。

导入元数据中的 `name` 必须是不带 `.pmtiles` 扩展名的 stem，例如：

```text
china-guangxi-20260818.base
```

`huavd-map` 会根据 `name` 自动追加 `.pmtiles`。如果把 `name` 写成 `china-guangxi-20260818.base.pmtiles`，运行时文件名会变成 `china-guangxi-20260818.base.pmtiles.pmtiles`。

## 准备导入包

已有 PMTiles、manifest、attribution 和 SHA-512 sidecar 后，可以生成给 `huavd-map` 导入工具消费的压缩包：

```bash
export REGION=china/guangxi
export YYYYMMDD=20260818
export ROLE=base

make prepare-import
```

需要 tar.gz 格式时：

```bash
make prepare-import IMPORT_FORMAT=tar
```

默认输出文件：

```text
${WORKDIR}/outputs/china-guangxi-20260818.import.zip
${WORKDIR}/outputs/china-guangxi-20260818.import.zip.sha512
```

压缩包内容：

```text
import-package/
  install.json
  .staging/
    {transfer_id}/
      china-guangxi-20260818.base.pmtiles
```

实际 archive 顶层就是 `install.json` 和 `.staging/`；上面的 `import-package/` 只是建议解压目录名。`prepare-import` 会读取 `${WORKDIR}/outputs/${SESSION}.${ROLE}.manifest.json` 和 `${WORKDIR}/outputs/${SESSION}.${ROLE}.pmtiles.sha512`，复制 PMTiles 到导入包 staging 缓存，并校验复制后的 SHA-512。脚本不会发送 HTTP 请求，也不要求 `huavd-map` 服务正在运行。

需要把当前 session 中可用的 role 聚合为一个导入包时：

```bash
make prepare-import-all
```

如果当前 region 没有 building 产物，`prepare-import-all` 会跳过 building 并给出 warning。导入包中的 `install.json` 包含 `offline_maps[]` 和可选的 `bundles[]` 元数据，接收端据此在 `huavd-map` 侧创建记录、复制 staging 文件并调用 import。

手动导入时，先把 `.import.zip` 解压到 `huavd-map` 约定的 `import-package/` 目录，使 `install.json` 与 `.staging/{transfer_id}/` 保持相对路径关系不变。之后在 `huavd-map` 侧按 `install.json` 创建 `offline-maps` 记录并执行 import；如果消费侧已经实现一键导入端点，则直接让该端点读取解压后的 `install.json`。

## Pack 产物与 install.json

`make pack`、`make pack-tar`、`make pack-zip` 生成的是分发包，不是 `huavd-map` 运行时直接读取的目录。打包时会保留既有文件：

```text
*.pmtiles
*.pmtiles.sha512
*.manifest.json
*.attribution.json
```

同时在包内新增：

```text
install.json
```

`install.json` 描述如何把包内 PMTiles 作为 `offline-maps` 单资产导入到 `huavd-map`，包括稳定的 `id`、不带扩展名的 `name`、`source-id`、`asset-role`、`source-type`、`coord-system`、`checksum` 和 staging 文件名。bundle 只表达多个 offline-map 的数据库关联关系，不复制 PMTiles 字节，也不替代 `huavd-map` 的导入状态机。

## 常用交付流程

端到端一次构建（使用日常 region 版本模板）：

```bash
unset HUAVD_MAP_PACKAGE_VERSION \
      HUAVD_MAP_PACKAGE_VERSION_BASE \
      HUAVD_MAP_PACKAGE_VERSION_BUILDING \
      HUAVD_MAP_PACKAGE_VERSION_DEM

export REGION=china/guangxi
export YYYYMMDD=20260818
# WORKDIR 默认 /tmp/huavd-map-build，需要显式换盘时再 export WORKDIR

make fetch                      # 下载 Geofabrik PBF + MD5
make release ROLE=both          # build + pack + verify（含 --strict 校验 package_version）
make prepare-import-release-all # 聚合 base/building 的 .import.zip

# ${WORKDIR}/${SESSION}/outputs/ 产物：
#   china-guangxi-20260818.base.pmtiles          ← vector tiles
#   china-guangxi-20260818.base.manifest.json    ← .huavd_record.package_version = "20260818.base"
#   china-guangxi-20260818.building.pmtiles      ← building role (region 启用时)
#   china-guangxi-20260818.building.manifest.json
#                                              .huavd_record.package_version = "20260818-building"
#   china-guangxi-20260818.bundle.zip            ← 含 install.json
#   china-guangxi-20260818.import.zip            ← huavd-map 导入包
```

## 补充文字渲染资源

生成 PMTiles 后再补 glyph 和 style：

```bash
make glyph REGION=china/guangxi YYYYMMDD=20260818
make style REGION=china/guangxi YYYYMMDD=20260818
make pack REGION=china/guangxi YYYYMMDD=20260818 ROLE=base FORMAT=zip
```

构建时同时生成 glyph 和 style：

```bash
make build REGION=china/guangxi YYYYMMDD=20260818 GLYPH=1
make pack REGION=china/guangxi YYYYMMDD=20260818 ROLE=base FORMAT=zip
```

`make pack` 会在 outputs 目录写入 `${SESSION}.pack.metrics.json`，`make prepare-import` 会在导入归档旁写入 `${SESSION}.import.zip.metrics.json` 或 `${SESSION}.import.tar.gz.metrics.json`。它们分别记录清单哈希、归档、复制校验和成品大小，便于把交付尾部成本纳入同一基准。
