---
layout: home

hero:
  name: huavd-map-build
  text: HUAVD 离线 PMTiles 构建管线
  tagline: 从 Geofabrik OSM PBF 生成 HUAVD 可离线分发的 PMTiles、manifest 和 bundle
  actions:
    - theme: brand
      text: 安装与使用
      link: /manual/
    - theme: alt
      text: 开发入口
      link: /development/

features:
  - title: OSM 数据转换
    details: 下载 Geofabrik PBF，按 layer 过滤 tags，导出 GeoJSONSeq，并归一化字段。
  - title: PMTiles 产出
    details: 使用 tippecanoe 生成 base/building 角色 PMTiles，写入 metadata 和校验 hash。
  - title: HUAVD 元数据
    details: 生成 manifest、attribution 和 bundle，记录 source_id、版本、区域、工具链与许可证。
  - title: 可复现脚本
    details: 以 devbox、Makefile 和 Bash 脚本作为稳定入口，避免 devbox shell 自动执行重型构建。
---

## 文档定位

Native 图片渲染工具的源码迁出、构建与 Python 接入见 [操作手册](./operations/native-renderer-build.md)。

本目录是 `huavd-map-build` 的项目内文档，用于说明当前代码的构建入口、目录职责、配置关系、运行方式和常见故障。

产品契约、跨服务边界和长期演进仍以 HUAVD 总体文档为真值源。本项目文档只解释当前构建工具链如何把 OSM 数据加工成离线地图产物。

## 构建边界

`huavd-map-build` 负责：

- 从 Geofabrik 下载或接收 `.osm.pbf` 输入。
- 按 `config/layers.yaml` 和 `config/export-config/*.json` 生成 GeoJSONSeq layer。
- 按 `config/tippecanoe.yaml` 生成 base/building PMTiles。
- 写入 PMTiles metadata、manifest、attribution 和 SHA512 sidecar。
- 将单次 build session 的产物打包为 tar/zip bundle。
- 通过固定 RouteWeft 工具从原始城市 PBF 生成、验证并打包独立路由审核数据集；与地图分开构建，不提供联合安装。

不负责：

- 不提供 HTTP Range 服务。
- 不承载 Web UI 或地图渲染 UI。
- 不直接管理 HUAVD 设备端 SQLite 地图索引。
- 不自动下载 `config/regions/*.poly`。

## 关键入口

| 主题 | 页面 |
| :--- | :--- |
| 从零安装和完整使用流程 | [安装与使用](/manual/) |
| 同源地图与导航路网的完整操作流程 | [地图与路网构建](/manual/map-and-routing) |
| 开发命令与环境 | [开发入口](/development/) |
| 构建阶段与文件流 | [构建管线](/pipeline/) |
| 配置文件职责 | [配置索引](/configuration/) |
| 运行、验证与故障处理 | [运行与故障处理](/operations/) |
| 外部工具与契约 | [契约与外部工具](/references/) |

## 快速启动文档

```bash
pnpm dev
```

默认访问地址：

```text
http://127.0.0.1:22592/
```
