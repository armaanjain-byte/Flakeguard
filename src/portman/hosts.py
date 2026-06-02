"""Manage the system hosts file for local routing."""

import os
from pathlib import Path

from portman.config import PortmanConfig

SENTINEL_START = "# --- PORTMAN MANAGED ---"
SENTINEL_END = "# --- END PORTMAN MANAGED ---"


def get_hosts_path() -> Path:
    """Get the path to the system hosts file."""
    if os.name == "nt":
        return (
            Path(os.environ.get("WINDIR", "C:\\Windows"))
            / "System32"
            / "drivers"
            / "etc"
            / "hosts"
        )
    return Path("/etc/hosts")


def _read_and_split(hosts_path: Path) -> tuple[list[str], list[str], list[str]]:
    """Read the hosts file and split it into pre-block, block, and post-block lines."""
    if not hosts_path.exists():
        return [], [], []

    content = hosts_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    pre = []
    block = []
    post = []

    state = "pre"

    for line in lines:
        if line.strip() == SENTINEL_START:
            state = "block"
            block.append(line)
        elif line.strip() == SENTINEL_END:
            block.append(line)
            state = "post"
        elif state == "pre":
            pre.append(line)
        elif state == "block":
            block.append(line)
        elif state == "post":
            post.append(line)

    return pre, block, post


def install_hosts(
    config: PortmanConfig, hosts_path: Path, dry_run: bool = False
) -> str:
    """Install portman routes into the hosts file.

    Returns the new file content as a string.
    """
    pre, _, post = _read_and_split(hosts_path)

    # Clean up trailing empty lines in pre
    while pre and not pre[-1].strip():
        pre.pop()

    new_block = [SENTINEL_START]
    for route in sorted(config.routes, key=lambda r: r.domain):
        new_block.append(f"127.0.0.1 {route.domain}")
    new_block.append(SENTINEL_END)

    new_lines = pre
    if new_lines:
        new_lines.append("")  # Ensure a blank line before the block

    new_lines.extend(new_block)

    if post:
        # Ensure a blank line after the block if there is post content
        # unless post already starts with a blank line
        if post[0].strip():
            new_lines.append("")
        new_lines.extend(post)

    # Ensure final newline
    new_lines.append("")

    new_content = "\n".join(new_lines)

    # To avoid having a leading blank line if the file was empty
    if new_content.startswith("\n"):
        new_content = new_content[1:]

    if not dry_run:
        hosts_path.write_text(new_content, encoding="utf-8")

    return new_content


def uninstall_hosts(hosts_path: Path, dry_run: bool = False) -> str:
    """Uninstall portman routes from the hosts file.

    Returns the new file content as a string.
    """
    pre, block, post = _read_and_split(hosts_path)

    if not block:
        # Nothing to uninstall, just return original content
        return hosts_path.read_text(encoding="utf-8") if hosts_path.exists() else ""

    # Clean up trailing empty lines in pre before concatenating with post
    while pre and not pre[-1].strip():
        pre.pop()

    # If post starts with empty lines, we might want to keep one
    # if there was one before, but it's safe to just join them cleanly.
    new_lines = pre
    if post:
        # Avoid double blank lines
        if new_lines and not post[0].strip():
            pass
        elif new_lines:
            new_lines.append("")
        new_lines.extend(post)

    if new_lines:
        new_lines.append("")

    new_content = "\n".join(new_lines)

    if not dry_run:
        hosts_path.write_text(new_content, encoding="utf-8")

    return new_content
