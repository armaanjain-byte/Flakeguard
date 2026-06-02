"""Health checking utilities.

Provides functions to concurrently check TCP connectivity to upstream
ports.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


async def check_port(port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP connection can be established to localhost on the given port.

    Returns True if successful, False otherwise.
    """
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def check_all(ports: Iterable[int], timeout: float = 1.0) -> dict[int, bool]:
    """Concurrently check multiple ports.

    Returns a mapping of port to health status (True for healthy, False for unhealthy).
    """
    ports_list = list(ports)
    if not ports_list:
        return {}

    results = await asyncio.gather(
        *(check_port(port, timeout=timeout) for port in ports_list)
    )

    return dict(zip(ports_list, results, strict=False))
