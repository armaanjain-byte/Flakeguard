"""Tests for portman.watcher — Phase 5."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from watchdog.events import FileModifiedEvent

from portman.config import PortmanConfig
from portman.route_table import RouteTable, RouteTableDiff
from portman.watcher import ConfigWatcher

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_diff(has_changes: bool = True) -> RouteTableDiff:
    if not has_changes:
        return RouteTableDiff(
            added=frozenset(), removed=frozenset(), changed=frozenset()
        )
    return RouteTableDiff(
        added=frozenset({"test.localhost"}),
        removed=frozenset(),
        changed=frozenset(),
    )


# ===================================================================
# Tests
# ===================================================================


class TestConfigWatcher:
    """Test the watchdog event handler."""

    def test_ignores_directories(self, tmp_path: Path) -> None:
        table = MagicMock(spec=RouteTable)
        watcher = ConfigWatcher(tmp_path / "portman.yml", table)

        event = FileModifiedEvent(str(tmp_path / "portman.yml"))
        event.is_directory = True

        watcher.on_modified(event)

        assert watcher._timer is None

    def test_ignores_unrelated_files(self, tmp_path: Path) -> None:
        table = MagicMock(spec=RouteTable)
        config_file = tmp_path / "portman.yml"
        watcher = ConfigWatcher(config_file, table)

        # Event for a different file
        event = FileModifiedEvent(str(tmp_path / "other.yml"))

        watcher.on_modified(event)

        assert watcher._timer is None

    def test_debounces_multiple_events(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "portman.yml"
        config_file.write_text(
            "proxy_port: 8080\nroutes:\n  api.localhost: 8000\n"
        )

        table = MagicMock(spec=RouteTable)
        table.update.return_value = _dummy_diff()

        # Mock config load to just return a dummy
        mock_load = MagicMock(return_value=PortmanConfig(proxy_port=8080, routes=()))
        monkeypatch.setattr("portman.watcher.load", mock_load)

        watcher = ConfigWatcher(config_file, table)

        event = FileModifiedEvent(str(config_file))

        # Trigger it 3 times quickly
        watcher.on_modified(event)
        timer1 = watcher._timer
        assert timer1 is not None

        watcher.on_modified(event)
        timer2 = watcher._timer
        assert timer2 is not timer1
        assert timer1.finished.is_set()  # Cancelled

        watcher.on_modified(event)
        timer3 = watcher._timer
        assert timer3 is not timer2

        # Wait for timer to finish
        assert timer3 is not None
        timer3.join(timeout=1.0)

        # Should only load and update once
        mock_load.assert_called_once_with(config_file.absolute())
        table.update.assert_called_once()

    def test_reloads_config_on_change_logging_diff(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO)
        config_file = tmp_path / "portman.yml"
        config_file.write_text(
            "proxy_port: 8080\nroutes:\n  api.localhost: 8000\n"
        )

        table = MagicMock(spec=RouteTable)
        table.update.return_value = RouteTableDiff(
            added=frozenset({"new.localhost"}),
            removed=frozenset({"old.localhost"}),
            changed=frozenset({"changed.localhost"}),
        )

        mock_load = MagicMock(return_value=PortmanConfig(proxy_port=8080, routes=()))
        monkeypatch.setattr("portman.watcher.load", mock_load)

        watcher = ConfigWatcher(config_file, table)

        watcher._reload()

        assert "Config reloaded successfully." in caplog.text
        assert "Added routes: new.localhost" in caplog.text
        assert "Removed routes: old.localhost" in caplog.text
        assert "Changed routes: changed.localhost" in caplog.text

    def test_logs_when_no_changes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO)
        config_file = tmp_path / "portman.yml"

        table = MagicMock(spec=RouteTable)
        table.update.return_value = _dummy_diff(has_changes=False)

        mock_load = MagicMock(return_value=PortmanConfig(proxy_port=8080, routes=()))
        monkeypatch.setattr("portman.watcher.load", mock_load)

        watcher = ConfigWatcher(config_file, table)
        watcher._reload()

        assert "Config reloaded, but no routes changed." in caplog.text

    def test_keeps_old_config_on_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from portman.config import ConfigError

        caplog.set_level(logging.ERROR)
        config_file = tmp_path / "portman.yml"

        table = MagicMock(spec=RouteTable)

        mock_load = MagicMock(side_effect=ConfigError("Invalid syntax"))
        monkeypatch.setattr("portman.watcher.load", mock_load)

        watcher = ConfigWatcher(config_file, table)
        watcher._reload()

        assert (
            "Failed to reload config (keeping old config): Invalid syntax"
            in caplog.text
        )
        table.update.assert_not_called()

    def test_keeps_old_config_on_unexpected_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.ERROR)
        config_file = tmp_path / "portman.yml"

        table = MagicMock(spec=RouteTable)

        mock_load = MagicMock(side_effect=ValueError("Boom!"))
        monkeypatch.setattr("portman.watcher.load", mock_load)

        watcher = ConfigWatcher(config_file, table)
        watcher._reload()

        assert (
            "Unexpected error reloading config (keeping old config): Boom!"
            in caplog.text
        )
        table.update.assert_not_called()
