"""Tests for portman.health — Phase 6."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from portman.health import check_all, check_port

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _dummy_handler(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def _make_dummy_server() -> TestServer:
    app = web.Application()
    app.router.add_get("/", _dummy_handler)
    server = TestServer(app)
    await server.start_server()
    return server


# ===================================================================
# Tests
# ===================================================================


class TestCheckPort:
    """Tests for single port health checks."""

    async def test_returns_true_for_open_port(self) -> None:
        server = await _make_dummy_server()
        try:
            port = server.port
            assert port is not None

            result = await check_port(port)
            assert result is True
        finally:
            await server.close()

    async def test_returns_false_for_closed_port(self) -> None:
        # Assuming port 59999 is highly likely to be closed
        result = await check_port(59999)
        assert result is False

    async def test_timeout_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from typing import Any

        async def mock_open_connection(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
            await asyncio.sleep(5.0)
            return None, None

        monkeypatch.setattr("asyncio.open_connection", mock_open_connection)

        result = await check_port(80, timeout=0.01)
        assert result is False


class TestCheckAll:
    """Tests for concurrent multi-port health checks."""

    async def test_empty_list_returns_empty_dict(self) -> None:
        result = await check_all([])
        assert result == {}

    async def test_mixed_ports(self) -> None:
        server = await _make_dummy_server()
        try:
            port = server.port
            assert port is not None

            result = await check_all([port, 59999, 59998])
            assert result == {
                port: True,
                59999: False,
                59998: False,
            }
        finally:
            await server.close()

    async def test_concurrent_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typing import Any

        server = await _make_dummy_server()
        try:
            port = server.port
            assert port is not None

            call_count = 0

            original_open_connection = asyncio.open_connection

            async def mock_open_connection(host: str, p: int) -> tuple[Any, Any]:
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.1)
                return await original_open_connection(host, p)

            monkeypatch.setattr("asyncio.open_connection", mock_open_connection)

            start = asyncio.get_event_loop().time()
            result = await check_all([port, port, port])
            elapsed = asyncio.get_event_loop().time() - start

            assert result == {port: True}
            assert call_count == 3
            assert elapsed < 0.25
        finally:
            await server.close()
