# Flakeguard

Detect flaky tests, recurring CI failures, and hidden reliability problems before they destroy trust in your pipeline.

## Why?

Every engineering team eventually reaches the same point:

```text
CI failed.
Rerun.
Passed.
Merge anyway.
```

Over time:

* Developers stop trusting test failures.
* CI becomes noise instead of signal.
* Flaky tests accumulate.
* Real regressions get ignored.
* Engineering time gets wasted investigating the wrong failures.

Modern CI systems generate huge amounts of data:

* GitHub Actions logs
* JUnit reports
* Pytest results
* Test durations
* Failure histories

Most teams never analyze that history.

Flakeguard turns historical CI data into actionable reliability insights.

---

## What Flakeguard Does

### Detect Flaky Tests

Identify tests that repeatedly alternate between:

```text
PASS
FAIL
PASS
FAIL
```

without meaningful code changes.

---

### Cluster Recurring Failures

Group failures by:

* stack traces
* exception types
* test names
* failure patterns

Instead of investigating the same failure 50 times, investigate it once.

---

### CI Health Reports

Generate reports showing:

* most flaky tests
* most expensive failures
* failure frequency trends
* recurring failure clusters

---

### Root Cause Heuristics

Flag likely causes such as:

* timing issues
* async race conditions
* network dependencies
* shared state contamination
* environment instability

---

## Example

```bash
flakeguard analyze
```

Output:

```text
Top Flaky Tests
----------------

test_login.py
Flakiness Score: 0.83

Observed:
PASS FAIL PASS PASS FAIL

Likely Cause:
Network dependency


Failure Cluster #12
-------------------

Occurrences: 47

Exception:
TimeoutError

Affected Tests:
test_login
test_signup
test_checkout

Likely Cause:
Database startup race
```

---

## MVP Roadmap

### Phase 1

* Parse GitHub Actions history
* Parse JUnit XML
* Store historical test results
* Detect flaky tests

### Phase 2

* Failure clustering
* CI health reports
* Trend analysis

### Phase 3

* GitHub Action integration
* Pull request summaries

### Phase 4

* Failure similarity search
* Root-cause recommendations
* ML-assisted failure classification

---

## Goals

Flakeguard is not:

* another test runner
* another dashboard
* another AI wrapper

Flakeguard focuses on one problem:

> Turning noisy CI history into reliable engineering signals.

---

## Status

Early development.
