"""Adaptive rate limiting for LLM submissions.

Auto-calibrating mechanism that adjusts submission rate based on LLM response times.
Prevents flooding the LLM endpoint with requests faster than it can respond.
"""

import logging
import threading
import time
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger("roz.llm.rate_limiter")


@dataclass
class LatencyStats:
    """Statistics about LLM request latencies."""
    min_latency: float = 0.0
    max_latency: float = 0.0
    avg_latency: float = 0.0
    latest_latency: float = 0.0


class AdaptiveRateLimiter:
    """Adaptive rate limiter for LLM submissions.

    Tracks response times and automatically adjusts submission interval to never
    overload the LLM endpoint. Uses exponential backoff when requests are queued.
    """

    def __init__(
        self,
        min_interval_s: float = 0.5,
        max_interval_s: float = 30.0,
        queue_threshold: int = 3,
    ):
        """Initialize adaptive rate limiter.

        Args:
            min_interval_s: Minimum time between submissions (default 0.5s)
            max_interval_s: Maximum backoff interval (default 30s)
            queue_threshold: How many pending requests trigger backoff (default 3)
        """
        self.min_interval_s = min_interval_s
        self.max_interval_s = max_interval_s
        self.queue_threshold = queue_threshold

        # Current submission interval (adapts based on latency)
        self.current_interval_s = min_interval_s

        # Latency tracking
        self.latencies = deque(maxlen=10)  # Keep last 10 latencies
        self.lock = threading.Lock()

        # State tracking
        self.last_submission_time = time.time()  # Initialize to now so first request goes through immediately
        self.pending_requests = 0

        logger.info(
            f"AdaptiveRateLimiter initialized: "
            f"min={min_interval_s}s, max={max_interval_s}s, "
            f"queue_threshold={queue_threshold}"
        )

    def record_submission(self) -> None:
        """Record that a request was submitted."""
        with self.lock:
            self.last_submission_time = time.time()
            self.pending_requests += 1

    def record_completion(self, latency_s: float) -> None:
        """Record that a request completed and track latency.

        Args:
            latency_s: How long the request took in seconds
        """
        with self.lock:
            self.pending_requests = max(0, self.pending_requests - 1)
            self.latencies.append(latency_s)
            self._update_interval()

            stats = self.get_stats()
            logger.debug(
                f"Request completed in {latency_s:.1f}s. "
                f"Avg latency: {stats.avg_latency:.1f}s, "
                f"Current interval: {self.current_interval_s:.1f}s, "
                f"Pending: {self.pending_requests}"
            )

    def can_submit(self) -> bool:
        """Check if enough time has passed since last submission.

        Returns:
            True if safe to submit, False if should wait
        """
        with self.lock:
            time_since_last = time.time() - self.last_submission_time
            return time_since_last >= self.current_interval_s

    def get_wait_time(self) -> float:
        """Get how long to wait before next submission is allowed.

        Returns:
            Seconds to wait, or 0.0 if can submit now
        """
        with self.lock:
            time_since_last = time.time() - self.last_submission_time
            if time_since_last < self.current_interval_s:
                return self.current_interval_s - time_since_last
            return 0.0

    def _update_interval(self) -> None:
        """Update submission interval based on pending requests and latency."""
        # Get average latency
        if not self.latencies:
            return

        avg_latency = sum(self.latencies) / len(self.latencies)

        # Adjust interval based on queue depth
        if self.pending_requests > self.queue_threshold:
            # Queue is building up - back off exponentially
            backoff_factor = min(2.0, 1.0 + (self.pending_requests - self.queue_threshold) * 0.5)
            new_interval = min(self.max_interval_s, avg_latency * backoff_factor)
            logger.info(
                f"Queue building up ({self.pending_requests} pending). "
                f"Backing off: {self.current_interval_s:.1f}s → {new_interval:.1f}s"
            )
            self.current_interval_s = new_interval
        else:
            # No queue - set interval to just faster than observed latency
            # This allows submissions as fast as the endpoint can handle
            min_safe_interval = max(self.min_interval_s, avg_latency * 0.9)

            if min_safe_interval < self.current_interval_s:
                # Can speed up
                self.current_interval_s = max(self.min_interval_s, min_safe_interval)
                logger.info(
                    f"Queue cleared. Speeding up: interval now {self.current_interval_s:.1f}s"
                )

    def get_stats(self) -> LatencyStats:
        """Get current latency statistics.

        Returns:
            LatencyStats object with min, max, avg latencies
        """
        with self.lock:
            if not self.latencies:
                return LatencyStats()

            latencies = list(self.latencies)
            return LatencyStats(
                min_latency=min(latencies),
                max_latency=max(latencies),
                avg_latency=sum(latencies) / len(latencies),
                latest_latency=latencies[-1] if latencies else 0.0,
            )

    def get_queue_status(self) -> dict:
        """Get current queue status for monitoring.

        Returns:
            Dict with queue info
        """
        with self.lock:
            return {
                "pending_requests": self.pending_requests,
                "current_interval_s": self.current_interval_s,
                "queue_depth": self.pending_requests,
                "queue_threshold": self.queue_threshold,
                "backed_off": self.pending_requests > self.queue_threshold,
            }
