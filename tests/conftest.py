"""Shared pytest fixtures for portman tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def tmp_yaml(tmp_path: Path) -> Any:
    """Factory fixture: write a dict as YAML and return the ``Path``.

    Usage::

        def test_something(tmp_yaml):
            cfg_path = tmp_yaml({"proxy_port": 9090, "routes": {"a.local": 3000}})
    """

    def _write(data: dict[str, Any], filename: str = "portman.yaml") -> Path:
        p = tmp_path / filename
        p.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
        return p

    return _write
