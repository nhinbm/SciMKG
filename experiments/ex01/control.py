"""Run limits and intentional stops: each one ends a batch cleanly and leaves the cache intact."""
from __future__ import annotations

from pathlib import Path
import time


class BudgetPause(BaseException):
    """Raised before a new request when a limit is reached; no request is recorded."""
    journal_status = "paused"


class StagePause(BaseException):
    """Raised after the requested stop point; the finished stages are already on disk."""
    journal_status = "paused"

    def __init__(self, stage):
        self.stage = stage
        super().__init__(f"Stopped after stage {stage}")


class RunBudget:
    def __init__(self, max_calls=None, max_seconds=None, stop_file=None):
        if (max_calls is not None and max_calls < 0) or (max_seconds is not None and max_seconds <= 0):
            raise ValueError("Invalid call or time budget")
        self.max_calls, self.max_seconds = max_calls, max_seconds
        self.stop_file = Path(stop_file) if stop_file else None
        self.started = time.monotonic()
        self.launched = 0

    def before_launch(self):
        """Return the seconds left for the next request, or raise BudgetPause."""
        if self.stop_file and self.stop_file.exists():
            raise BudgetPause("STOP file exists; paused before a new request")
        if self.max_calls is not None and self.launched >= self.max_calls:
            raise BudgetPause(f"The batch budget of {self.max_calls} new requests has been reached")
        remaining = float("inf") if self.max_seconds is None else self.max_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise BudgetPause(f"The batch time budget of {self.max_seconds} seconds has been reached")
        self.launched += 1
        return remaining
