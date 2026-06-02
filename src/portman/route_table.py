"""In-memory route table with atomic updates and async-safe reads.

The ``RouteTable`` is the single source of truth that maps normalised
domain names to ``RouteEntry`` records.  It is built from a
``PortmanConfig`` via ``RouteTable.from_config`` and can be atomically
refreshed with ``update``, which returns a ``RouteTableDiff`` describing
exactly what changed.

Design notes
~~~~~~~~~~~~
* **Case-insensitive & trailing-dot-agnostic** — all domain keys are
  normalised to lowercase with trailing dots stripped before storage or
  lookup.
* **Atomic updates** — ``update`` replaces the internal mapping in a
  single reference swap so concurrent readers never observe a partial
  state.
* **Async-safe** — because CPython's GIL guarantees atomic reference
  assignment, the table is safe for use across ``asyncio`` tasks without
  an explicit lock.  ``snapshot`` returns a frozen copy so callers can
  iterate without races.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from portman.config import PortmanConfig


# ---------------------------------------------------------------------------
# Route entry (plain dataclass, not Pydantic — no validation needed here)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteEntry:
    """A resolved route ready for the proxy layer.

    Attributes:
        domain: Normalised domain (lowercase, no trailing dot).
        port: Target port on ``localhost``.
        timeout: Per-route timeout in seconds.
    """

    domain: str
    port: int
    timeout: int


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteTableDiff:
    """Describes changes between two snapshots of the route table.

    All sets contain normalised domain strings.

    Attributes:
        added: Domains that are new.
        removed: Domains that were deleted.
        changed: Domains whose port or timeout changed.
    """

    added: frozenset[str] = field(default_factory=frozenset)
    removed: frozenset[str] = field(default_factory=frozenset)
    changed: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_changes(self) -> bool:
        """Return ``True`` if the diff is non-empty."""
        return bool(self.added or self.removed or self.changed)


# ---------------------------------------------------------------------------
# Domain normalisation
# ---------------------------------------------------------------------------


def _normalise_domain(domain: str) -> str:
    """Lowercase the domain and strip any trailing dot."""
    return domain.lower().rstrip(".")


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------


class RouteTable:
    """Thread-safe, atomically-updatable mapping of domains → route entries.

    Typical lifecycle::

        cfg = portman.config.load(path)
        table = RouteTable.from_config(cfg)
        entry = table.get("api.localhost")

        # On config reload:
        new_cfg = portman.config.load(path)
        diff = table.update(new_cfg)
    """

    __slots__ = ("_lock", "_routes")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._routes: dict[str, RouteEntry] = {}

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, config: PortmanConfig) -> RouteTable:
        """Build a new ``RouteTable`` from a validated configuration."""
        table = cls()
        table._routes = cls._build_map(config)
        return table

    # -- lookups ------------------------------------------------------------

    def get(self, domain: str) -> RouteEntry | None:
        """Look up a route by domain name.

        The lookup is case-insensitive and ignores trailing dots.
        Returns ``None`` when no route matches.
        """
        key = _normalise_domain(domain)
        # dict.get is atomic under the GIL — no lock needed for reads.
        return self._routes.get(key)

    def snapshot(self) -> Mapping[str, RouteEntry]:
        """Return an immutable point-in-time copy of the route table.

        The returned mapping will not reflect later ``update`` calls.
        """
        # Take the lock so we copy a consistent reference.
        with self._lock:
            return dict(self._routes)

    # -- mutations ----------------------------------------------------------

    def update(self, config: PortmanConfig) -> RouteTableDiff:
        """Atomically replace the route table from *config*.

        Returns a ``RouteTableDiff`` describing what changed.
        """
        new_map = self._build_map(config)

        with self._lock:
            old_map = self._routes
            self._routes = new_map

        return self._diff(old_map, new_map)

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _build_map(config: PortmanConfig) -> dict[str, RouteEntry]:
        """Convert a ``PortmanConfig`` into the internal dict."""
        result: dict[str, RouteEntry] = {}
        for route in config.routes:
            key = _normalise_domain(route.domain)
            result[key] = RouteEntry(
                domain=key,
                port=route.port,
                timeout=route.timeout,
            )
        return result

    @staticmethod
    def _diff(
        old: dict[str, RouteEntry],
        new: dict[str, RouteEntry],
    ) -> RouteTableDiff:
        """Compute the diff between two internal maps."""
        old_keys = set(old)
        new_keys = set(new)

        added = frozenset(new_keys - old_keys)
        removed = frozenset(old_keys - new_keys)

        changed: set[str] = set()
        for key in old_keys & new_keys:
            if old[key] != new[key]:
                changed.add(key)

        return RouteTableDiff(
            added=added,
            removed=removed,
            changed=frozenset(changed),
        )
