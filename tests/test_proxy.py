"""Tests for portman.proxy — Phase 3.

Uses *aiohttp*'s ``TestServer`` to spin up both the proxy and fake
upstream servers in-process, avoiding real network I/O.
"""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from portman.config import PortmanConfig, RouteConfig
from portman.proxy import create_app
from portman.route_table import RouteTable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.asyncio


def _cfg(
    routes: dict[str, int | dict[str, Any]],
    proxy_port: int = 19_000,
) -> PortmanConfig:
    """Build a ``PortmanConfig`` for testing."""
    entries: list[RouteConfig] = []
    for domain, value in routes.items():
        if isinstance(value, int):
            entries.append(RouteConfig(domain=domain, port=value))
        else:
            entries.append(RouteConfig(domain=domain, **value))
    return PortmanConfig(proxy_port=proxy_port, routes=tuple(entries))


async def _make_upstream(
    handlers: dict[str, web.RequestHandler] | None = None,
) -> TestServer:
    """Create a trivial upstream ``TestServer``.

    *handlers* maps route strings like ``"GET /"`` to handler coroutines.
    If not supplied, a default ``GET /`` that returns 200 OK is used.
    """
    app = web.Application()

    if handlers is None:
        handlers = {}

    for route_spec, handler in handlers.items():
        method, path = route_spec.split(" ", 1)
        app.router.add_route(method, path, handler)

    if not handlers:

        async def _default(request: web.Request) -> web.Response:
            return web.Response(text="upstream OK")

        app.router.add_route("*", "/{path_info:.*}", _default)

    server = TestServer(app)
    await server.start_server()
    return server


async def _make_proxy_client(
    route_table: RouteTable,
    config: PortmanConfig,
) -> TestClient:
    """Create a ``TestClient`` wrapping the proxy app."""
    proxy_app = create_app(route_table, config)
    client: TestClient = TestClient(TestServer(proxy_app))  # type: ignore[arg-type]
    await client.start_server()
    return client


# ===================================================================
# 404: unknown host
# ===================================================================


class TestUnknownHost:
    """Requests with missing or unrecognised Host → 404."""

    async def test_unknown_host_returns_404(self) -> None:
        cfg = _cfg({"api.localhost": 8000})
        table = RouteTable.from_config(cfg)
        client = await _make_proxy_client(table, cfg)

        try:
            resp = await client.get(
                "/", headers={"Host": "unknown.localhost"}
            )
            assert resp.status == 404
            body = await resp.text()
            assert "unknown.localhost" in body
        finally:
            await client.close()


# ===================================================================
# 502: upstream unavailable
# ===================================================================


class TestUpstreamUnavailable:
    """Upstream refuses connection → 502."""

    async def test_connection_refused_returns_502(self) -> None:
        # Point the route at a port that nothing is listening on.
        cfg = _cfg({"api.localhost": 59_999})
        table = RouteTable.from_config(cfg)
        client = await _make_proxy_client(table, cfg)

        try:
            resp = await client.get(
                "/", headers={"Host": "api.localhost"}
            )
            assert resp.status == 502
            body = await resp.text()
            assert "unavailable" in body.lower()
        finally:
            await client.close()


# ===================================================================
# 504: upstream timeout
# ===================================================================


class TestUpstreamTimeout:
    """Upstream takes too long → 504."""

    async def test_timeout_returns_504(self) -> None:
        import asyncio

        async def _slow_handler(request: web.Request) -> web.Response:
            await asyncio.sleep(10)
            return web.Response(text="too late")

        upstream = await _make_upstream({"GET /slow": _slow_handler})

        try:
            port = upstream.port
            assert port is not None
            # timeout=1 so the test finishes fast.
            cfg = _cfg(
                {"api.localhost": {"port": port, "timeout": 1}},
            )
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.get(
                    "/slow", headers={"Host": "api.localhost"}
                )
                assert resp.status == 504
                body = await resp.text()
                assert "timed out" in body.lower()
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# Successful proxying
# ===================================================================


class TestSuccessfulProxy:
    """Happy-path: proxy forwards requests to upstream and streams back."""

    async def test_get_returns_upstream_body(self) -> None:
        async def _handler(request: web.Request) -> web.Response:
            return web.Response(text="hello from upstream")

        upstream = await _make_upstream({"GET /": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.get(
                    "/", headers={"Host": "api.localhost"}
                )
                assert resp.status == 200
                body = await resp.text()
                assert body == "hello from upstream"
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_post_body_forwarded(self) -> None:
        async def _handler(request: web.Request) -> web.Response:
            body = await request.text()
            return web.Response(text=f"echo: {body}")

        upstream = await _make_upstream({"POST /submit": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.post(
                    "/submit",
                    headers={"Host": "api.localhost"},
                    data="my payload",
                )
                assert resp.status == 200
                body = await resp.text()
                assert body == "echo: my payload"
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_query_string_preserved(self) -> None:
        async def _handler(request: web.Request) -> web.Response:
            qs = request.query_string
            return web.Response(text=f"qs={qs}")

        upstream = await _make_upstream({"GET /search": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.get(
                    "/search?q=hello&page=2",
                    headers={"Host": "api.localhost"},
                )
                assert resp.status == 200
                body = await resp.text()
                assert "q=hello" in body
                assert "page=2" in body
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_upstream_status_code_preserved(self) -> None:
        async def _handler(request: web.Request) -> web.Response:
            return web.Response(status=201, text="created")

        upstream = await _make_upstream({"POST /items": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.post(
                    "/items", headers={"Host": "api.localhost"}
                )
                assert resp.status == 201
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_upstream_headers_preserved(self) -> None:
        async def _handler(request: web.Request) -> web.Response:
            return web.Response(
                text="ok",
                headers={"X-Custom": "my-value"},
            )

        upstream = await _make_upstream({"GET /": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.get(
                    "/", headers={"Host": "api.localhost"}
                )
                assert resp.headers.get("X-Custom") == "my-value"
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# Header rewriting
# ===================================================================


class TestHeaderRewriting:
    """Verify Host rewriting and X-Forwarded-* headers."""

    async def test_host_rewritten_to_localhost(self) -> None:
        received_host: str = ""

        async def _handler(request: web.Request) -> web.Response:
            nonlocal received_host
            received_host = request.headers.get("Host", "")
            return web.Response(text="ok")

        upstream = await _make_upstream({"GET /": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                await client.get(
                    "/", headers={"Host": "api.localhost"}
                )
                assert received_host == f"localhost:{port}"
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_x_forwarded_for_set(self) -> None:
        forwarded_for: str = ""

        async def _handler(request: web.Request) -> web.Response:
            nonlocal forwarded_for
            forwarded_for = request.headers.get("X-Forwarded-For", "")
            return web.Response(text="ok")

        upstream = await _make_upstream({"GET /": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                await client.get(
                    "/", headers={"Host": "api.localhost"}
                )
                # The forwarded-for should be a non-empty IP.
                assert forwarded_for != ""
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_x_forwarded_host_set(self) -> None:
        forwarded_host: str = ""

        async def _handler(request: web.Request) -> web.Response:
            nonlocal forwarded_host
            forwarded_host = request.headers.get("X-Forwarded-Host", "")
            return web.Response(text="ok")

        upstream = await _make_upstream({"GET /": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                await client.get(
                    "/", headers={"Host": "api.localhost"}
                )
                assert "api.localhost" in forwarded_host
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_x_forwarded_proto_set(self) -> None:
        forwarded_proto: str = ""

        async def _handler(request: web.Request) -> web.Response:
            nonlocal forwarded_proto
            forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
            return web.Response(text="ok")

        upstream = await _make_upstream({"GET /": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                await client.get(
                    "/", headers={"Host": "api.localhost"}
                )
                assert forwarded_proto == "http"
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# Streaming / large response
# ===================================================================


class TestStreaming:
    """Verify that large responses are streamed correctly."""

    async def test_large_body_streamed(self) -> None:
        # 256 KiB payload — larger than the 64 KiB chunk size.
        payload = b"X" * (256 * 1024)

        async def _handler(request: web.Request) -> web.Response:
            return web.Response(body=payload)

        upstream = await _make_upstream({"GET /big": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.get(
                    "/big", headers={"Host": "api.localhost"}
                )
                assert resp.status == 200
                body = await resp.read()
                assert body == payload
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# Multiple routes
# ===================================================================


class TestMultipleRoutes:
    """Proxy correctly routes to different upstreams based on Host."""

    async def test_routes_to_correct_upstream(self) -> None:
        async def _api_handler(request: web.Request) -> web.Response:
            return web.Response(text="api")

        async def _app_handler(request: web.Request) -> web.Response:
            return web.Response(text="app")

        upstream_api = await _make_upstream({"GET /": _api_handler})
        upstream_app = await _make_upstream({"GET /": _app_handler})

        try:
            api_port = upstream_api.port
            app_port = upstream_app.port
            assert api_port is not None
            assert app_port is not None

            cfg = _cfg({
                "api.localhost": api_port,
                "app.localhost": app_port,
            })
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp_api = await client.get(
                    "/", headers={"Host": "api.localhost"}
                )
                assert await resp_api.text() == "api"

                resp_app = await client.get(
                    "/", headers={"Host": "app.localhost"}
                )
                assert await resp_app.text() == "app"
            finally:
                await client.close()
        finally:
            await upstream_api.close()
            await upstream_app.close()
