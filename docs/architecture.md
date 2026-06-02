# Portman Architecture

Portman has four core runtime parts:

```text
portman.yml
    |
    v
Config loader -> RouteTable -> Proxy app -> localhost upstreams
                    ^
                    |
              ConfigWatcher
```

## Request Flow

```text
Browser
  |
  | Host: api.localhost
  v
Portman on 127.0.0.1:8080
  |
  | RouteTable lookup: api.localhost -> localhost:8000
  v
Upstream service on localhost:8000
```

The proxy uses the request `Host` header, normalized to lowercase with trailing
dots removed, to select a route. Unknown hosts return a 404. Unavailable
upstreams return a 502, and timed-out upstreams return a 504.

## RouteTable

`RouteTable` is the single source of truth for runtime routes. It stores a
dictionary of normalized domain names to immutable `RouteEntry` values.

`RouteTable.update(config)`:

1. Builds a new map from the validated config.
2. Swaps the internal map under a short lock.
3. Returns a `RouteTableDiff` describing added, removed, and changed routes.

Reads use the current dictionary reference. Snapshots copy the current map under
the same lock so callers can iterate over a stable point-in-time view.

## Watcher Reloads

`ConfigWatcher` watches the parent directory of the config file because many
editors save files by writing a temporary file and replacing the target file.
Only events for the configured path are handled.

Reloads are debounced with a short timer. On reload:

1. The config file is loaded and validated.
2. If validation succeeds, `RouteTable.update()` atomically publishes the new
   routes and logs the diff.
3. If validation fails or an unexpected exception occurs, the error is logged
   and the previous route table remains active.

There is no separate route registry or background reconciliation mechanism.
`RouteTable` is the runtime source of truth.

## Hosts File Integration

Hosts file integration is experimental and optional. Core functionality uses
`*.localhost` domains and does not require OS hosts file modification.
