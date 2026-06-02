"""Tests for portman.config — Phase 1."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from portman.config import (
    _DEFAULT_PROXY_PORT,
    _DEFAULT_TIMEOUT,
    _MAX_PORT,
    _MAX_TIMEOUT,
    _MIN_PORT,
    _MIN_TIMEOUT,
    ConfigError,
    PortmanConfig,
    load,
)

if TYPE_CHECKING:
    from pathlib import Path


# ===================================================================
# Happy-path: simple form
# ===================================================================


class TestSimpleForm:
    """``routes: {domain: port}`` shorthand."""

    def test_single_route(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": {"api.localhost": 8000}})
        cfg = load(path)

        assert isinstance(cfg, PortmanConfig)
        assert cfg.proxy_port == _DEFAULT_PROXY_PORT
        assert len(cfg.routes) == 1

        route = cfg.routes[0]
        assert route.domain == "api.localhost"
        assert route.port == 8000
        assert route.timeout == _DEFAULT_TIMEOUT

    def test_multiple_routes(self, tmp_yaml: Any) -> None:
        path = tmp_yaml(
            {
                "routes": {
                    "api.localhost": 8000,
                    "app.localhost": 3000,
                    "db.localhost": 5432,
                }
            }
        )
        cfg = load(path)
        assert len(cfg.routes) == 3
        domains = {r.domain for r in cfg.routes}
        assert domains == {"api.localhost", "app.localhost", "db.localhost"}

    def test_custom_proxy_port(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"proxy_port": 9090, "routes": {"api.localhost": 8000}})
        cfg = load(path)
        assert cfg.proxy_port == 9090


# ===================================================================
# Happy-path: extended form
# ===================================================================


class TestExtendedForm:
    """``routes: {domain: {port: …, timeout: …}}`` mapping."""

    def test_extended_with_timeout(self, tmp_yaml: Any) -> None:
        path = tmp_yaml(
            {"routes": {"api.localhost": {"port": 8000, "timeout": 60}}}
        )
        cfg = load(path)
        route = cfg.routes[0]
        assert route.port == 8000
        assert route.timeout == 60

    def test_extended_without_timeout_uses_default(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": {"api.localhost": {"port": 8000}}})
        cfg = load(path)
        assert cfg.routes[0].timeout == _DEFAULT_TIMEOUT

    def test_mixed_simple_and_extended(self, tmp_yaml: Any) -> None:
        path = tmp_yaml(
            {
                "routes": {
                    "api.localhost": 8000,
                    "app.localhost": {"port": 3000, "timeout": 120},
                }
            }
        )
        cfg = load(path)
        assert len(cfg.routes) == 2
        by_domain = {r.domain: r for r in cfg.routes}
        assert by_domain["api.localhost"].timeout == _DEFAULT_TIMEOUT
        assert by_domain["app.localhost"].timeout == 120


# ===================================================================
# Port validation
# ===================================================================


class TestPortValidation:
    """Validate port numbers on both proxy_port and route ports."""

    @pytest.mark.parametrize("port", [_MIN_PORT, 80, 443, 8080, _MAX_PORT])
    def test_valid_ports(self, tmp_yaml: Any, port: int) -> None:
        # Pick a proxy_port that won't collide with the route port under test.
        proxy = 9999 if port == _DEFAULT_PROXY_PORT else _DEFAULT_PROXY_PORT
        path = tmp_yaml({"proxy_port": proxy, "routes": {"api.localhost": port}})
        cfg = load(path)
        assert cfg.routes[0].port == port

    @pytest.mark.parametrize("port", [0, -1, 65_536, 100_000])
    def test_invalid_route_port(self, tmp_yaml: Any, port: int) -> None:
        path = tmp_yaml({"routes": {"api.localhost": port}})
        with pytest.raises(ConfigError, match="must be between"):
            load(path)

    @pytest.mark.parametrize("port", [0, -1, 65_536])
    def test_invalid_proxy_port(self, tmp_yaml: Any, port: int) -> None:
        path = tmp_yaml({"proxy_port": port, "routes": {"api.localhost": 8000}})
        with pytest.raises(ConfigError, match="must be between"):
            load(path)


# ===================================================================
# Domain validation
# ===================================================================


class TestDomainValidation:
    """Validate domain / hostname strings."""

    @pytest.mark.parametrize(
        "domain",
        [
            "api.localhost",
            "app.local",
            "my-service.dev.local",
            "a",
            "a.b.c.d.e",
            "UPPER.case",
        ],
    )
    def test_valid_domains(self, tmp_yaml: Any, domain: str) -> None:
        path = tmp_yaml({"routes": {domain: 8000}})
        cfg = load(path)
        assert cfg.routes[0].domain == domain

    @pytest.mark.parametrize(
        "domain",
        [
            "",
            "-leading-hyphen.local",
            "trailing-hyphen-.local",
            "has space.local",
            "under_score.local",
            "no..double.dot",
        ],
    )
    def test_invalid_domains(self, tmp_yaml: Any, domain: str) -> None:
        path = tmp_yaml({"routes": {domain: 8000}})
        with pytest.raises(ConfigError, match="Invalid domain"):
            load(path)


# ===================================================================
# Timeout validation
# ===================================================================


class TestTimeoutValidation:
    """Validate the timeout range."""

    @pytest.mark.parametrize("timeout", [_MIN_TIMEOUT, 30, _MAX_TIMEOUT])
    def test_valid_timeouts(self, tmp_yaml: Any, timeout: int) -> None:
        path = tmp_yaml(
            {"routes": {"api.localhost": {"port": 8000, "timeout": timeout}}}
        )
        cfg = load(path)
        assert cfg.routes[0].timeout == timeout

    @pytest.mark.parametrize("timeout", [0, -1, _MAX_TIMEOUT + 1, 1000])
    def test_invalid_timeouts(self, tmp_yaml: Any, timeout: int) -> None:
        path = tmp_yaml(
            {"routes": {"api.localhost": {"port": 8000, "timeout": timeout}}}
        )
        with pytest.raises(ConfigError, match="Timeout must be between"):
            load(path)


# ===================================================================
# Port conflict validation
# ===================================================================


class TestPortConflict:
    """proxy_port must not collide with any route port."""

    def test_conflict_raises(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"proxy_port": 8000, "routes": {"api.localhost": 8000}})
        with pytest.raises(ConfigError, match="conflicts with proxy_port"):
            load(path)

    def test_default_proxy_conflict(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": {"api.localhost": _DEFAULT_PROXY_PORT}})
        with pytest.raises(ConfigError, match="conflicts with proxy_port"):
            load(path)

    def test_no_conflict_different_ports(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"proxy_port": 9090, "routes": {"api.localhost": 8000}})
        cfg = load(path)
        assert cfg.proxy_port == 9090
        assert cfg.routes[0].port == 8000


# ===================================================================
# File / YAML errors
# ===================================================================


class TestFileErrors:
    """Missing files, bad YAML, wrong top-level type, etc."""

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load(tmp_path / "nope.yaml")

    def test_directory_instead_of_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not a file"):
            load(tmp_path)

    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("routes:\n  - :\n    bad:: yaml", encoding="utf-8")
        with pytest.raises(ConfigError, match="invalid YAML"):
            load(bad)

    def test_top_level_list(self, tmp_path: Path) -> None:
        bad = tmp_path / "list.yaml"
        bad.write_text("- one\n- two\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load(bad)

    def test_missing_routes_key(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"proxy_port": 8080})
        with pytest.raises(ConfigError, match="missing the required 'routes'"):
            load(path)

    def test_routes_not_a_mapping(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": [1, 2, 3]})
        with pytest.raises(ConfigError, match="must be a mapping"):
            load(path)

    def test_empty_routes(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": {}})
        with pytest.raises(ConfigError, match="at least one route"):
            load(path)


# ===================================================================
# Edge-cases & error wrapping
# ===================================================================


class TestEdgeCases:
    """Miscellaneous edge-case coverage."""

    def test_route_value_not_int_or_dict(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": {"api.localhost": "bad"}})
        with pytest.raises(ConfigError, match="invalid value"):
            load(path)

    def test_route_value_bool_rejected(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": {"api.localhost": True}})
        with pytest.raises(ConfigError, match="invalid value"):
            load(path)

    def test_config_error_is_exception(self) -> None:
        err = ConfigError("boom")
        assert isinstance(err, Exception)
        assert err.message == "boom"
        assert str(err) == "boom"

    def test_route_config_is_frozen(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": {"api.localhost": 8000}})
        cfg = load(path)
        with pytest.raises(ValidationError):
            cfg.routes[0].port = 9999  # type: ignore[misc]

    def test_portman_config_is_frozen(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"routes": {"api.localhost": 8000}})
        cfg = load(path)
        with pytest.raises(ValidationError):
            cfg.proxy_port = 1234  # type: ignore[misc]

    def test_boundary_port_min(self, tmp_yaml: Any) -> None:
        path = tmp_yaml({"proxy_port": _MIN_PORT, "routes": {"a.local": 2}})
        cfg = load(path)
        assert cfg.proxy_port == _MIN_PORT

    def test_boundary_port_max(self, tmp_yaml: Any) -> None:
        path = tmp_yaml(
            {"proxy_port": _MAX_PORT, "routes": {"a.local": _MAX_PORT - 1}}
        )
        cfg = load(path)
        assert cfg.proxy_port == _MAX_PORT

    def test_never_exposes_pydantic_validation_error(self, tmp_yaml: Any) -> None:
        """Even when Pydantic itself throws, the caller only sees ConfigError."""
        path = tmp_yaml({"routes": {"api.localhost": {"port": "not-a-number"}}})
        with pytest.raises(ConfigError):
            load(path)
