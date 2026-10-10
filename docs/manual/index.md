# 安装与使用手册

本手册说明如何安装工具链，从 OSM PBF 构建离线地图，并准备分发包和 `huavd-map` 导入包。所有命令默认在仓库根目录执行。

默认 `WORKDIR=/tmp/huavd-map-build`，默认 `REGION=china/guangxi`。`YYYYMMDD` 使用 8 位构建日期；完整变量说明见 [命令与变量参考](./commands.md)。

## 首次使用

1. [环境安装与渲染资源](./installation.md)：安装工具链、执行 doctor、准备字体与 glyph/style。
2. [标准地图构建](./build.md)：声明构建上下文，下载或使用本地 PBF，构建并验证地图。
3. [产物、打包与导入](./delivery.md)：查找产物，生成 bundle 和导入包，了解运行时目录边界。

## 按任务查阅

| 任务 | 文档 |
| :--- | :--- |
| 查询 Makefile、脚本参数和环境变量 | [命令与变量参考](./commands.md) |
| 锁定发布版本、配置批处理 CI | [版本管理与 CI 发布](./versioning.md) |
| 构建 WebP 图片底图、估算瓦片数、检查缓存与发布状态 | [图片地图构建](./raster.md) |
| 使用授权高程源构建独立 DEM 资产 | [DEM 高程地图](./dem.md) |
| 查找 overview 和派生地图入口 | [命令与变量参考](./commands.md#派生地图入口) |
| 预览或构建本站文档 | [文档预览](./installation.md#文档预览) |

## 工作目录与交付

直接执行 `make build`、`make pack` 等命令时，产物在 `${WORKDIR}/outputs/`；`make release` 系列命令使用 `${WORKDIR}/${SESSION}/outputs/`。后续导入包准备应选择对应入口，详见 [产物、打包与导入](./delivery.md)。

构建输出目录与 `huavd-map` 运行时地图目录是不同的目录。构建工具负责生成交付物；接收端负责导入和激活。
