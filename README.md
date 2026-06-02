# Portman

Portman is a lightweight local reverse proxy for production-like `.localhost`
domains. It lets multi-service development projects use stable names like
`api.localhost`, `app.localhost`, and `admin.localhost` instead of a pile of
remembered ports.

```text
                    portman.yml
                         |
                         v
Browser -> api.localhost:8080   -> Portman -> localhost:8000
Browser -> app.localhost:8080   -> Portman -> localhost:3000
Browser -> admin.localhost:8080 -> Portman -> localhost:9000
```

Portman is aimed at small teams and solo developers who want cleaner local
environments without running a full Nginx, Caddy, Traefik, or Docker routing
setup for every project.

## Quick Start

Install Portman:

```bash
pip install portman
```

Create `portman.yml`:

```yaml
proxy_port: 8080
routes:
  api.localhost: 8000
  app.localhost: 3000
  admin.localhost:
    port: 9000
    timeout: 60
```

Start your local services, then start Portman:

```bash
portman start --config portman.yml
```

Open:

```text
http://api.localhost:8080
http://app.localhost:8080
http://admin.localhost:8080
```

List configured routes and health status:

```bash
portman list --config portman.yml
```

## How It Works

Portman binds to `127.0.0.1` on `proxy_port`, reads the incoming `Host` header,
and looks up the matching domain in an in-memory route table. Requests are then
forwarded to the configured upstream service on `localhost:<port>`.

The route table is built from `portman.yml` at startup. A file watcher monitors
the config file's directory and reloads the table when the config file changes.
Valid reloads replace the route table atomically; invalid reloads are logged and
the previous working routes remain active.

HTTP and WebSocket traffic are both proxied. Portman rewrites upstream `Host`
headers to `localhost:<port>` and preserves useful forwarding headers such as
`X-Forwarded-Host`.

## Hosts File Integration

Hosts file modification is not required for normal Portman usage. Prefer
`.localhost` domains, which are intended for loopback local development and do
not require editing `/etc/hosts` or the Windows hosts file on modern systems.

The `portman hosts` commands remain available as an experimental, optional
escape hatch for custom domains. They are not part of the core workflow.

## Benchmarking

Portman includes a small stdlib-only benchmark helper:

```bash
python scripts/benchmark.py --host api.localhost --port 8080 --requests 1000 --concurrency 50
```

Run it while Portman and the target upstream service are already running. The
script reports request throughput plus mean, median, p95, and p99 latency.

## Limitations

- Portman is a local development proxy, not a production edge proxy.
- TLS termination is not implemented in v0.1.0.
- `.localhost` domains should be preferred; custom domains may require manual
  DNS or hosts file setup.
- Upstream services must already be running on local TCP ports.
- Route matching is based on the request `Host` header, not path prefixes.

## Release Status

See `docs/release-readiness.md` for the current v0.1.0 readiness audit.
