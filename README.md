portman
A developer running a modern project typically has 3–8 local services running simultaneously: a frontend dev server, a backend API, a database admin UI, maybe a queue worker UI, maybe a mock service. All of them are on different ports. The developer has to remember port numbers, and nothing enforces consistency across teammates.
Existing solutions require either heavy configuration (Nginx, Caddy, Traefik), a non-Python runtime (Go, Node, Rust), sudo on every run, or only work on macOS. No tool is installable with a single pip install and configurable in under two minutes.

What portman does — one sentence
portman is a local reverse proxy that lets you visit api.local, app.local, and db.local in your browser instead of localhost:8000, localhost:3000, and localhost:5432 — configured with one YAML file and started with one command.
