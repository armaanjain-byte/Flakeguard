# v0.1.0 Release Readiness

Date: 2026-06-02

## Hosts Recommendation

Recommendation: Option 2, keep `hosts.py` as an experimental feature.

Rationale:

- `*.localhost` removes the normal need for hosts file modification.
- Hosts file edits add OS-specific behavior, privilege requirements, and support
  cost that should not define the MVP.
- Removing the module entirely would be a public CLI break for users who already
  tried it.
- Keeping it clearly optional preserves backward compatibility while keeping the
  core workflow simple.

Core functionality works without `hosts.py`: `portman start`, `portman list`,
HTTP proxying, WebSocket proxying, route reloads, and config validation all use
the config file and route table only.

## CI Enforcement

`.github/workflows/test.yml` now runs:

- `ruff check src tests scripts`
- `mypy src`
- `pytest --cov=portman --cov-report=term-missing --cov-report=xml`

The workflow has no `continue-on-error` settings, so failures block the job.
It runs on Python 3.10, 3.11, 3.12, and 3.13, matching the package's
`requires-python = ">=3.10"` lower bound and current supported release range.
Coverage XML is uploaded as a workflow artifact.

## RouteTable and Watcher Audit

Implementation and documentation now agree:

- `RouteTable.update()` builds a complete replacement map, swaps it under a
  short lock, and returns a diff.
- `ConfigWatcher` debounces config file changes and calls `RouteTable.update()`
  only after successful config validation.
- Failed reloads keep the previous route table active.

No code fix was needed for the route reload model.

## Release Blockers

- None known after this pass, assuming CI runs in a clean environment with
  dependencies installed.

## Local Verification

Verified on 2026-06-02:

- `python -m ruff check src tests scripts --no-cache` passed.
- `python -m mypy --no-incremental src` passed.
- `python -m pytest --cov=portman --cov-report=term-missing --cov-report=xml`
  passed with 142 tests and 90% total coverage.

The sandboxed pytest run could not use temporary directories on Windows, so the
pytest verification was run with normal filesystem access.

## Medium Priority

- Consider publishing packaging smoke tests in CI later, such as building a
  wheel and installing it in a fresh virtual environment.
- Consider adding an explicit Python upper-bound policy if future interpreters
  expose dependency compatibility issues.

## Low Priority

- Add real-world benchmark numbers to the README after testing against a stable
  local upstream.
- Add an example for a frontend/API/admin service stack if the project wants a
  more guided tutorial.

## Go/No-Go

Go for v0.1.0 after CI passes on the supported Python matrix.

The project is appropriately scoped for an MVP: configuration loading, route
lookup, HTTP proxying, WebSocket proxying, health checks, hot reloads, tests,
CI enforcement, and basic release documentation are present without adding new
product surface area.
