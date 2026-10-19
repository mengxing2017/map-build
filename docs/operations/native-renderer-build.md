# 生成图片地图 ZIP

在仓库根目录操作。支持 Linux x86_64、项目 devbox 和 Vulkan 软件渲染。
图片是 OSM 底图，不是卫星影像；文字与图标由客户端叠加。

## 1. 安装和检查（首次使用）

```bash
devbox shell
make setup
make doctor
```

`make setup` 优先验证并复用已有安装；没有可用安装时，自动从
`config/native-renderer.lock.json` 指定的 wrapper/core 仓库获取锁定提交，
初始化 core 子模块，编译 C++/Rust 渲染器并执行真实自检，通过后发布固定入口。
无需预先填写 HUAVD_NATIVE_INSTALLATION 或运行包路径。首次安装需要联网、较多磁盘空间和编译时间；
下载只发生在显式 setup，进入 devbox shell 或执行 doctor 不会触发源码构建。
源码构建采用上游非 amalgam 链接模式，链接 Devbox 提供的依赖库，
不要求 PNG、ICU、OpenSSL 等依赖的静态归档，也不需要安装 armerge。
构建显式关闭 CMake 的静态合并选项，重试时会覆盖旧缓存中的 ON。
Devbox 同时安装 glslang 的库与开发输出，以及 SPIRV-Tools 的 lib/dev 输出；
只有命令行工具不足以完成 Vulkan 渲染器链接。更新配置后执行 `devbox install`。
更新项目后先重新进入 devbox 环境；离线模式要求对应工具及 Cargo 源码缓存已齐备。
缺字体或 glyph 工具时先修复安装；不能用空资源继续打包。

## 2. 选择地区与日期

```bash
export REGION=china/guangxi
export YYYYMMDD=20261003
```

填写自己数据对应的已配置地区和日期。
默认工作目录为 `/tmp/huavd-map-build`，数据需要持久保存时先设置自己的 `WORKDIR`。
输入默认按地区配置读取 `WORKDIR/mirror`；不会自动下载 PBF。

## 3. 构建和打包

```bash
make build ROLE=base_raster
make pack ROLE=base_raster FORMAT=zip
```

使用其他本地 PBF 时，在第一条命令后添加 `INPUT=./input/guangxi.osm.pbf`，
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

## 工具来源与缓存

已有安装目录含 `bin/huavd-native-render`、build-info、source-lock、binary.sha256 和 licenses。
设置 `HUAVD_NATIVE_INSTALLATION` 为其实际目录，执行 `make setup`。
安装器校验源码锁、二进制摘要和真实渲染自检，再创建固定入口。
后续使用者不需要填写摘要路径。原目录是运行依赖，登记后不要移动或删除。

工具默认放在实际 `WORKDIR/tools/maplibre-native`；未设置 WORKDIR 时使用
`HUAVD_MAP_BUILD_HOME`，两者均未设置时使用 `/tmp/huavd-map-build`；
可以一次性设置 `HUAVD_NATIVE_TOOLS` 到持久工具目录。
自定义工具目录时在构建机环境中保留该设置，独立于地图任务的 WORKDIR。

导入运行包时设置 `HUAVD_NATIVE_PACKAGE` 和可信发布方提供的
`HUAVD_NATIVE_PACKAGE_SHA256`，再执行 `make setup`。
tar 包根目录直接包含上述安装文件；不接受链接、特殊文件或路径穿越。
运行包须匹配目标平台及动态库，先在目标环境测试，不能只复制一个 executable。
当前没有项目默认发布包；未指定本地来源时，自动采用锁定源码构建。
对外分发前须补齐 core 和第三方 notices，现有源码安装器只自动收集 wrapper 许可证。

源码重建也可以直接执行：

```bash
make setup-native-renderer NATIVE_RENDERER_SETUP_ARGS=--online
```

未提供 core 时，--online 自动获取锁定 core 和 wrapper 仓库。源码缓存位于
`${WORKDIR}/tools/native-build`，其中 core 按提交隔离，下载失败后可重试复用缓存；
缓存存在未记录修改或提交不匹配时拒绝覆盖。默认单次源码 fetch 超时 300 秒，
可设置 NATIVE_FETCH_TIMEOUT_SECONDS；子模块初始化超时默认 1800 秒，可设置
NATIVE_SUBMODULE_TIMEOUT_SECONDS。构建并发默认 2，可设置 CMAKE_BUILD_PARALLEL_LEVEL。

所有耗时阶段均输出 START、RUNNING、DONE 或 FAILED 日志，包含 UTC 时间、阶段、PID 和已耗时长。
默认每 10 秒输出一次 RUNNING，即使 Git 正在接收/解包、Cargo 暂时没有输出也会持续报告。
可通过 `NATIVE_PROGRESS_INTERVAL_SECONDS` 调整为正数秒，例如：

```bash
NATIVE_PROGRESS_INTERVAL_SECONDS=5 make setup
```

原命令输出和失败退出码保持不变；取消任务会向对应命令进程组转发信号并清理子进程。
心跳表示进程尚未结束，不表示下载字节数、编译完成百分比或预计剩余时间。
高级离线构建仍可通过脚本的 --wrapper-source、--core-source 或 --amalgam/--headers
提供匹配锁定版本的本地源码和归档。自定义 HUAVD_NATIVE_TOOLS 时，自动构建安装到该目录。
成功后自动创建同样的固定入口；大静态库留在外部构建目录。
后续 setup 会优先复用已验证安装，不需要重复构建。

## 常见问题

| 提示 | 处理 |
| --- | --- |
| Native missing | 运行 make setup，自动获取锁定源码并构建 |
| Source lock mismatch | 检查显式指定的安装/包，修正来源；不覆盖不匹配的已有安装 |
| Git 下载超时或依赖获取失败 | 检查网络或镜像后重跑 setup；保留源码缓存 |
| Vulkan 或动态库错误 | 重新进入 devbox，检查工具包与目标环境是否匹配 |
| 输入不存在 | 检查已配置地区、WORKDIR 和 INPUT，准备对应 PBF |
| 字体或 build-glyphs 缺失 | 准备配置字体并运行 setup，不创建空资源替代 |
| 超过瓦片上限 | 检查地区和层级配置，先核算预算，不直接取消限制 |
| 发布失败 | 查看 finalization 失败项，补齐资源后重跑 |

默认引擎和并发来自 `config/bake.yaml`，区域可覆盖。
小范围排障使用既有 `make raster-estimate` 和 `BAKE_BBOX/BAKE_MIN_ZOOM/BAKE_MAX_ZOOM/BAKE_MAX_TILES`。
显式使用旧引擎可设置 `BAKE_RENDERER_ENGINE=mbgl-renderer`，
其工具安装需维护者启用 `INSTALL_LEGACY_RENDERER=1`。
切换工具、样式、输入或瓦片计划后缓存可能失效；不要在运行中删除缓存。
