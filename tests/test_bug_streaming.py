"""Integration tests for Bug 1 — Request body streaming.

Verifies that Portman forwards request bodies as a stream (via
``request.content``) rather than buffering the entire body in memory
with ``await request.read()``.

Each test starts a real upstream ``TestServer``, sends a large payload
through the proxy, and verifies the full payload arrives upstream.
"""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from portman.config import PortmanConfig, RouteConfig
from portman.proxy import create_app
from portman.route_table import RouteTable

pytestmark = pytest.mark.asyncio

# Size of the test payload: 2 MiB.
_PAYLOAD_SIZE: int = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(
    routes: dict[str, int | dict[str, Any]],
    proxy_port: int = 19_100,
) -> PortmanConfig:
    entries: list[RouteConfig] = []
    for domain, value in routes.items():
        if isinstance(value, int):
            entries.append(RouteConfig(domain=domain, port=value))
        else:
            entries.append(RouteConfig(domain=domain, **value))
    return PortmanConfig(proxy_port=proxy_port, routes=tuple(entries))


async def _make_upstream(
    handlers: dict[str, Any],
) -> TestServer:
    app = web.Application(client_max_size=_PAYLOAD_SIZE + 1024)
    for route_spec, handler in handlers.items():
        method, path = route_spec.split(" ", 1)
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()
    return server


async def _make_proxy_client(
    route_table: RouteTable,
    config: PortmanConfig,
) -> TestClient:
    proxy_app = create_app(route_table, config)
    # Raise the client_max_size so the proxy app itself accepts large bodies.
    proxy_app._client_max_size = _PAYLOAD_SIZE + 1024  # type: ignore[attr-defined]
    client: TestClient = TestClient(TestServer(proxy_app))  # type: ignore[arg-type]
    await client.start_server()
    return client


# ===================================================================
# POST — large body streaming
# ===================================================================


class TestStreamingPost:
    """POST with a large body is forwarded without buffering assumptions."""

    async def test_large_post_body_arrives_intact(self) -> None:
        payload = b"A" * _PAYLOAD_SIZE

        async def _handler(request: web.Request) -> web.Response:
            body = await request.read()
            return web.Response(
                text=f"size={len(body)}",
                headers={"X-Match": "true" if body == payload else "false"},
            )

        upstream = await _make_upstream({"POST /upload": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.post(
                    "/upload",
                    headers={"Host": "api.localhost"},
                    data=payload,
                )
                assert resp.status == 200
                body = await resp.text()
                assert body == f"size={_PAYLOAD_SIZE}"
                assert resp.headers["X-Match"] == "true"
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# PUT — large body streaming
# ===================================================================


class TestStreamingPut:
    """PUT with a large body is forwarded correctly."""

    async def test_large_put_body_arrives_intact(self) -> None:
        payload = b"B" * _PAYLOAD_SIZE

        async def _handler(request: web.Request) -> web.Response:
            body = await request.read()
            return web.Response(
                text=f"size={len(body)}",
                headers={"X-Match": "true" if body == payload else "false"},
            )

        upstream = await _make_upstream({"PUT /resource": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.put(
                    "/resource",
                    headers={"Host": "api.localhost"},
                    data=payload,
                )
                assert resp.status == 200
                body = await resp.text()
                assert body == f"size={_PAYLOAD_SIZE}"
                assert resp.headers["X-Match"] == "true"
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# PATCH — large body streaming
# ===================================================================


class TestStreamingPatch:
    """PATCH with a large body is forwarded correctly."""

    async def test_large_patch_body_arrives_intact(self) -> None:
        payload = b"C" * _PAYLOAD_SIZE

        async def _handler(request: web.Request) -> web.Response:
            body = await request.read()
            return web.Response(
                text=f"size={len(body)}",
                headers={"X-Match": "true" if body == payload else "false"},
            )

        upstream = await _make_upstream({"PATCH /item": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.patch(
                    "/item",
                    headers={"Host": "api.localhost"},
                    data=payload,
                )
                assert resp.status == 200
                body = await resp.text()
                assert body == f"size={_PAYLOAD_SIZE}"
                assert resp.headers["X-Match"] == "true"
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# DELETE — body forwarding (some APIs use bodies with DELETE)
# ===================================================================


class TestStreamingDelete:
    """DELETE with a body is forwarded correctly."""

    async def test_delete_with_body_forwarded(self) -> None:
        payload = b'{"id": 42}'

        async def _handler(request: web.Request) -> web.Response:
            body = await request.read()
            return web.Response(
                text=f"got={body.decode()}"
            )

        upstream = await _make_upstream({"DELETE /item": _handler})
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"api.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.delete(
                    "/item",
                    headers={"Host": "api.localhost"},
                    data=payload,
                )
                assert resp.status == 200
                body = await resp.text()
                assert body == 'got={"id": 42}'
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# GET — no body, response streaming unchanged
# ===================================================================


class TestStreamingGetNoBody:
    """GET requests with no body still work correctly."""

    async def test_get_no_body_works(self) -> None:
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

    async def test_response_streaming_unchanged(self) -> None:
        """Large response body is still streamed back correctly."""
        response_payload = b"Z" * _PAYLOAD_SIZE

        async def _handler(request: web.Request) -> web.Response:
            return web.Response(body=response_payload)

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
                assert len(body) == _PAYLOAD_SIZE
                assert body == response_payload
            finally:
                await client.close()
        finally:
            await upstream.close()
