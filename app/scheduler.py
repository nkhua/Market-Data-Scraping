from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any


class Scheduler:
    def __init__(self, frequency_seconds: int) -> None:
        self.frequency_seconds = frequency_seconds

    def run_forever(self, task: Callable[[], Any]) -> None:
        while True:
            started = datetime.utcnow()
            task()
            elapsed = (datetime.utcnow() - started).total_seconds()
            sleep_seconds = max(self.frequency_seconds - elapsed, 1)
            time.sleep(sleep_seconds)
