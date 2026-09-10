---
title: Install and run
description: Choose a version and storage, generate configuration, and start or update PowerContext.
---

# Install and run

For the complete installation → wizard → startup → Agent connection → memory check, follow [Quick Start](quickstart.md).
This page covers installation roles, storage, and updates. Commands use the default installation from
`oceanbase/powercontext`.

## Platforms and prerequisites

| Item | Requirement |
| --- | --- |
| PowerContext | Python 3.11+, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/) |
| macOS and Linux | Supported |
| Windows | `experimental`; these examples use Bash and cannot be pasted directly into PowerShell |
| Embedded seekdb | Linux or macOS with a compatible `pylibseekdb` wheel for the Python version and architecture |
| Agent | Install its CLI on the machine where the Agent runs |
| Full memory | Working Generation and Embedding model APIs |

## Choose a version

The guided experience on this site is provided by the current `oceanbase/powercontext` installation. Keep the Server
tool and Agent plugins on the same installed PowerContext version:

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
powercontext --version
```

`uv tool` installs an isolated environment without creating a source checkout in your current directory.
`--force` refreshes the installed tool. To pin an acceptance run, install a specific existing release or use the same
source checkout for the Server and plugin. Do not switch only the plugin to another repository or version.

## Retry dependency downloads with a mirror

If the GitHub checkout succeeds but downloading Python dependencies from PyPI is slow or fails with a network/TLS error,
retry this installation using the Aliyun HTTPS index:

```bash
uv tool install --force --default-index https://mirrors.aliyun.com/pypi/simple "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
```

This selects the index for this command only; it does not change global uv settings. It applies to Python dependencies,
including build dependencies, not the GitHub source checkout. If GitHub itself is unreachable, configure working GitHub
access separately. The mirror uses HTTPS, so this command does not need `--trusted-host` or disabled certificate verification.
After installation succeeds, continue with the configuration wizard below.

## Generate configuration and select storage

Run the wizard in a dedicated directory:

```bash
mkdir -p ~/powercontext-demo
cd ~/powercontext-demo
powercontext config init --language en --output .env
```

Without `--language`, the wizard detects Chinese or English from the system and falls back to English when unknown
or unsupported; you can switch at the first prompt. `--template` writes a basic, model-free template without the
interactive flow. Omit it for the full-memory walkthrough.

The wizard asks about storage, usage scenario, capabilities, Dashboard/network, models, background schedules,
and Agents. Existing environment files can be reused or reviewed, with backups when overwritten.
It does not migrate databases or restore every model credential and deployment setting from an OceanBase connection.
Keep the original environment file and data path. Inspecting local SQLite metadata does not validate every dependency.

| Storage option | Behavior |
| --- | --- |
| SQLite | Local file without another database service; suitable for a first check |
| Embedded seekdb | Local instance; the wizard can install its missing dependency incrementally |
| OceanBase | Supply an existing service's connection details; check networking, authentication, and readiness after startup |
| Existing PowerContext Server | Generate client connection settings without creating another local Server |

### seekdb dependency installation

After you select seekdb, the wizard checks its dependency and asks for permission to install missing packages.
It reads the constraints declared by the installed PowerContext version and installs incrementally in the background.
You can answer the remaining questions during the download. If it is unfinished when you save, the wizard waits with
an activity indicator, without inventing a download percentage.

Explicit `UV_DEFAULT_INDEX` or `UV_INDEX_URL` settings take precedence. Without those overrides, a Chinese timezone
selects the [Aliyun PyPI mirror](https://mirrors.aliyun.com/pypi/simple/) immediately; other timezones use the default
index first and fall back to Aliyun after failure. Ordinary failures produce a copyable incremental installation
command. If no compatible wheel exists, use SQLite/OceanBase or a supported Python/platform combination.

You can also include the dependency during the initial installation:

```bash
uv tool install --force "powercontext[cli,server,seekdb] @ git+https://github.com/oceanbase/powercontext.git@master"
```

seekdb uses a local `POWERCONTEXT_SERVER_DATABASE_PATH`, not a SQLite/SQLAlchemy
`POWERCONTEXT_SERVER_DATABASE_URL`. When switching from SQLite, remove the old URL from the starting process's
environment. Selecting another backend does not migrate existing memories.

## Start and check

```bash
powercontext config validate --env-file .env
powercontext server run --env-file .env
```

`server run` stays in the foreground; stop it with `Ctrl-C`. Load the client file in another terminal and check:

```bash
set -a
. ./.env
set +a
powercontext doctor
powercontext ready
powercontext capabilities
```

`server run` automatically reads `.env` in its current directory. Use `--env-file` to choose a file explicitly,
or `--no-env-file` to disable loading. Exported process variables override file values; check inherited variables
if editing a file appears to have no effect. Service managers should use an explicit absolute path;
see [Deploy the Server](../operate/deploy-server.md).

A minimal Server also runs without model configuration: SQLite, `127.0.0.1:8000`, MCP at `/mcp`, and Dashboard disabled.
It supports explicit Memory writes and reads, but ordinary Sources do not automatically become Topic Memory.
Use the wizard's configuration for the full experience.

## Agent installation and connection

On the machine running the Agent, first load the shared `.env`, then install the corresponding plugin:

```bash
powercontext setup codex
powercontext doctor codex
```

For Claude Code:

```bash
powercontext setup claude-code --server-url "$POWERCONTEXT_CLAUDE_SERVER_URL"
powercontext doctor claude-code
```

The wizard writes connection files, setup installs plugins, and the Server performs persistence and model processing.
Complete each step. MCP, Hooks, and the browser must reach the same service; Scope settings use IDs actually returned
by the Server. Follow [Quick Start](quickstart.md), [Codex](../integrations/codex.md), or [Claude Code](../integrations/claude-code.md).

## Update or reinstall

Repeat the matching installation and plugin commands, then restart the Server and Agent. For a personal service,
repeat the [service installation](../operate/deploy-server.md#run-a-persistent-personal-server) to register the updated
program and environment file.

Updating the tool does not intentionally remove data, but changing `POWERCONTEXT_HOME`, the database URL, or the database
directory opens different storage. Keep configuration and database backups before updates. Do not delete a SQLite file
as a troubleshooting shortcut.

## Install a Python role

An isolated `uv tool` environment does not expose an importable SDK to another Python project.
Install the Client SDK in that project's environment:

```bash
uv add "powercontext[client] @ git+https://github.com/oceanbase/powercontext.git@master"
```

Use `builtin` for in-process composition, `server` for a standalone service, `client` for the SDK, and `cli` for commands.
