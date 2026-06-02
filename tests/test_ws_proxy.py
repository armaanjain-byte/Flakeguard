"""Tests for portman.ws_proxy — Phase 4."""

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
    proxy_port: int = 29_000,
) -> PortmanConfig:
    entries = []
    for domain, value in routes.items():
        if isinstance(value, int):
            entries.append(RouteConfig(domain=domain, port=value))
        else:
            entries.append(RouteConfig(domain=domain, **value))
    return PortmanConfig(proxy_port=proxy_port, routes=tuple(entries))


async def _make_proxy_client(
    route_table: RouteTable,
    config: PortmanConfig,
) -> TestClient[web.Request, web.Application]:
    proxy_app = create_app(route_table, config)
    client = TestClient(TestServer(proxy_app))
    await client.start_server()
    return client


# ---------------------------------------------------------------------------
# Test Echo Upstream
# ---------------------------------------------------------------------------


async def _echo_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            if msg.data == "close_me":
                await ws.close(code=1000, message=b"closed by request")
                return ws
            await ws.send_str(f"echo: {msg.data}")
        elif msg.type == WSMsgType.BINARY:
            await ws.send_bytes(msg.data)
        elif msg.type == WSMsgType.CLOSE:
            await ws.close()

    return ws


async def _make_ws_upstream() -> TestServer:
    app = web.Application()
    app.router.add_get("/", _echo_handler)
    server = TestServer(app)
    await server.start_server()
    return server


# ===================================================================
# Tests
# ===================================================================


class TestWebSocketProxy:
    """End-to-end WebSocket proxy tests."""

    async def test_text_messages(self) -> None:
        upstream = await _make_ws_upstream()
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"ws.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                async with client.ws_connect(
                    "/", headers={"Host": "ws.localhost"}
                ) as ws:
                    await ws.send_str("hello")
                    resp = await ws.receive()
                    assert resp.type == WSMsgType.TEXT
                    assert resp.data == "echo: hello"
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_binary_messages(self) -> None:
        upstream = await _make_ws_upstream()
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"ws.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                async with client.ws_connect(
                    "/", headers={"Host": "ws.localhost"}
                ) as ws:
                    await ws.send_bytes(b"\x00\x01\x02")
                    resp = await ws.receive()
                    assert resp.type == WSMsgType.BINARY
                    assert resp.data == b"\x00\x01\x02"
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_client_closes_cleanly(self) -> None:
        upstream = await _make_ws_upstream()
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"ws.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                async with client.ws_connect(
                    "/", headers={"Host": "ws.localhost"}
                ) as ws:
                    await ws.send_str("hello")
                    await ws.receive()
                    await ws.close(code=1000, message=b"done")

                assert ws.closed
            finally:
                await client.close()
        finally:
            await upstream.close()

    async def test_upstream_closes_cleanly(self) -> None:
        upstream = await _make_ws_upstream()
        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"ws.localhost": port})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                async with client.ws_connect(
                    "/", headers={"Host": "ws.localhost"}
                ) as ws:
                    await ws.send_str("close_me")

                    resp = await ws.receive()
                    assert resp.type == WSMsgType.CLOSE
                    assert ws.close_code == 1000
            finally:
                await client.close()
        finally:
            await upstream.close()


class TestWebSocketErrors:
    """Upstream error handling."""

    async def test_upstream_unavailable(self) -> None:
        cfg = _cfg({"ws.localhost": 59_999})
        table = RouteTable.from_config(cfg)
        client = await _make_proxy_client(table, cfg)

        try:
            async with client.ws_connect("/", headers={"Host": "ws.localhost"}) as ws:
                msg = await ws.receive()
                assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED)
                assert ws.close_code in (1011, 1006)
        finally:
            await client.close()

    async def test_upstream_timeout(self) -> None:
        async def _slow_handler(request: web.Request) -> web.WebSocketResponse:
            await asyncio.sleep(5)
            raise Exception("Should not reach here")

        app = web.Application()
        app.router.add_get("/", _slow_handler)
        upstream = TestServer(app)
        await upstream.start_server()

        try:
            port = upstream.port
            assert port is not None
            cfg = _cfg({"ws.localhost": {"port": port, "timeout": 1}})
            table = RouteTable.from_config(cfg)
            client = await _make_proxy_client(table, cfg)

            try:
                async with client.ws_connect(
                    "/", headers={"Host": "ws.localhost"}
                ) as ws:
                    msg = await ws.receive()
                    assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED)
                    assert ws.close_code in (1011, 1006)
            finally:
                await client.close()
        finally:
            await upstream.close()
