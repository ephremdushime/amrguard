from collections import deque
from threading import Lock
import time


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter.

    Provides single-instance protection for login, credential issuance, and credential
    verification. Multi-replica deployments should back this interface with shared Redis state.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check_and_record(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        """Record an attempt and return True if allowed, False if rate-limited."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= max_attempts:
                return False
            bucket.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


rate_limiter = SlidingWindowRateLimiter()
