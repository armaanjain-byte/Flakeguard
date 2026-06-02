"""Lightweight Portman throughput and latency benchmark.

Run Portman and an upstream service first, then point this script at the
Portman listener. It intentionally uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import http.client
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Result:
    latency_ms: float
    status: int | None = None
    error: str | None = None


def _request(
    connect_host: str,
    port: int,
    host_header: str,
    path: str,
    timeout: float,
) -> Result:
    start = time.perf_counter()
    conn: http.client.HTTPConnection | None = None
    try:
        conn = http.client.HTTPConnection(connect_host, port, timeout=timeout)
        conn.request(
            "GET",
            path,
            headers={"Host": host_header, "Connection": "close"},
        )
        response = conn.getresponse()
        response.read()
        latency_ms = (time.perf_counter() - start) * 1000
        return Result(latency_ms=latency_ms, status=response.status)
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return Result(latency_ms=latency_ms, error=str(exc))
    finally:
        if conn is not None:
            conn.close()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure Portman request throughput and latency."
    )
    parser.add_argument(
        "--connect-host",
        default="127.0.0.1",
        help="Address where Portman is listening.",
    )
    parser.add_argument("--port", type=int, default=8080, help="Portman port.")
    parser.add_argument(
        "--host",
        default="api.localhost",
        help="Host header routed by Portman.",
    )
    parser.add_argument("--path", default="/", help="Request path.")
    parser.add_argument(
        "--requests",
        type=int,
        default=1000,
        help="Total number of requests to send.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help="Number of concurrent worker threads.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-request timeout in seconds.",
    )
    args = parser.parse_args()

    if args.requests < 1:
        parser.error("--requests must be at least 1")
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.port < 1 or args.port > 65_535:
        parser.error("--port must be between 1 and 65535")
    if not args.path.startswith("/"):
        parser.error("--path must start with /")

    return args


def main() -> None:
    args = _parse_args()
    worker_count = min(args.concurrency, args.requests)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _request,
                args.connect_host,
                args.port,
                args.host,
                args.path,
                args.timeout,
            )
            for _ in range(args.requests)
        ]
        results = [future.result() for future in as_completed(futures)]
    elapsed = time.perf_counter() - started

    latencies = [result.latency_ms for result in results]
    errors = [result for result in results if result.error is not None]
    status_counts: dict[int, int] = {}
    for result in results:
        if result.status is not None:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1

    print(f"Requests:     {len(results)}")
    print(f"Concurrency:  {worker_count}")
    print(f"Elapsed:      {elapsed:.2f}s")
    print(f"Throughput:   {len(results) / elapsed:.2f} req/s")
    print(f"Errors:       {len(errors)}")
    print(f"Status codes: {dict(sorted(status_counts.items()))}")
    print(f"Mean latency: {statistics.fmean(latencies):.2f} ms")
    print(f"Median:       {statistics.median(latencies):.2f} ms")
    print(f"P95:          {_percentile(latencies, 0.95):.2f} ms")
    print(f"P99:          {_percentile(latencies, 0.99):.2f} ms")

    if errors:
        print(f"First error:  {errors[0].error}")


if __name__ == "__main__":
    main()
