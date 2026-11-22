"""Small in-memory sliding-window rate limiter (single backend process)."""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_hits: int, window_seconds: float):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record a hit for `key`; return False when the limit is exceeded."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.max_hits:
                return False
            hits.append(now)
            return True

    def blocked(self, key: str, now: float | None = None) -> bool:
        """True when `key` has already used up its hits. Does not record a hit."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            return len(hits) >= self.max_hits

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Login limiters count FAILED attempts only (see app/api/auth.py).
login_limiter = RateLimiter(max_hits=5, window_seconds=15 * 60)  # per phone/email
login_ip_limiter = RateLimiter(max_hits=30, window_seconds=15 * 60)  # per client address
register_limiter = RateLimiter(max_hits=30, window_seconds=60 * 60)  # per client address
assistant_limiter = RateLimiter(max_hits=30, window_seconds=60 * 60)
speech_token_limiter = RateLimiter(max_hits=20, window_seconds=60 * 60)
care_request_limiter = RateLimiter(max_hits=10, window_seconds=60 * 60)
# Process-local only: this state lives in one Python process, resets on restart,
# and is not shared across workers or instances. It is deliberately not distributed.
forgot_password_limiter = RateLimiter(max_hits=5, window_seconds=60 * 60)

ALL_LIMITERS = (
    login_limiter, login_ip_limiter, register_limiter, assistant_limiter, speech_token_limiter, care_request_limiter,
    forgot_password_limiter,
)
