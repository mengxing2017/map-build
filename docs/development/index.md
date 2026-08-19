# 开发入口

## 项目结构

`huavd-map-build` 是 Bash 脚本驱动的离线地图构建项目。主要路径：

| 路径 | 职责 |
| :--- | :--- |
| `Makefile` | 稳定命令入口，封装 setup、doctor、fetch、build、verify、pack、clean |
| `devbox.json` | 开发工具声明和 devbox script 入口 |
| `scripts/lib/common.sh` | 通用路径、session、日志、参数解析、版本检测 |
| `scripts/lib/config.sh` | YAML 配置加载、region/layer/tippecanoe 解析 |
| `scripts/lib/pmtiles.sh` | PMTiles header 与 metadata 读取 helper |
| `scripts/setup-tools.sh` | osmium、tippecanoe、pmtiles 安装 |
| `config/` | region、layer、tippecanoe 和 osmium export 配置 |
| `docs/` | 当前 VitePress 文档模块 |

## 常用命令

```bash
devbox shell
devbox run setup
devbox run doctor
```

Makefile 入口：

```bash
make setup
make doctor
make fetch REGION=china/guangxi
make build REGION=china/guangxi YYYYMMDD=20260818 ROLE=both
make verify REGION=china/guangxi YYYYMMDD=20260818 ROLE=both
make pack SESSION=china-guangxi-20260818 ROLE=both FORMAT=both
```

文档入口：

```bash
pnpm dev
pnpm run docs:build
pnpm run docs:preview
```

## 开发约束

- `devbox shell` 只设置环境和 `PATH`，不得放入自动下载或源码编译逻辑。
- 重型安装放在 `devbox run setup` 或 `make setup`。
- Bash 脚本保持 `set -euo pipefail`，新增失败路径要给出明确错误。
- 不用 `|| true` 静默吞掉安装、构建或验证失败。
- 不把 PBF、PMTiles、bundle、cache、`node_modules`、`.vitepress/dist` 放入仓库。

## 最小验证

```bash
bash -n scripts/*.sh scripts/lib/*.sh
jq . devbox.json >/dev/null
devbox run doctor
pnpm run docs:build
```
