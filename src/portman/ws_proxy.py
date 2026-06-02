"""WebSocket reverse-proxy handler.

Relays WebSocket connections bidirectionally between the client and
the upstream server. Uses ``asyncio.gather()`` to concurrently read
from both ends and write to the other.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError, ClientSession, WSMsgType, web

logger = logging.getLogger("portman.ws_proxy")


async def ws_proxy_handler(
    request: web.Request,
    entry: Any,
    session: ClientSession,
    headers: dict[str, str],
) -> web.WebSocketResponse:
    """Relay WebSocket traffic bidirectionally.

    Called by the main proxy handler when an ``Upgrade: websocket``
    request is detected.
    """
    client_ws = web.WebSocketResponse()
    await client_ws.prepare(request)

    upstream_url = f"ws://localhost:{entry.port}{request.path_qs}"

    # aiohttp handles its own Sec-WebSocket-* headers for the upstream connection.
    # We must strip them from the forwarded headers to avoid duplication errors.
    clean_headers = {
        k: v for k, v in headers.items()
        if not k.lower().startswith("sec-websocket-")
    }

    try:
        async with session.ws_connect(
            upstream_url,
            headers=clean_headers,
            timeout=entry.timeout,
        ) as upstream_ws:

            async def client_to_upstream() -> None:
                async for msg in client_ws:
                    if msg.type == WSMsgType.TEXT:
                        await upstream_ws.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await upstream_ws.send_bytes(msg.data)
                    elif msg.type == WSMsgType.CLOSE:
                        message = (
                            msg.extra.encode()
                            if isinstance(msg.extra, str)
                            else b""
                        )
                        await upstream_ws.close(
                            code=msg.data,
                            message=message,
                        )
                        break
                    elif msg.type == WSMsgType.ERROR:
                        await upstream_ws.close()
                        break

                if not upstream_ws.closed:
                    await upstream_ws.close(
                        code=client_ws.close_code or 1000,
                        message=b"",
                    )

            async def upstream_to_client() -> None:
                async for msg in upstream_ws:
                    if msg.type == WSMsgType.TEXT:
                        await client_ws.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await client_ws.send_bytes(msg.data)
                    elif msg.type == WSMsgType.CLOSE:
                        message = (
                            msg.extra.encode()
                            if isinstance(msg.extra, str)
                            else b""
                        )
                        await client_ws.close(
                            code=msg.data,
                            message=message,
                        )
                        break
                    elif msg.type == WSMsgType.ERROR:
                        await client_ws.close()
                        break

                if not client_ws.closed:
                    await client_ws.close(
                        code=upstream_ws.close_code or 1000,
                        message=b"",
                    )

            # Wait for both ends to finish relaying
            await asyncio.gather(
                client_to_upstream(),
                upstream_to_client(),
            )

    except TimeoutError:
        logger.warning("WebSocket upstream timeout: %s", upstream_url)
        if not client_ws.closed:
            await client_ws.close(code=1011, message=b"Upstream Timeout")
    except ClientError as e:
        logger.warning(
            "WebSocket upstream error %s: %s", type(e).__name__, upstream_url
        )
        if not client_ws.closed:
            await client_ws.close(code=1011, message=b"Upstream Unavailable")
    except OSError:
        logger.warning("WebSocket upstream OS error: %s", upstream_url)
        if not client_ws.closed:
            await client_ws.close(code=1011, message=b"Upstream Unavailable")

    return client_ws
