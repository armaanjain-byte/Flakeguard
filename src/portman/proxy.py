"""HTTP reverse-proxy built on *aiohttp*.

The proxy inspects the ``Host`` header of every incoming request, resolves
it through the :class:`~portman.route_table.RouteTable`, and forwards the
request to ``http://localhost:<port>``.  Responses are streamed back
chunk-by-chunk so large payloads never need to be buffered entirely in
memory.

Error semantics
~~~~~~~~~~~~~~~
* **404** — the ``Host`` header is missing or does not match any route.
* **502** — the upstream service refused the connection or returned an
  unexpected error.
* **504** — the upstream service did not respond within the configured
  per-route timeout.

Public API
~~~~~~~~~~
The sole entry-point is :func:`create_app`, which returns a fully-wired
:class:`aiohttp.web.Application`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiohttp import (
    ClientConnectionError,
    ClientResponse,
    ClientSession,
    ClientTimeout,
    web,
)

if TYPE_CHECKING:
    from portman.config import PortmanConfig
    from portman.route_table import RouteTable

from portman.ws_proxy import ws_proxy_handler

logger = logging.getLogger("portman.proxy")

# ---------------------------------------------------------------------------
# App-level keys  (plain strings — avoids AppKey generic headaches)
# ---------------------------------------------------------------------------

_ROUTE_TABLE_KEY = "portman.route_table"
_CLIENT_SESSION_KEY = "portman.client_session"
_ROUTE_ENTRY_KEY = "portman.route_entry"

# Chunk size for streaming response bodies (64 KiB).
_STREAM_CHUNK_SIZE: int = 64 * 1024

# Headers that must NOT be forwarded verbatim.
_HOP_BY_HOP_HEADERS: frozenset[str] = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
})

# Type alias for the "next handler" parameter in middleware.
_Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


# ---------------------------------------------------------------------------
# Middleware: resolve Host → RouteEntry
# ---------------------------------------------------------------------------


@web.middleware
async def _route_middleware(
    request: web.Request,
    handler: _Handler,
) -> web.StreamResponse:
    """Extract the ``Host`` header, look up the route, and stash the
    :class:`RouteEntry` on the request for the handler.
    """
    host_header: str = request.host  # includes port if present
    if not host_header:
        return web.Response(
            status=404,
            text="No Host header in request.\n",
        )

    # Strip optional port from Host (e.g. "api.localhost:8080" → "api.localhost").
    domain = host_header.split(":")[0]

    route_table: Any = request.app[_ROUTE_TABLE_KEY]
    entry: Any = route_table.get(domain)

    if entry is None:
        logger.debug("No route for host %r", domain)
        return web.Response(
            status=404,
            text=f"No route configured for host '{domain}'.\n",
        )

    # Stash the entry for the handler.
    request[_ROUTE_ENTRY_KEY] = entry
    return await handler(request)


# ---------------------------------------------------------------------------
# Handler: forward request → stream response
# ---------------------------------------------------------------------------


async def _proxy_handler(request: web.Request) -> web.StreamResponse:
    """Forward the request to the upstream service and stream the response
    back to the client.
    """
    entry: Any = request[_ROUTE_ENTRY_KEY]
    session: ClientSession = request.app[_CLIENT_SESSION_KEY]

    # Build forwarded headers.
    headers = _build_upstream_headers(request, entry)

    # Detect WebSocket Upgrade
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await ws_proxy_handler(request, entry, session, headers)

    # Build upstream URL preserving path and query string.
    upstream_url = (
        f"http://localhost:{entry.port}"
        f"{request.path_qs}"
    )

    timeout = ClientTimeout(total=entry.timeout)

    try:
        body = await request.read()
        upstream_resp = await session.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            data=body if body else None,
            timeout=timeout,
            allow_redirects=False,
        )
    except TimeoutError:
        logger.warning(
            "Upstream timeout for %s after %ds",
            upstream_url,
            entry.timeout,
        )
        return web.Response(
            status=504,
            text=f"Upstream at localhost:{entry.port} timed out.\n",
        )
    except ClientConnectionError:
        logger.warning("Upstream connection refused: %s", upstream_url)
        return web.Response(
            status=502,
            text=f"Upstream at localhost:{entry.port} is unavailable.\n",
        )
    except OSError:
        logger.warning("Upstream OS error: %s", upstream_url)
        return web.Response(
            status=502,
            text=f"Upstream at localhost:{entry.port} is unavailable.\n",
        )

    # Stream the response back.
    response = web.StreamResponse(
        status=upstream_resp.status,
        headers=_filter_response_headers(upstream_resp),
    )
    await response.prepare(request)

    async for chunk in upstream_resp.content.iter_chunked(_STREAM_CHUNK_SIZE):
        await response.write(chunk)

    await response.write_eof()
    upstream_resp.release()
    return response


# ---------------------------------------------------------------------------
# Header helpers
# ---------------------------------------------------------------------------


def _build_upstream_headers(
    request: web.Request,
    entry: Any,
) -> dict[str, str]:
    """Build the header dict to send to the upstream.

    * Preserves most original headers.
    * Rewrites ``Host`` to ``localhost:<port>``.
    * Adds ``X-Forwarded-*`` headers.
    * Strips hop-by-hop headers.
    """
    headers: dict[str, str] = {}

    for name, value in request.headers.items():
        if name.lower() not in _HOP_BY_HOP_HEADERS:
            headers[name] = value

    # Rewrite Host.
    headers["Host"] = f"localhost:{entry.port}"

    # X-Forwarded-* headers.
    peer: str = request.remote or "127.0.0.1"
    headers["X-Forwarded-For"] = peer
    headers["X-Forwarded-Host"] = request.host or ""
    headers["X-Forwarded-Proto"] = request.scheme

    return headers


def _filter_response_headers(
    upstream_resp: ClientResponse,
) -> dict[str, str]:
    """Copy upstream response headers, stripping hop-by-hop headers."""
    headers: dict[str, str] = {}
    for name, value in upstream_resp.headers.items():
        if name.lower() not in _HOP_BY_HOP_HEADERS:
            headers[name] = value
    return headers


# ---------------------------------------------------------------------------
# Lifecycle: managed ClientSession
# ---------------------------------------------------------------------------


async def _on_startup(app: web.Application) -> None:
    """Create the shared ``ClientSession``."""
    app[_CLIENT_SESSION_KEY] = ClientSession()


async def _on_cleanup(app: web.Application) -> None:
    """Close the shared ``ClientSession``."""
    session: ClientSession = app[_CLIENT_SESSION_KEY]
    await session.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_app(
    route_table: RouteTable,
    config: PortmanConfig,
) -> web.Application:
    """Build an :class:`aiohttp.web.Application` wired for proxying.

    Parameters:
        route_table: The route table to resolve ``Host`` headers against.
        config: The validated configuration (used for ``proxy_port``
            and potential future settings).

    Returns:
        A ready-to-run ``aiohttp.web.Application``.
    """
    app = web.Application(
        middlewares=[_route_middleware],
    )

    app[_ROUTE_TABLE_KEY] = route_table

    # Catch-all route: every path goes through the proxy handler.
    app.router.add_route("*", "/{path_info:.*}", _proxy_handler)

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    return app
