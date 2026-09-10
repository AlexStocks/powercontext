---
title: 安装和运行
description: 选择安装版本和存储，生成配置，并启动或更新 PowerContext。
---

# 安装和运行

首次使用请按[快速开始](quickstart.md)完成“安装 → 向导 → 启动 → 接入 Agent → 记忆验收”。
本页补充安装角色、存储与更新，命令使用 `oceanbase/powercontext` 的默认安装来源。

## 平台与准备

| 项目 | 要求 |
| --- | --- |
| PowerContext | Python 3.11+、Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) |
| macOS、Linux | 支持 |
| Windows | `experimental`；本文命令使用 Bash，不能直接粘贴到 PowerShell |
| 嵌入式 seekdb | Linux 或 macOS，且当前 Python/架构有兼容的 `pylibseekdb` wheel |
| Agent | 在运行 Agent 的机器上安装对应 CLI |
| 完整记忆 | 可用的 Generation 和 Embedding 模型 API |

## 选择版本

本页的配置向导体验来自指定开发分支，不能假定任意已发布包都包含相同向导。
安装工具和 Agent 插件时保持仓库及 ref 一致：

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
powercontext --version
```

`uv tool` 使用隔离环境，不会在当前目录创建源码仓库。`--force` 用于刷新该分支当前对应的安装。
需要固定验收版本时，可将安装命令中的 ref 和后续 setup 的 `--ref` 同时替换为同一个已存在的 tag；也可使用同一份源码 checkout。
不要只把插件改成另一个仓库的 `master`。

## 使用镜像重试依赖下载

如果 GitHub 源码已拉取成功，但从 PyPI 下载 Python 依赖很慢，或出现网络/TLS 错误，可用阿里云 HTTPS 镜像重试本次安装：

```bash
uv tool install --force --default-index https://mirrors.aliyun.com/pypi/simple "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
```

这个参数只对本条命令生效，不修改全局 uv 配置；它覆盖 Python 依赖（包括构建依赖）的下载源，不代理 GitHub 源码访问。
如果失败发生在拉取 GitHub 源码阶段，需要另行解决 GitHub 的连接问题。镜像使用 HTTPS，无需增加 `--trusted-host`
或关闭证书验证。安装成功后，继续下面的配置向导步骤。

## 生成配置与选择存储

在专用目录运行向导：

```bash
mkdir -p ~/powercontext-demo
cd ~/powercontext-demo
powercontext config init --language zh --output .env
```

不传 `--language` 时，向导先根据系统语言选择中英文，无法判断或不支持时使用英语；首屏可以切换。
`--template` 生成无模型基础模板，跳过交互；首次体验完整记忆不要加它。

向导按存储、使用场景、能力、Dashboard/网络、模型、后台周期和 Agent 顺序收集信息。
已有环境文件会进入复用或重新确认流程，覆盖时保留备份。它不会迁移旧数据库，也不会从一个 OceanBase 连接
自动恢复所有模型凭据和部署设置；请保留原环境文件和真实数据路径。检查已有 SQLite 元数据不等于验证全部服务可用。

| 存储选择 | 使用方式 |
| --- | --- |
| SQLite | 本地文件，无需额外数据库服务，适合首次验收 |
| 嵌入式 seekdb | 本机运行；向导可增量安装缺失的 seekdb 依赖 |
| OceanBase | 提供已有服务的连接参数；启动后检查网络、认证与数据库就绪状态 |
| 已有 PowerContext Server | 只生成客户端连接配置，不在本机另建 Server |

### seekdb 依赖安装

选择 seekdb 后，向导会检查依赖，并在征得同意后读取当前安装版本声明的依赖约束进行增量安装。
下载在后台进行，你可以继续回答其余问题；保存时若仍未完成，会直接显示活动进度并等待，不显示虚构的下载百分比。

显式设置的 `UV_DEFAULT_INDEX` 或 `UV_INDEX_URL` 优先。没有这两项覆盖时，中国时区直接使用
[阿里云 PyPI 镜像](https://mirrors.aliyun.com/pypi/simple/)；其他时区先用默认索引，失败后回退阿里云。
普通安装失败会输出一条可复制的增量安装命令；没有兼容 wheel 时应换用 SQLite/OceanBase 或受支持的 Python/平台。

也可以在首次安装时带上依赖：

```bash
uv tool install --force "powercontext[cli,server,seekdb] @ git+https://github.com/oceanbase/powercontext.git@master"
```

seekdb 使用 `POWERCONTEXT_SERVER_DATABASE_PATH` 指定本地目录，不接受 SQLite/SQLAlchemy 的
`POWERCONTEXT_SERVER_DATABASE_URL`。从 SQLite 改为 seekdb 时，不能让旧 URL 留在启动进程的环境中；
选择新后端不会自动迁移原有记忆。

## 启动与检查

```bash
powercontext config validate --env-file .env
powercontext server run --env-file .env
```

`server run` 是前台服务；按 `Ctrl-C` 正常退出。在另一个终端加载客户端文件后检查：

```bash
set -a
. ./.env
set +a
powercontext doctor
powercontext ready
powercontext capabilities
```

当前目录的 `.env` 会由 `server run` 自动读取，也可显式指定 `--env-file`，或用 `--no-env-file` 禁用。
进程中已导出的同名变量优先于文件；改了文件却没生效时检查旧终端环境。服务管理器应使用明确的绝对文件路径，
见[部署 Server](../operate/deploy-server.md)。

不带模型配置的最小 Server 也可以运行：默认 SQLite、`127.0.0.1:8000`、MCP `/mcp`，Dashboard 关闭。
它支持显式 Memory 写入与读取，但普通 Source 不会自动变成 Topic Memory。完整体验请使用向导生成的配置。

## Agent 安装与配置边界

在运行 Agent 的机器上执行对应命令，且先加载共享的 `.env`：

```bash
powercontext setup codex
powercontext doctor codex
```

Claude Code 使用：

```bash
powercontext setup claude-code --server-url "$POWERCONTEXT_CLAUDE_SERVER_URL"
powercontext doctor claude-code
```

向导生成客户端文件，setup 安装插件，Server 执行持久化与模型处理；三者需要分别完成。
MCP、Hook、浏览器应使用同一个服务，Scope 必须使用 Server 实际返回的 ID。
完整接线见[快速开始](quickstart.md)、[Codex](../integrations/codex.md)和[Claude Code](../integrations/claude-code.md)。

## 更新或重新安装

重新运行上面的同源安装命令，更新匹配的 Agent 插件，再重启 Server 和 Agent。
使用个人服务时，按[服务安装步骤](../operate/deploy-server.md#运行持久个人-server)重新注册更新后的程序和环境文件。

工具升级不会主动删除数据，但改变 `POWERCONTEXT_HOME`、数据库 URL 或数据库目录，会让服务打开另一份存储。
更新前保留环境文件和数据库备份；不要为了排错删除 SQLite 文件。

## 在 Python 应用中使用

`uv tool` 的隔离环境不会给另一 Python 项目提供可导入的 SDK。应用需要 Client SDK 时，在应用目录执行：

```bash
uv add "powercontext[client] @ git+https://github.com/oceanbase/powercontext.git@master"
```

进程内组合使用 `builtin`，独立服务使用 `server`，客户端 SDK 使用 `client`，命令行使用 `cli`。
