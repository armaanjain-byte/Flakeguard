"""Portman configuration loader.

Reads a YAML configuration file and produces a validated ``PortmanConfig``.
Every public error surfaces as a human-readable ``ConfigError`` — raw YAML
and Pydantic exceptions are never exposed to callers.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_PORT: int = 1
_MAX_PORT: int = 65_535
_DEFAULT_PROXY_PORT: int = 8080
_DEFAULT_TIMEOUT: int = 30
_MIN_TIMEOUT: int = 1
_MAX_TIMEOUT: int = 300

# RFC-952 / RFC-1123 compliant hostname label (simplified for local dev).
_DOMAIN_RE: re.Pattern[str] = re.compile(
    r"^(?!-)[a-zA-Z0-9-]{1,63}(?<!-)(\.[a-zA-Z0-9-]{1,63})*$"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised for any configuration problem.

    Attributes:
        message: Human-readable explanation of the error.
    """

    message: str

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_port(value: int, label: str) -> int:
    """Return *value* if it is a valid TCP port, else raise ``ConfigError``."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{label} must be an integer, got {type(value).__name__}")
    if value < _MIN_PORT or value > _MAX_PORT:
        raise ConfigError(
            f"{label} must be between {_MIN_PORT} and {_MAX_PORT}, got {value}"
        )
    return value


def _validate_domain(domain: str) -> str:
    """Return *domain* if it looks like a valid hostname, else raise ``ConfigError``."""
    if not _DOMAIN_RE.match(domain):
        raise ConfigError(
            f"Invalid domain '{domain}'. "
            "Domains must contain only letters, digits, hyphens, and dots, "
            "and each label must be 1-63 characters."
        )
    return domain


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RouteConfig(BaseModel, frozen=True):
    """A single route entry (always in *extended* form internally)."""

    domain: str
    port: int
    timeout: int = _DEFAULT_TIMEOUT

    @field_validator("port")
    @classmethod
    def _check_port(cls, value: int) -> int:
        return _validate_port(value, "Route port")

    @field_validator("domain")
    @classmethod
    def _check_domain(cls, value: str) -> str:
        return _validate_domain(value)

    @field_validator("timeout")
    @classmethod
    def _check_timeout(cls, value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(
                f"Timeout must be an integer, got {type(value).__name__}"
            )
        if value < _MIN_TIMEOUT or value > _MAX_TIMEOUT:
            raise ConfigError(
                f"Timeout must be between {_MIN_TIMEOUT} and {_MAX_TIMEOUT} "
                f"seconds, got {value}"
            )
        return value


class PortmanConfig(BaseModel, frozen=True):
    """Top-level validated configuration."""

    proxy_port: int = _DEFAULT_PROXY_PORT
    routes: tuple[RouteConfig, ...]

    @field_validator("proxy_port")
    @classmethod
    def _check_proxy_port(cls, value: int) -> int:
        return _validate_port(value, "proxy_port")

    @model_validator(mode="after")
    def _check_port_conflicts(self) -> PortmanConfig:
        for route in self.routes:
            if route.port == self.proxy_port:
                raise ConfigError(
                    f"Route '{route.domain}' port {route.port} conflicts "
                    f"with proxy_port ({self.proxy_port}). "
                    "Each service must listen on a unique port."
                )
        return self


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

# The raw YAML value for a single route may be:
#   simple  →  ``"api.localhost": 8000``
#   extended →  ``"api.localhost": {"port": 8000, "timeout": 60}``
_RawRouteValue = int | dict[str, Any]


def _normalise_routes(
    raw: dict[str, _RawRouteValue],
) -> list[dict[str, Any]]:
    """Convert the user-facing route mapping into a list of dicts suitable
    for constructing ``RouteConfig`` instances.
    """
    result: list[dict[str, Any]] = []
    for domain, value in raw.items():
        if isinstance(value, int) and not isinstance(value, bool):
            result.append({"domain": domain, "port": value})
        elif isinstance(value, dict):
            result.append({"domain": domain, **value})
        else:
            raise ConfigError(
                f"Route '{domain}' has an invalid value. "
                "Expected an integer port or a mapping with at least a 'port' key."
            )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load(path: Path) -> PortmanConfig:
    """Load and validate a Portman configuration file.

    Parameters:
        path: Filesystem path to a YAML configuration file.

    Returns:
        A fully validated ``PortmanConfig``.

    Raises:
        ConfigError: For *any* problem — missing file, bad YAML syntax,
            validation failures, etc.
    """
    # --- read -----------------------------------------------------------------
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    if not path.is_file():
        raise ConfigError(f"Configuration path is not a file: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration file: {exc}") from exc

    # --- parse YAML -----------------------------------------------------------
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ConfigError(
            f"Configuration file '{path.name}' contains invalid YAML. "
            "Please check the syntax."
        ) from None

    if not isinstance(raw, dict):
        raise ConfigError(
            f"Configuration file '{path.name}' must be a YAML mapping "
            "(key: value pairs) at the top level."
        )

    # --- extract & normalise --------------------------------------------------
    raw_routes: Any = raw.get("routes")
    if raw_routes is None:
        raise ConfigError("Configuration is missing the required 'routes' section.")
    if not isinstance(raw_routes, dict):
        raise ConfigError(
            "The 'routes' section must be a mapping of domain names to "
            "port numbers or route configurations."
        )
    if len(raw_routes) == 0:
        raise ConfigError(
            "The 'routes' section must contain at least one route."
        )

    try:
        normalised = _normalise_routes(raw_routes)
    except ConfigError:
        raise  # already a ConfigError — propagate as-is

    # --- build & validate models ---------------------------------------------
    proxy_port: int = raw.get("proxy_port", _DEFAULT_PROXY_PORT)

    try:
        routes = tuple(RouteConfig(**entry) for entry in normalised)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"Invalid route configuration: {exc}") from exc

    try:
        return PortmanConfig(proxy_port=proxy_port, routes=routes)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc
