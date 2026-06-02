"""Configuration hot-reloader using ``watchdog``.

Watches the directory containing the configuration file for changes.
When the configuration file is modified, it debounces the events (to
handle editors that emit multiple write events or use swap files),
reloads the file via ``portman.config.load``, and atomically updates
the shared ``RouteTable``.

If the configuration is invalid, the error is logged and the old
configuration is preserved.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from portman.config import ConfigError, load

if TYPE_CHECKING:
    from portman.route_table import RouteTable

logger = logging.getLogger("portman.watcher")


class ConfigWatcher(FileSystemEventHandler):
    """Watchdog event handler for the configuration file.

    Debounces modifications to avoid spurious reloads, handles
    atomic reloading, and updates the ``RouteTable``.
    """

    def __init__(self, config_path: Path, route_table: RouteTable) -> None:
        self.config_path = config_path.absolute()
        self.route_table = route_table
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def on_modified(self, event: FileSystemEvent) -> None:
        self._trigger(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._trigger(event)

    def _trigger(self, event: FileSystemEvent) -> None:
        """Filter events and trigger the debounce timer."""
        if event.is_directory:
            return

        # event.src_path is typically a string, ensure absolute Path comparison.
        try:
            src_path = Path(event.src_path).absolute()
        except TypeError:
            return

        if src_path != self.config_path:
            return

        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(0.3, self._reload)
            self._timer.start()

    def _reload(self) -> None:
        """Perform the actual reload. Runs in the timer thread."""
        logger.info("Config file changed, reloading...")
        try:
            new_config = load(self.config_path)
            diff = self.route_table.update(new_config)

            if diff.has_changes:
                logger.info("Config reloaded successfully.")
                if diff.added:
                    logger.info("Added routes: %s", ", ".join(sorted(diff.added)))
                if diff.removed:
                    logger.info("Removed routes: %s", ", ".join(sorted(diff.removed)))
                if diff.changed:
                    logger.info("Changed routes: %s", ", ".join(sorted(diff.changed)))
            else:
                logger.info("Config reloaded, but no routes changed.")

        except ConfigError as e:
            logger.error("Failed to reload config (keeping old config): %s", e)
        except Exception as e:
            logger.error(
                "Unexpected error reloading config (keeping old config): %s", e
            )


def start_watcher(config_path: Path, route_table: RouteTable) -> Any:
    """Start watching the configuration file's parent directory.

    Returns the ``watchdog.observers.Observer`` instance. The caller
    is responsible for calling ``.stop()`` and ``.join()`` on it during
    application shutdown.
    """
    observer: Any = Observer()
    handler = ConfigWatcher(config_path, route_table)

    # Watch the directory, not the file itself. Editors often write to
    # temporary files and move them over the target file, which can
    # break file-specific watches.
    observer.schedule(handler, str(config_path.parent.absolute()), recursive=False)
    observer.start()
    return observer
