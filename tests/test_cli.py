"""Tests for portman.cli — Phase 7."""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from typer.testing import CliRunner

from portman.cli import app
from portman.config import ConfigError, PortmanConfig, RouteConfig

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    v = version("portman")
    assert f"Portman {v}" in result.stdout


class TestStartCommand:
    def test_start_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "portman.yml"
        config_path.write_text("proxy_port: 8080\nroutes:\n  api.local: 8000\n")

        mock_load = MagicMock()
        mock_load.return_value = PortmanConfig(
            proxy_port=8080, routes=(RouteConfig(domain="api.local", port=8000),)
        )
        monkeypatch.setattr("portman.cli.load", mock_load)

        mock_route_table = MagicMock()
        mock_from_config = MagicMock(return_value=mock_route_table)
        monkeypatch.setattr("portman.cli.RouteTable.from_config", mock_from_config)

        mock_observer = MagicMock()
        mock_start_watcher = MagicMock(return_value=mock_observer)
        monkeypatch.setattr("portman.cli.start_watcher", mock_start_watcher)

        mock_aio_app = MagicMock()
        mock_create_app = MagicMock(return_value=mock_aio_app)
        monkeypatch.setattr("portman.cli.create_app", mock_create_app)

        mock_run_app = MagicMock()
        monkeypatch.setattr("portman.cli.web.run_app", mock_run_app)

        result = runner.invoke(app, ["start", "--config", str(config_path)])

        assert result.exit_code == 0
        assert "Starting Portman proxy on port 8080" in result.stdout

        mock_load.assert_called_once_with(config_path)
        mock_from_config.assert_called_once_with(mock_load.return_value)
        mock_start_watcher.assert_called_once_with(config_path, mock_route_table)
        mock_create_app.assert_called_once_with(
            mock_route_table, mock_load.return_value
        )

        mock_run_app.assert_called_once()
        assert mock_run_app.call_args[0][0] is mock_aio_app
        assert mock_run_app.call_args[1]["host"] == "127.0.0.1"
        assert mock_run_app.call_args[1]["port"] == 8080

        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once()

    def test_start_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "portman.yml"
        config_path.write_text("invalid")

        mock_load = MagicMock(side_effect=ConfigError("Invalid syntax"))
        monkeypatch.setattr("portman.cli.load", mock_load)

        result = runner.invoke(app, ["start", "--config", str(config_path)])

        assert result.exit_code == 1
        assert "Error loading configuration: Invalid syntax" in result.stdout


class TestListCommand:
    def test_list_routes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "portman.yml"
        config_path.write_text("proxy_port: 8080\nroutes:\n  api.local: 8000\n")

        mock_load = MagicMock()
        mock_load.return_value = PortmanConfig(
            proxy_port=8080,
            routes=(
                RouteConfig(domain="api.local", port=8000),
                RouteConfig(domain="db.local", port=5432),
            ),
        )
        monkeypatch.setattr("portman.cli.load", mock_load)

        async def mock_check_all(ports: set[int]) -> dict[int, bool]:
            return {8000: True, 5432: False}

        monkeypatch.setattr("portman.cli.check_all", mock_check_all)

        result = runner.invoke(app, ["list", "--config", str(config_path)])

        assert result.exit_code == 0
        assert "Portman Routes" in result.stdout
        assert "api.local" in result.stdout
        assert "8000" in result.stdout
        assert "Healthy" in result.stdout
        assert "db.local" in result.stdout
        assert "5432" in result.stdout
        assert "Unreachable" in result.stdout

    def test_list_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "portman.yml"
        config_path.write_text("invalid")

        mock_load = MagicMock(side_effect=ConfigError("File not found"))
        monkeypatch.setattr("portman.cli.load", mock_load)

        result = runner.invoke(app, ["list", "--config", str(config_path)])

        assert result.exit_code == 1
        assert "Error loading configuration: File not found" in result.stdout


class TestHostsCommand:
    def test_hosts_install_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "portman.yml"
        config_path.write_text("proxy_port: 8080\nroutes:\n  api.local: 8000\n")

        mock_load = MagicMock()
        monkeypatch.setattr("portman.cli.load", mock_load)

        mock_get_hosts_path = MagicMock(return_value=tmp_path / "hosts")
        monkeypatch.setattr("portman.hosts.get_hosts_path", mock_get_hosts_path)

        mock_install = MagicMock(return_value="content")
        monkeypatch.setattr("portman.hosts.install_hosts", mock_install)

        result = runner.invoke(app, ["hosts", "install", "--config", str(config_path)])

        assert result.exit_code == 0
        assert "Successfully installed routes into" in result.stdout
        mock_install.assert_called_once_with(
            mock_load.return_value, mock_get_hosts_path.return_value, dry_run=False
        )

    def test_hosts_install_dry_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "portman.yml"
        config_path.write_text("proxy_port: 8080\nroutes:\n  api.local: 8000\n")

        mock_load = MagicMock()
        monkeypatch.setattr("portman.cli.load", mock_load)

        mock_get_hosts_path = MagicMock(return_value=tmp_path / "hosts")
        monkeypatch.setattr("portman.hosts.get_hosts_path", mock_get_hosts_path)

        mock_install = MagicMock(return_value="mock content")
        monkeypatch.setattr("portman.hosts.install_hosts", mock_install)

        result = runner.invoke(
            app, ["hosts", "install", "--config", str(config_path), "--dry-run"]
        )

        assert result.exit_code == 0
        assert "DRY RUN:" in result.stdout
        assert "mock content" in result.stdout
        mock_install.assert_called_once_with(
            mock_load.return_value, mock_get_hosts_path.return_value, dry_run=True
        )

    def test_hosts_uninstall_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_get_hosts_path = MagicMock(return_value=tmp_path / "hosts")
        monkeypatch.setattr("portman.hosts.get_hosts_path", mock_get_hosts_path)

        mock_uninstall = MagicMock(return_value="content")
        monkeypatch.setattr("portman.hosts.uninstall_hosts", mock_uninstall)

        result = runner.invoke(app, ["hosts", "uninstall"])

        assert result.exit_code == 0
        assert "Successfully uninstalled routes from" in result.stdout
        mock_uninstall.assert_called_once_with(
            mock_get_hosts_path.return_value, dry_run=False
        )

    def test_hosts_uninstall_dry_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_get_hosts_path = MagicMock(return_value=tmp_path / "hosts")
        monkeypatch.setattr("portman.hosts.get_hosts_path", mock_get_hosts_path)

        mock_uninstall = MagicMock(return_value="mock content")
        monkeypatch.setattr("portman.hosts.uninstall_hosts", mock_uninstall)

        result = runner.invoke(app, ["hosts", "uninstall", "--dry-run"])

        assert result.exit_code == 0
        assert "DRY RUN:" in result.stdout
        assert "mock content" in result.stdout
        mock_uninstall.assert_called_once_with(
            mock_get_hosts_path.return_value, dry_run=True
        )
