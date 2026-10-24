"""Start, done and failure lines for a command that changes files.

The lines go to `musicos-activity.log` as they happen, so `tail -f` follows a
run. A failure also goes to `changes.jsonl`, because the command may have
changed some files before it stopped.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from musicos.changelog import record, stamp

Clock = Callable[[], datetime]


class Trace:
    def __init__(self, logs: Path, now: Clock, command: str, subject: str) -> None:
        self.logs = logs
        self.now = now
        self.command = command
        self.subject = subject

    def _line(self, what: str, detail: str, when: datetime) -> None:
        text = f"{stamp(when)} {self.command} {self.subject} {what}"
        self.logs.mkdir(parents=True, exist_ok=True)
        with (self.logs / "musicos-activity.log").open("a") as log:
            log.write(f"{text} {detail}".rstrip() + "\n")

    def start(self, detail: str = "") -> None:
        self._line("start", detail, self.now())

    def done(self, detail: str = "") -> None:
        self._line("done", detail, self.now())

    def fail(self, error: str) -> None:
        when = self.now()
        self._line("FAIL", error, when)
        record(
            self.logs / "changes.jsonl",
            "failed",
            when,
            command=self.command,
            subject=self.subject,
            error=error,
        )
