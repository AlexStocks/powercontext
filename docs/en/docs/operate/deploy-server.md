---
title: Deploy the Server
description: Run PowerContext with persistent data, health checks, authentication, and a safe network boundary.
---

# Deploy the Server

First install from the `master` branch of `oceanbase/powercontext` and generate configuration with
[Quick Start](../get-started/quickstart.md). This page covers persistent operation and remote access.
When Server and Agent run on different machines, install on each machine and keep the plugin repository and ref matched.

Windows support is `experimental`.

`powercontext server run` is a foreground process. On a personal macOS, Linux, or Windows workstation, PowerContext can register
that same Server runner with the native current-user service manager. Managed deployments should continue to use a
container platform or an administrator-owned service manager.

## Run a persistent personal Server

Install and start the optional current-user service:

```bash
powercontext service install --env-file /absolute/path/to/.env
powercontext service status
```

On Windows, the command asks whether to enable startup at the current user's next login when neither
`--start-on-login` nor `--no-start-on-login` is supplied; pressing Enter keeps login auto-start disabled. Use either
option for a non-interactive choice.

Replace the example with the absolute path to the wizard's `.env`. Stop a foreground Server on the same port with
`Ctrl-C` before installing the service. Use `service status` to confirm the registered service is actually running.

Linux uses `systemd --user` and writes logs to the user journal. macOS uses a per-user LaunchAgent, and Windows uses a current-user Task Scheduler task; both write stdout and stderr below the PowerContext user data directory. `service status` reports the exact log selector or path.

For an explicit Server configuration, protect the environment file before installing:

```bash
chmod 600 /path/to/powercontext.env
powercontext config validate --env-file /path/to/powercontext.env
powercontext service install --env-file /path/to/powercontext.env
```

On Windows, remove inherited access and grant the file only to the current user, `SYSTEM`, and local `Administrators` before validation, for example:

```powershell
icacls $env:USERPROFILE\powercontext.env /inheritance:r /grant:r "${env:USERNAME}:(F)" "SYSTEM:(F)" "Administrators:(F)"
```

The native definition stores only the absolute file path and non-content file identity metadata. On Windows this
includes the current user's owner SID, which is revalidated whenever the launcher starts. It does not copy
credentials or the caller's shell environment. Re-run `service install` after upgrading PowerContext or changing the
environment file. Remove the registration without deleting Server data or logs with:

```bash
powercontext service uninstall
```

## Choose the network boundary

The default Server listens on `127.0.0.1:8000` without authentication. This is suitable for clients on the same
machine. Do not change the listener to a non-loopback address while authentication is disabled.

For access from another machine:

1. enable bearer authentication;
2. keep the Server behind a TLS-terminating reverse proxy or private network boundary;
3. provide the token through a secret manager or protected process environment;
4. allow access to the data directory only for the Server operator.

The built-in command serves HTTP and has no TLS options. Terminate HTTPS outside PowerContext.

In “Custom listener address and client URL”, `0.0.0.0` means accept connections on all interfaces. It is not a browser
address and does not enable HTTPS. PowerContext clients permit plain HTTP only on loopback addresses, so a remote
`http://server:8000` is not a supported client URL. For a first remote check without a domain, certificate, or HTTPS
proxy, use SSH forwarding.

## Access from another computer with SSH

On the Server machine, select “Access from other devices” → “SSH port forwarding” in the wizard. Enter your actual
SSH host or alias and the client's forwarded port. The Server keeps listening on `127.0.0.1:8000`.
After starting it with the generated configuration, run the printed tunnel command on the client computer, for example:

```bash
ssh -N -L 18000:127.0.0.1:8000 user@server
```

Replace `user@server` with your normal SSH address or alias and keep this terminal running. Open
`http://127.0.0.1:18000/dashboard/home` in the client browser and sign in with the Server token.
SSH encrypts the tunnel; the HTTP connections use loopback at each endpoint.

An Agent on the Server machine uses `http://127.0.0.1:8000`; an Agent on the client computer uses
`http://127.0.0.1:18000`. The wizard asks which machine hosts the Agent. Securely transfer the corresponding
`.env` to that machine and load it. Check `POWERCONTEXT_CLIENT_SERVER_URL` and the Agent-specific URL. Copy it only
to a trusted machine because it contains the complete installation configuration. Codex's MCP URL must also match its Hook URL;
see [Codex connection steps](../integrations/codex.md).

If the local port is occupied, choose another port and update the browser/client URLs together. The tunnel stops
when SSH exits, while the remote Server continues running. Starting a Server inside remote tmux does not establish
port forwarding to your Mac.

## Use external HTTPS

With an existing Nginx, Caddy, gateway, or load balancer, choose “HTTPS reverse proxy” and enter its complete public URL,
such as `https://memory.example.com`. A proxy on the Server machine uses `http://127.0.0.1:8000` as its upstream;
a proxy on another machine needs the corresponding listener and network configuration.

Configure certificates, DNS, TLS, and forwarding in that external component; the wizard does not install them.
`POWERCONTEXT_SERVER_PUBLIC_URL=https://...` declares the external URL but does not add TLS to the built-in Server.
The proxy must support streaming `/mcp` connections, preserve `Authorization`, and forward the correct external host
and scheme for Dashboard sign-in checks. Verify the external `/health/ready`, Dashboard login, and MCP from the client,
not only the local Server port. Without an existing HTTPS service, use the complete SSH workflow above.

## Run from an installed tool

Install PowerContext as described in [Install and run](../get-started/install-and-run.md), then choose a persistent data directory:

```bash
export POWERCONTEXT_HOME=/srv/powercontext
powercontext server run
```

The process must be able to create and update this directory. The default SQLite database and scheduler state are
stored below it. Supply the same environment variables whenever your service manager restarts the process.

`server run` loads `.env` from its current directory when present. Managed deployments should export the variables,
configure them in the service manager or container platform, or pass one explicit file so startup does not depend on
the working directory:

```bash
powercontext config validate --env-file /etc/powercontext/powercontext.env
powercontext server run --env-file /etc/powercontext/powercontext.env
```

The successful installation summary prints the environment file actually used. If Bearer authentication is enabled,
read `POWERCONTEXT_SERVER_AUTH_TOKEN` from that file; the command never prints the token value. The basic model-free
template leaves authentication disabled. The wizard generates a token when Dashboard or authenticated access
requires one and no existing token is available.

The file may contain provider credentials or a bearer token, so restrict it to the Server operator. For `server run`,
process environment variables override same-named file values. `config init` opens a bilingual wizard: choose storage,
usage scenario, and capabilities, then configure Dashboard/access and only the necessary model connections.
It selects English or Chinese from the system language (`LC_ALL` before `LC_MESSAGES` before `LANG`, then system
preferences), with English fallback for an unknown or unsupported language. Change the language on the first screen
or pass `--language en` or `--language zh`; add `--template` to retain the basic model-free template.

The wizard writes configuration and follow-up instructions. It does not start or register services, migrate a
database, or probe remote storage and model endpoints. Existing local SQLite metadata can be inspected read-only.
After saving, perform the deployment checks below and, when enabled, the
[Memory extraction and vector search checks](../get-started/configure-models.md).

Whether the Server runs in the foreground, in Docker, or as a personal service, startup or installation output warns
that missing models may affect some artifact features and links to the
[configuration reference](configuration.md).
The notice is omitted when both generation and embedding models are configured.

## Run with Docker

Build the image from the repository root:

```bash
POWERCONTEXT_VERSION=$(uvx --from hatchling --with hatch-vcs hatchling version)
docker build \
  --file docker/Dockerfile \
  --build-arg "POWERCONTEXT_VERSION=${POWERCONTEXT_VERSION}" \
  --tag powercontext-server:local \
  .
```

Run it with a named volume and publish the port only on the host loopback interface:

```bash
docker run --rm \
  --name powercontext-server \
  --publish 127.0.0.1:8000:8000 \
  --volume powercontext-data:/data \
  powercontext-server:local
```

The image listens on `0.0.0.0:8000` inside the container, so the host-side address in `--publish` is important. The
named volume persists the SQLite database and scheduler state after the container stops.

## Enable authentication

Load a strong token from your secret manager into the Server process environment:

```bash
export POWERCONTEXT_SERVER_ACCESS_MODE=enforced
export POWERCONTEXT_SERVER_AUTH_TOKEN="$POWERCONTEXT_DEPLOYMENT_TOKEN"
powercontext server run
```

For Docker, pass the already-loaded variables without putting the token value in the command:

```bash
docker run --rm \
  --name powercontext-server \
  --publish 127.0.0.1:8000:8000 \
  --volume powercontext-data:/data \
  --env POWERCONTEXT_SERVER_ACCESS_MODE=enforced \
  --env POWERCONTEXT_SERVER_AUTH_TOKEN \
  powercontext-server:local
```

Clients then send `Authorization: Bearer <token>`. The liveness and readiness endpoints remain public so an
orchestrator can probe them. API, MCP, metrics, and `/openapi.json` require authentication. The `/docs` shell remains
public, but requests made from the interactive reference require authentication.

Personal or demonstration deployments can additionally set `POWERCONTEXT_SERVER_DASHBOARD_ENABLED=true` to expose
`/dashboard/home` on the same port. It requires the static Bearer configuration above; startup fails clearly without a
token. Browser sign-in uses the Server token, not a model API key. Credentials are stored in an HttpOnly,
SameSite=Strict Cookie restricted to `/dashboard`, for up to eight hours. HTTPS sets Secure. Reverse proxies must
preserve the external scheme and host for the sign-in same-origin check.

All holders of the static token share one administrator identity. The Dashboard does not support multi-user RBAC or
provide accounts, SSO, invitations, or grant management. Deployments injecting an Authentication Provider or
AccessControlService must disable the Dashboard; an incompatible enabled configuration is rejected at startup.
Disabling it does not affect team API or MCP access. For personal setup, see
[Install and run](../get-started/install-and-run.md).

## Check the deployment

Use liveness to determine whether the process can answer HTTP requests:

```bash
curl --fail http://127.0.0.1:8000/health/live
```

Use readiness before sending application traffic:

```bash
curl --fail http://127.0.0.1:8000/health/ready
```

Readiness returns HTTP 503 when a required runtime or database binding is unavailable. An optional inference provider
can make the response `degraded` with HTTP 200 while database-backed operations remain available.

After enabling authentication, verify a protected endpoint as well:

```bash
curl --fail \
  --header "Authorization: Bearer ${POWERCONTEXT_DEPLOYMENT_TOKEN}" \
  http://127.0.0.1:8000/v1/capabilities
```

See [HTTP API](../develop/http-api.md) for request examples and [Configuration](configuration.md) for
all Server settings.

## Protect and back up data

- Back up the directory selected by `POWERCONTEXT_HOME`, or the Docker volume mounted at `/data`.
- Stop writes or stop the Server while taking a filesystem-level SQLite backup.
- Keep database backups and bearer tokens out of the repository.
- Test restoration before relying on a backup procedure.
