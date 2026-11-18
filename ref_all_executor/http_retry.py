"""Shared retry wrapper for REFALL service transports.

Every REFALL service the standing loop depends on -- REFALL AB, the coverage
service, and the Agent Canvas -- can drop out briefly: a launchd restart, a
container bounce, an OOM kill of a backend process. Without a retry those blips
raise straight through the loop's request call and terminate the whole run,
losing every in-flight conversation.

Wrap a transport with `with_retry` to make 5xx responses and raw socket errors
survivable. The final attempt is passed through unchanged so callers keep their
normal error handling: a 5xx is returned for the caller to raise on, and a
socket error is re-raised.
"""

from __future__ import annotations

import os
import time
import urllib.error
from typing import Callable

# Raw socket/DNS failures. A service that is restarting refuses connections for
# a few seconds; that is not a reason to end a multi-hour run.
TRANSIENT_EXC = (urllib.error.URLError, TimeoutError, ConnectionError, OSError)

DEFAULT_MAX_ATTEMPTS = int(os.environ.get("REFALL_HTTP_MAX_ATTEMPTS", "4"))
DEFAULT_BACKOFF_S = float(os.environ.get("REFALL_HTTP_BACKOFF_S", "3"))


def with_retry(
    transport: Callable,
    *,
    max_attempts: int | None = None,
    backoff_s: float | None = None,
    sleep: Callable[[float], None] | None = None,
    label: str = "refall",
) -> Callable:
    """Return `transport` wrapped so 5xx and socket errors retry with backoff."""
    attempts = DEFAULT_MAX_ATTEMPTS if max_attempts is None else max_attempts
    delay = DEFAULT_BACKOFF_S if backoff_s is None else backoff_s
    napper = sleep or time.sleep

    def wrapped(method, url, headers, body):
        for attempt in range(1, max(1, attempts) + 1):
            last = attempt >= max(1, attempts)
            try:
                status, raw = transport(method, url, headers, body)
            except TRANSIENT_EXC:
                if last:
                    raise
            else:
                if status < 500 or last:
                    return status, raw
            if delay:
                napper(delay * attempt)
        raise RuntimeError(f"{label}: {method} {url} exhausted {attempts} attempts")  # pragma: no cover

    return wrapped
