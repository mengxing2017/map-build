# 生成图片地图 ZIP

在仓库根目录操作。支持 Linux x86_64、项目 devbox 和 Vulkan 软件渲染。
图片是 OSM 底图，不是卫星影像；文字与图标由客户端叠加。

## 1. 安装和检查（首次使用）

```bash
devbox shell
make setup
make doctor
```

团队须先准备匹配项目锁的 Native 工具安装或经过目标环境验证的运行工具包。
`make setup` 不会自动下载未经配置的 Native 包，也不会自动编译大型 C++ 工程。
若提示 Native 来源未配置，由维护者按下方“工具准备”处理一次。
缺字体或 glyph 工具时先修复安装；不能用空资源继续打包。

## 2. 选择地区与日期

```bash
export REGION=china/guangxi/guilin/qixing
export YYYYMMDD=20261003
```

填写自己数据对应的已配置地区和日期。
默认工作目录为 `/tmp/huavd-map-build`，数据需要持久保存时先设置自己的 `WORKDIR`。
输入默认按地区配置读取 `WORKDIR/mirror`；不会自动下载 PBF。
七星区须使用提取好的七星区输入，不能直接替换成广西全域 PBF。

## 3. 构建和打包

```bash
make build ROLE=base_raster
make pack ROLE=base_raster FORMAT=zip
```

使用其他本地 PBF 时，在第一条命令后添加 `INPUT=./input/qixing.osm.pbf`，
路径相对仓库根目录；文件须与选择地区对应。
任一步失败就停止，按错误提示修复后重跑，不交付残留旧 ZIP。
已有完整成果重建时须显式加 `FORCE=1`；它会重建当前会话的矢量成果。

build 自动准备底图、字体资源、sprite、样式，使用 Native 生成 WebP PMTiles，
校验并发布。成功结果含 `published: true` 和 `finalization.status: passed`。
结果的 `inspection.preview` 是离线图片查看页，视觉与客户端验收状态单独标注。
pack 结果打印 `archives.zip_path`、`zip_bytes`、`zip_sha512`，并验证 ZIP CRC。
输出位于 `WORKDIR/outputs/{地区名}-{日期}.bundle.zip`，同时生成 `.sha512`。

已具备同会话完整 base、glyph、sprite、样式、manifest 和归因，仅补图片时：

```bash
make build ROLE=raster_bake
make pack ROLE=base_raster FORMAT=zip
```

需要客户端导入 ZIP 时再执行：

```bash
make prepare-import ROLE=base_raster IMPORT_FORMAT=zip
```

## 工具准备（维护者，仅首次或升级）

已有安装目录含 `bin/huavd-native-render`、build-info、source-lock、binary.sha256 和 licenses。
设置 `HUAVD_NATIVE_INSTALLATION` 为其实际目录，执行 `make setup`。
安装器校验源码锁、二进制摘要和真实渲染自检，再创建固定入口。
后续使用者不需要填写摘要路径。原目录是运行依赖，登记后不要移动或删除。

工具默认放在 `HUAVD_MAP_BUILD_HOME/tools/maplibre-native`，
`HUAVD_MAP_BUILD_HOME` 默认 `/tmp/huavd-map-build`；
可以一次性设置 `HUAVD_NATIVE_TOOLS` 到持久工具目录。
自定义工具目录时在构建机环境中保留该设置，独立于地图任务的 WORKDIR。

导入运行包时设置 `HUAVD_NATIVE_PACKAGE` 和可信发布方提供的
`HUAVD_NATIVE_PACKAGE_SHA256`，再执行 `make setup`。
tar 包根目录直接包含上述安装文件；不接受链接、特殊文件或路径穿越。
运行包须匹配目标平台及动态库，先在目标环境测试，不能只复制一个 executable。
当前没有项目默认发布包；维护者负责提供本地包或完整安装。
对外分发前须补齐 core 和第三方 notices，现有源码安装器只自动收集 wrapper 许可证。

源码重建使用 `scripts/setup-native-renderer.sh --help` 列出的参数，
需要匹配 `config/native-renderer.lock.json` 的外部源码或归档。
成功后自动创建同样的固定入口；大静态库留在外部构建目录。
这属于维护工作，不是日常生成地图的前提操作。

## 常见问题

| 提示 | 处理 |
| --- | --- |
| Native missing / source lock mismatch | 由维护者准备匹配安装，重跑 setup、doctor |
| Vulkan 或动态库错误 | 重新进入 devbox，检查工具包与目标环境是否匹配 |
| 输入不存在 | 检查地区、WORKDIR 和 INPUT；本地提取地区先准备对应 PBF |
| 字体或 build-glyphs 缺失 | 准备配置字体并运行 setup，不创建空资源替代 |
| 超过瓦片上限 | 检查地区和层级配置，先核算预算，不直接取消限制 |
| 发布失败 | 查看 finalization 失败项，补齐资源后重跑 |

默认引擎和并发来自 `config/bake.yaml`，区域可覆盖。
小范围排障使用既有 `make raster-estimate` 和 `BAKE_BBOX/BAKE_MIN_ZOOM/BAKE_MAX_ZOOM/BAKE_MAX_TILES`。
显式使用旧引擎可设置 `BAKE_RENDERER_ENGINE=mbgl-renderer`，
其工具安装需维护者启用 `INSTALL_LEGACY_RENDERER=1`。
切换工具、样式、输入或瓦片计划后缓存可能失效；不要在运行中删除缓存。
