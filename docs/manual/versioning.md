# 版本管理与 CI 发布

[返回手册目录](./index.md)

## package-version 解析规则

`manifest.huavd_record.package_version`、`install.json` 的 `offline_maps[].package-version` 与 `bundles[].bundle-version` 都从同一个值派生。`scripts/lib/config.sh:region_package_version()` 按以下优先级解析：

1. **per-role env**：`HUAVD_MAP_PACKAGE_VERSION_BASE` / `_BUILDING` / `_DEM`（按 role 大写）。
2. **全局 env**：`HUAVD_MAP_PACKAGE_VERSION`。
3. **region 模板**：沿 `geofabrik.parent_region` 上溯读取 `huavd.package_version_template`。
4. **per-role 默认**：`huavd.package_version_template_per_role[<role>]`（`{yyyymmdd}.{role}` 之外常用 `-building` / `-dem` 模式）。
5. **全局默认**：`huavd.default_package_version_template`，缺省回落 `{yyyymmdd}.{role}`。

命中规则 1–2 后跳过模板渲染，并 `INFO package_version source=env (...=...)` 日志记录来源，便于排查 CI 中漏 `unset` 的覆盖。env 值必须匹配 `^[A-Za-z0-9._+-]+$`，包含空格或其它字符会 `die` 退出。

模板支持两个占位符：

- `{yyyymmdd}` → 当前 `YYYYMMDD`（如 `20260818`）。
- `{role}` → 当前 role（`base` / `building` / `dem`）。

**历史契约**：当 region 自带模板（不在 `huavd.default_package_version_template` 之下）且 role 是 `building` 或 `dem` 时，第一个 `.{yyyymmdd}` 会被替换为 `-<role>.{yyyymmdd}`。仓库当前没有 region 使用这种模板，仅作记录：

| region 模板 | base | building | dem |
| :--- | :--- | :--- | :--- |
| `v1.0.{yyyymmdd}.cn` | `v1.0.20260818.cn` | `v1.0-building.20260818.cn` | `v1.0-dem.20260818.cn` |
| `1.0.{yyyymmdd}.base` | `1.0.20260818.base` | `1.0-building.20260818.base` | `1.0-dem.20260818.base` |

注：纯 `{yyyymmdd}.{role}`（无前缀）和不含 `.{yyyymmdd}` 的模板不会触发替换；`per-role env` / `全局 env` 也不经过这一步。

### 人工定版

默认情况下 `manifest.huavd_record.package_version` 和 `install.json` 的
`offline_maps[].package-version`、`bundles[].bundle-version` 都由
`config/regions.yaml` 的 `huavd.package_version_template`（含父子继承）渲染，
具体规则见 [package-version 解析规则](#package-version-解析规则)。

如果要锁住与月份无关的 RC 版本号，设 `HUAVD_MAP_PACKAGE_VERSION` 即可跳过模板：

```bash
export HUAVD_MAP_PACKAGE_VERSION="1.4.0-rc2"
make fetch REGION=china/guangxi YYYYMMDD=20260818
make release REGION=china/guangxi YYYYMMDD=20260818
# ${WORKDIR}/china-guangxi-20260818/outputs/china-guangxi-20260818.base.pmtiles  ✓
# ${WORKDIR}/china-guangxi-20260818/outputs/china-guangxi-20260818.base.manifest.json
#   .huavd_record.package_version = "1.4.0-rc2"
# ${WORKDIR}/china-guangxi-20260818/outputs/china-guangxi-20260818.bundle.zip  (含 install.json)
#   .offline_maps[0]."package-version" = "1.4.0-rc2"
#   .bundles[0]."bundle-version"     = "1.4.0-rc2"
```

per-role 不一致时分别覆盖（`per-role env` 永远优先于 `全局 env`）：

```bash
export HUAVD_MAP_PACKAGE_VERSION_BASE="1.4.0-base"
export HUAVD_MAP_PACKAGE_VERSION_BUILDING="1.4.0-bld"
# HUAVD_MAP_PACKAGE_VERSION_DEM 不设 -> dem 仍走 region 模板
make release REGION=china/guangxi YYYYMMDD=20260818 ROLE=both
# base      package-version = "1.4.0-base"
# building  package-version = "1.4.0-bld"
# dem       package-version = 走全局默认 ("20260818-dem")
```

发布构建后用 `verify --strict` 一次性确认所有产物落盘正确：

```bash
make verify REGION=china/guangxi YYYYMMDD=20260818 ROLE=all --strict
# OK   manifest package_version (role=base)
# OK   manifest package_version (role=building)
# OK   manifest package_version (role=dem)
# OK   install.json offline_maps package-version
# OK   install.json bundles bundle-version
```

构建机或 CI runner 残留的 `HUAVD_MAP_PACKAGE_VERSION*` 会静默吃掉 region 模板
改动，发布 job 的第一步应显式 `unset`。env 包含空格或其它非法字符（不在
`[A-Za-z0-9._+-]+`）会 `die` 退出，不会写出一份半成品 manifest。

### CI 场景

CI 可以在 job 环境中声明变量，然后使用相同的短命令：

```bash
export REGION=china/guangxi
export YYYYMMDD=20260818
export WORKDIR=/tmp/huavd-map-build-ci
export ROLE=base

devbox run doctor
make fetch
make release
```

如果 CI 环境不能访问 Geofabrik，就不要执行 `make fetch`；应先把 PBF 作为 CI artifact 或缓存放入当前 `WORKDIR`，或通过 `INPUT` 指向已有文件：

```bash
export REGION=china/guangxi
export YYYYMMDD=20260818
export WORKDIR=/tmp/huavd-map-build-ci
export ROLE=base
export INPUT=/cache/maps/guangxi-latest.osm.pbf

devbox run doctor
make release
```

现有的命令行变量覆盖方式仍然兼容，适合临时切换参数；推荐文档中的主流程使用环境变量继承模式。

### Release pipeline: 锁版本号

CI 同一个 region 既有日常构建（每日走 `regions.yaml` 模板），又有发布构建（需要锁定 `1.4.0-rc2` 这类与月份无关的版本）。`huavd-map-build` 的 manifest、install.json、bundle 都通过同一套 `region_package_version()` 解析器，详见 [package-version 解析规则](#package-version-解析规则)。

#### 日常构建 job

显式 `unset` 是为了避免上游 job 残留 `HUAVD_MAP_PACKAGE_VERSION*` 影响本次构建：

```bash
# 入口：显式清空覆盖
unset HUAVD_MAP_PACKAGE_VERSION \
      HUAVD_MAP_PACKAGE_VERSION_BASE \
      HUAVD_MAP_PACKAGE_VERSION_BUILDING \
      HUAVD_MAP_PACKAGE_VERSION_DEM

export REGION=china/guangxi
export YYYYMMDD=20260818

make fetch
make release ROLE=both
make verify ROLE=all --strict

# release 产物在 ${WORKDIR}/${SESSION}/outputs/ 下：
#   china-guangxi-20260818.base.pmtiles
#   china-guangxi-20260818.base.manifest.json  .huavd_record.package_version = "20260818.base"
#   china-guangxi-20260818.building.pmtiles
#   china-guangxi-20260818.building.manifest.json  .huavd_record.package_version = "20260818-building"
#   china-guangxi-20260818.bundle.zip  install.json .offline_maps[0]."package-version" = "20260818.base"
```

#### 发布构建 job

```bash
unset HUAVD_MAP_PACKAGE_VERSION \
      HUAVD_MAP_PACKAGE_VERSION_BASE \
      HUAVD_MAP_PACKAGE_VERSION_BUILDING \
      HUAVD_MAP_PACKAGE_VERSION_DEM

export REGION=china/guangxi
export YYYYMMDD=20260818
# 发布锁版本，覆盖 base / building，dem 不动
export HUAVD_MAP_PACKAGE_VERSION_BASE="1.4.0-base"
export HUAVD_MAP_PACKAGE_VERSION_BUILDING="1.4.0-bld"

make fetch
make release ROLE=both
make verify ROLE=all --strict
# OK   manifest package_version (role=base)         => "1.4.0-base"
# OK   manifest package_version (role=building)     => "1.4.0-bld"
# OK   manifest package_version (role=dem)          => 走全局默认 ("20260818-dem")
# OK   install.json offline_maps package-version
# OK   install.json bundles bundle-version
```

如果不区分 role，所有产物都用同一个版本号：

```bash
unset HUAVD_MAP_PACKAGE_VERSION_BASE \
      HUAVD_MAP_PACKAGE_VERSION_BUILDING \
      HUAVD_MAP_PACKAGE_VERSION_DEM
export HUAVD_MAP_PACKAGE_VERSION="1.4.0-rc2"
make release REGION=china/guangxi YYYYMMDD=20260818 ROLE=both
# 所有 manifest/install.json 的 package-version 都是 "1.4.0-rc2"
```

> 构建机或 runner 上一次构建残留的 `HUAVD_MAP_PACKAGE_VERSION*` 会静默吃掉
> region 模板修改，所以每个 job 入口都先 `unset`，避免排查“明明改了 regions.yaml
> 怎么产物没变”的怪问题。
