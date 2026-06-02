"""Tests for portman.route_table — Phase 2."""

from __future__ import annotations

from typing import Any

import pytest

from portman.config import PortmanConfig, RouteConfig
from portman.route_table import (
    RouteEntry,
    RouteTable,
    RouteTableDiff,
    _normalise_domain,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(
    routes: dict[str, int | dict[str, Any]],
    proxy_port: int = 9090,
) -> PortmanConfig:
    """Shorthand to build a ``PortmanConfig`` for tests.

    Uses proxy_port=9090 by default to avoid collisions with common
    route ports like 8080.
    """
    route_entries = []
    for domain, value in routes.items():
        if isinstance(value, int):
            route_entries.append(RouteConfig(domain=domain, port=value))
        else:
            route_entries.append(RouteConfig(domain=domain, **value))
    return PortmanConfig(proxy_port=proxy_port, routes=tuple(route_entries))


# ===================================================================
# Domain normalisation
# ===================================================================


class TestNormaliseDomain:
    """Low-level ``_normalise_domain`` helper."""

    def test_lowercase(self) -> None:
        assert _normalise_domain("API.LocalHost") == "api.localhost"

    def test_strip_trailing_dot(self) -> None:
        assert _normalise_domain("api.localhost.") == "api.localhost"

    def test_strip_multiple_trailing_dots(self) -> None:
        assert _normalise_domain("api.localhost...") == "api.localhost"

    def test_lowercase_and_strip(self) -> None:
        assert _normalise_domain("API.Local.") == "api.local"

    def test_already_normalised(self) -> None:
        assert _normalise_domain("api.localhost") == "api.localhost"

    def test_single_label(self) -> None:
        assert _normalise_domain("LOCALHOST.") == "localhost"


# ===================================================================
# from_config
# ===================================================================


class TestFromConfig:
    """Build a RouteTable from a PortmanConfig."""

    def test_single_route(self) -> None:
        cfg = _cfg({"api.localhost": 8000})
        table = RouteTable.from_config(cfg)

        entry = table.get("api.localhost")
        assert entry is not None
        assert entry.domain == "api.localhost"
        assert entry.port == 8000
        assert entry.timeout == 30  # default

    def test_multiple_routes(self) -> None:
        cfg = _cfg({
            "api.localhost": 8000,
            "app.localhost": 3000,
            "db.localhost": 5432,
        })
        table = RouteTable.from_config(cfg)

        assert table.get("api.localhost") is not None
        assert table.get("app.localhost") is not None
        assert table.get("db.localhost") is not None

    def test_extended_route_with_timeout(self) -> None:
        cfg = _cfg({"api.localhost": {"port": 8000, "timeout": 120}})
        table = RouteTable.from_config(cfg)

        entry = table.get("api.localhost")
        assert entry is not None
        assert entry.timeout == 120

    def test_domains_are_normalised(self) -> None:
        cfg = _cfg({"API.Localhost": 8000})
        table = RouteTable.from_config(cfg)

        # The stored key should be normalised.
        entry = table.get("api.localhost")
        assert entry is not None
        assert entry.domain == "api.localhost"


# ===================================================================
# get — case-insensitive & trailing dot
# ===================================================================


class TestGet:
    """Route lookup semantics."""

    def test_case_insensitive_lookup(self) -> None:
        table = RouteTable.from_config(_cfg({"api.localhost": 8000}))
        assert table.get("API.LOCALHOST") is not None
        assert table.get("Api.Localhost") is not None

    def test_trailing_dot_ignored(self) -> None:
        table = RouteTable.from_config(_cfg({"api.localhost": 8000}))
        assert table.get("api.localhost.") is not None

    def test_mixed_case_and_trailing_dot(self) -> None:
        table = RouteTable.from_config(_cfg({"api.localhost": 8000}))
        assert table.get("API.LOCALHOST.") is not None

    def test_miss_returns_none(self) -> None:
        table = RouteTable.from_config(_cfg({"api.localhost": 8000}))
        assert table.get("unknown.localhost") is None

    def test_empty_table_returns_none(self) -> None:
        table = RouteTable()
        assert table.get("anything") is None


# ===================================================================
# snapshot
# ===================================================================


class TestSnapshot:
    """snapshot() returns an isolated copy."""

    def test_returns_all_entries(self) -> None:
        cfg = _cfg({"api.localhost": 8000, "app.localhost": 3000})
        table = RouteTable.from_config(cfg)

        snap = table.snapshot()
        assert len(snap) == 2
        assert "api.localhost" in snap
        assert "app.localhost" in snap

    def test_snapshot_is_isolated_from_updates(self) -> None:
        cfg1 = _cfg({"api.localhost": 8000})
        table = RouteTable.from_config(cfg1)
        snap = table.snapshot()

        # Mutate the table.
        cfg2 = _cfg({"api.localhost": 8000, "new.localhost": 3000})
        table.update(cfg2)

        # The snapshot should NOT contain the new route.
        assert "new.localhost" not in snap
        assert len(snap) == 1

    def test_empty_table_snapshot(self) -> None:
        table = RouteTable()
        snap = table.snapshot()
        assert len(snap) == 0


# ===================================================================
# update & diff
# ===================================================================


class TestUpdateAndDiff:
    """update() atomically replaces the table and returns a diff."""

    def test_add_route(self) -> None:
        table = RouteTable.from_config(_cfg({"api.localhost": 8000}))
        diff = table.update(
            _cfg({"api.localhost": 8000, "app.localhost": 3000})
        )

        assert diff.added == frozenset({"app.localhost"})
        assert diff.removed == frozenset()
        assert diff.changed == frozenset()
        assert diff.has_changes

    def test_remove_route(self) -> None:
        table = RouteTable.from_config(
            _cfg({"api.localhost": 8000, "app.localhost": 3000})
        )
        diff = table.update(_cfg({"api.localhost": 8000}))

        assert diff.added == frozenset()
        assert diff.removed == frozenset({"app.localhost"})
        assert diff.changed == frozenset()
        assert diff.has_changes

    def test_change_port(self) -> None:
        table = RouteTable.from_config(_cfg({"api.localhost": 8000}))
        diff = table.update(_cfg({"api.localhost": 9000}))

        assert diff.changed == frozenset({"api.localhost"})
        assert diff.added == frozenset()
        assert diff.removed == frozenset()
        assert diff.has_changes

    def test_change_timeout(self) -> None:
        table = RouteTable.from_config(
            _cfg({"api.localhost": {"port": 8000, "timeout": 30}})
        )
        diff = table.update(
            _cfg({"api.localhost": {"port": 8000, "timeout": 120}})
        )

        assert diff.changed == frozenset({"api.localhost"})
        assert diff.has_changes

    def test_no_changes(self) -> None:
        cfg = _cfg({"api.localhost": 8000})
        table = RouteTable.from_config(cfg)
        diff = table.update(cfg)

        assert diff.added == frozenset()
        assert diff.removed == frozenset()
        assert diff.changed == frozenset()
        assert not diff.has_changes

    def test_complex_diff(self) -> None:
        """Add, remove, and change routes simultaneously."""
        table = RouteTable.from_config(
            _cfg({
                "api.localhost": 8000,
                "app.localhost": 3000,
                "db.localhost": 5432,
            })
        )
        diff = table.update(
            _cfg({
                "api.localhost": 9000,  # changed port
                "app.localhost": 3000,  # unchanged
                "new.localhost": 4000,  # added
                # db.localhost removed
            })
        )

        assert diff.added == frozenset({"new.localhost"})
        assert diff.removed == frozenset({"db.localhost"})
        assert diff.changed == frozenset({"api.localhost"})
        assert diff.has_changes

    def test_update_reflects_in_get(self) -> None:
        table = RouteTable.from_config(_cfg({"api.localhost": 8000}))
        table.update(_cfg({"api.localhost": 9000}))

        entry = table.get("api.localhost")
        assert entry is not None
        assert entry.port == 9000

    def test_update_removes_old_routes(self) -> None:
        table = RouteTable.from_config(
            _cfg({"api.localhost": 8000, "old.localhost": 3000})
        )
        table.update(_cfg({"api.localhost": 8000}))

        assert table.get("old.localhost") is None


# ===================================================================
# RouteEntry
# ===================================================================


class TestRouteEntry:
    """RouteEntry is a frozen dataclass."""

    def test_equality(self) -> None:
        a = RouteEntry(domain="api.localhost", port=8000, timeout=30)
        b = RouteEntry(domain="api.localhost", port=8000, timeout=30)
        assert a == b

    def test_inequality_port(self) -> None:
        a = RouteEntry(domain="api.localhost", port=8000, timeout=30)
        b = RouteEntry(domain="api.localhost", port=9000, timeout=30)
        assert a != b

    def test_inequality_timeout(self) -> None:
        a = RouteEntry(domain="api.localhost", port=8000, timeout=30)
        b = RouteEntry(domain="api.localhost", port=8000, timeout=60)
        assert a != b

    def test_frozen(self) -> None:
        entry = RouteEntry(domain="api.localhost", port=8000, timeout=30)
        with pytest.raises(AttributeError):
            entry.port = 9000  # type: ignore[misc]


# ===================================================================
# RouteTableDiff
# ===================================================================


class TestRouteTableDiff:
    """RouteTableDiff is a frozen dataclass with a has_changes property."""

    def test_empty_diff(self) -> None:
        diff = RouteTableDiff()
        assert not diff.has_changes
        assert diff.added == frozenset()
        assert diff.removed == frozenset()
        assert diff.changed == frozenset()

    def test_has_changes_added(self) -> None:
        diff = RouteTableDiff(added=frozenset({"x"}))
        assert diff.has_changes

    def test_has_changes_removed(self) -> None:
        diff = RouteTableDiff(removed=frozenset({"x"}))
        assert diff.has_changes

    def test_has_changes_changed(self) -> None:
        diff = RouteTableDiff(changed=frozenset({"x"}))
        assert diff.has_changes

    def test_frozen(self) -> None:
        diff = RouteTableDiff()
        with pytest.raises(AttributeError):
            diff.added = frozenset({"x"})  # type: ignore[misc]


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Miscellaneous edge-case coverage."""

    def test_duplicate_domain_different_case_in_config(self) -> None:
        """If a config somehow has the same domain in different cases,
        the last one wins after normalisation.
        """
        # Build config with two routes whose domains normalise to the same key.
        r1 = RouteConfig(domain="api.localhost", port=8000)
        r2 = RouteConfig(domain="API.localhost", port=9000)
        cfg = PortmanConfig(proxy_port=9090, routes=(r1, r2))

        table = RouteTable.from_config(cfg)
        entry = table.get("api.localhost")
        assert entry is not None
        # The second route should overwrite the first.
        assert entry.port == 9000

    def test_from_config_on_fresh_instance(self) -> None:
        """from_config returns a new table, not a mutated one."""
        cfg = _cfg({"a.local": 1000})
        t1 = RouteTable.from_config(cfg)
        t2 = RouteTable.from_config(cfg)

        assert t1 is not t2
        assert t1.get("a.local") == t2.get("a.local")

    def test_multiple_sequential_updates(self) -> None:
        table = RouteTable.from_config(_cfg({"a.local": 1000}))

        diff1 = table.update(_cfg({"a.local": 1000, "b.local": 2000}))
        assert diff1.added == frozenset({"b.local"})

        diff2 = table.update(_cfg({"b.local": 2000, "c.local": 3000}))
        assert diff2.added == frozenset({"c.local"})
        assert diff2.removed == frozenset({"a.local"})

        assert table.get("a.local") is None
        assert table.get("b.local") is not None
        assert table.get("c.local") is not None
