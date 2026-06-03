"""Integration tests for Bug 2 — Python 3.10+ timeout handling.

Verifies that ``asyncio.TimeoutError`` is correctly caught across all
supported Python versions (3.10, 3.11, 3.12, 3.13).

On Python 3.10, ``asyncio.TimeoutError`` is a separate class from the
builtin ``TimeoutError``.  The old ``except TimeoutError:`` catch missed
timeouts raised by aiohttp / asyncio internals on 3.10.

Each test deliberately creates a slow upstream to trigger a timeout.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from portman.config import PortmanConfig, RouteConfig
from portman.proxy import create_app
from portman.route_table import RouteTable

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(
    routes: dict[str, int | dict[str, Any]],
    proxy_port: int = 19_200,
) -> PortmanConfig:
    entries: list[RouteConfig] = []
    for domain, value in routes.items():
        if isinstance(value, int):
            entries.append(RouteConfig(domain=domain, port=value))
        else:
            entries.append(RouteConfig(domain=domain, **value))
    return PortmanConfig(proxy_port=proxy_port, routes=tuple(entries))


async def _make_proxy_client(
    route_table: RouteTable,
    config: PortmanConfig,
) -> TestClient:
    proxy_app = create_app(route_table, config)
    client: TestClient = TestClient(TestServer(proxy_app))  # type: ignore[arg-type]
    await client.start_server()
    return client


# ===================================================================
# HTTP timeout → 504
# ===================================================================


class TestHttpTimeout:
    """Deliberately slow HTTP upstream triggers a 504 via asyncio.TimeoutError."""

    async def test_get_timeout_returns_504(self) -> None:
        async def _slow_handler(request: web.Request) -> web.Response:
            await asyncio.sleep(10)
            return web.Response(text="too late")

        app = web.Application()
        app.router.add_route("GET", "/slow", _slow_handler)
        upstream = TestServer(app)
        await upstream.start_server()

        try:
            port = upstream.port
            assert port is not None
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

    async def test_post_timeout_returns_504(self) -> None:
        async def _slow_handler(request: web.Request) -> web.Response:
            await asyncio.sleep(10)
            return web.Response(text="too late")

        app = web.Application()
        app.router.add_route("POST", "/slow", _slow_handler)
        upstream = TestServer(app)
        await upstream.start_server()

        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg(
                {"api.localhost": {"port": port, "timeout": 1}},
            )
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                resp = await client.post(
                    "/slow",
                    headers={"Host": "api.localhost"},
                    data=b"some data",
                )
                assert resp.status == 504
                body = await resp.text()
                assert "timed out" in body.lower()
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_504_body_contains_port(self) -> None:
        """Verify the 504 response body references the upstream port."""

        async def _slow_handler(request: web.Request) -> web.Response:
            await asyncio.sleep(10)
            return web.Response(text="too late")

        app = web.Application()
        app.router.add_route("GET", "/slow", _slow_handler)
        upstream = TestServer(app)
        await upstream.start_server()

        try:
            port = upstream.port
            assert port is not None
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
                assert str(port) in body
            finally:
                await client.close()
        finally:
            await upstream.close()


# ===================================================================
# WebSocket timeout
# ===================================================================


class TestWebSocketTimeout:
    """Deliberately slow WS upstream triggers timeout via asyncio.TimeoutError."""

    async def test_ws_timeout_closes_with_1011(self) -> None:
        async def _slow_ws_handler(request: web.Request) -> web.WebSocketResponse:
            # Never complete the handshake — just sleep.
            await asyncio.sleep(10)
            raise AssertionError("Should not reach here")

        app = web.Application()
        app.router.add_get("/ws", _slow_ws_handler)
        upstream = TestServer(app)
        await upstream.start_server()

        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg(
                {"ws.localhost": {"port": port, "timeout": 1}},
            )
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                async with client.ws_connect(
                    "/ws", headers={"Host": "ws.localhost"}
                ) as ws:
                    msg = await ws.receive()
                    assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED)
                    assert ws.close_code in (1011, 1006)
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_ws_normal_operation_unaffected(self) -> None:
        """A WebSocket that responds quickly still works normally."""

        async def _echo_handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await ws.send_str(f"echo: {msg.data}")
                elif msg.type == WSMsgType.CLOSE:
                    await ws.close()
            return ws

        app = web.Application()
        app.router.add_get("/ws", _echo_handler)
        upstream = TestServer(app)
        await upstream.start_server()

        try:
            port = upstream.port
            assert port is not None
            # Use a generous timeout — this should NOT trigger.
            cfg = _cfg(
                {"ws.localhost": {"port": port, "timeout": 30}},
            )
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                async with client.ws_connect(
                    "/ws", headers={"Host": "ws.localhost"}
                ) as ws:
                    await ws.send_str("ping")
                    resp = await ws.receive()
                    assert resp.type == WSMsgType.TEXT
                    assert resp.data == "echo: ping"
            finally:
                await client.close()
        finally:
            await upstream.close()
