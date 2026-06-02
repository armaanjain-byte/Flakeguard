"""Tests for portman.hosts — Optional Hosts Integration."""

from pathlib import Path

from portman.config import PortmanConfig, RouteConfig
from portman.hosts import SENTINEL_END, SENTINEL_START, install_hosts, uninstall_hosts


class TestInstallHosts:
    def test_install_adds_block_to_empty_file(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        config = PortmanConfig(
            proxy_port=8080,
            routes=(
                RouteConfig(domain="api.localhost", port=8000),
                RouteConfig(domain="db.localhost", port=5432),
            ),
        )

        content = install_hosts(config, hosts_file)

        assert SENTINEL_START in content
        assert "127.0.0.1 api.localhost" in content
        assert "127.0.0.1 db.localhost" in content
        assert SENTINEL_END in content

        written_content = hosts_file.read_text(encoding="utf-8")
        assert written_content == content

    def test_install_preserves_existing_content(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 localhost\n::1 localhost\n", encoding="utf-8")

        config = PortmanConfig(
            proxy_port=8080,
            routes=(RouteConfig(domain="app.localhost", port=8000),),
        )

        content = install_hosts(config, hosts_file)

        assert content.startswith("127.0.0.1 localhost\n::1 localhost\n\n# ---")
        assert "127.0.0.1 app.localhost" in content

    def test_install_is_idempotent(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")

        config = PortmanConfig(
            proxy_port=8080,
            routes=(RouteConfig(domain="app.localhost", port=8000),),
        )

        install_hosts(config, hosts_file)
        first_content = hosts_file.read_text(encoding="utf-8")

        # Install again
        install_hosts(config, hosts_file)
        second_content = hosts_file.read_text(encoding="utf-8")

        assert first_content == second_content

    def test_install_dry_run_does_not_modify_file(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")

        config = PortmanConfig(
            proxy_port=8080,
            routes=(RouteConfig(domain="app.localhost", port=8000),),
        )

        content = install_hosts(config, hosts_file, dry_run=True)

        assert "app.localhost" in content

        written_content = hosts_file.read_text(encoding="utf-8")
        assert "app.localhost" not in written_content


class TestUninstallHosts:
    def test_uninstall_removes_block(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        original = (
            "127.0.0.1 localhost\n\n"
            "# --- PORTMAN MANAGED ---\n"
            "127.0.0.1 api.localhost\n"
            "# --- END PORTMAN MANAGED ---\n\n"
            "192.168.1.1 router\n"
        )
        hosts_file.write_text(original, encoding="utf-8")

        content = uninstall_hosts(hosts_file)

        assert SENTINEL_START not in content
        assert "api.localhost" not in content
        assert content == "127.0.0.1 localhost\n\n192.168.1.1 router\n"

        written_content = hosts_file.read_text(encoding="utf-8")
        assert written_content == content

    def test_uninstall_idempotent(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")

        content = uninstall_hosts(hosts_file)

        assert content == "127.0.0.1 localhost\n"
        assert hosts_file.read_text(encoding="utf-8") == "127.0.0.1 localhost\n"

    def test_uninstall_dry_run_does_not_modify_file(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        original = (
            "127.0.0.1 localhost\n\n"
            "# --- PORTMAN MANAGED ---\n"
            "127.0.0.1 api.localhost\n"
            "# --- END PORTMAN MANAGED ---\n"
        )
        hosts_file.write_text(original, encoding="utf-8")

        content = uninstall_hosts(hosts_file, dry_run=True)

        assert "api.localhost" not in content
        assert "api.localhost" in hosts_file.read_text(encoding="utf-8")
