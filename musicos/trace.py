"""Start, done and failure lines for a command that changes files.

The lines go to `musicos-activity.log` as they happen, so `tail -f` follows a
run. A failure also goes to `changes.jsonl`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from musicos.changelog import CHANGES_LOG, append_activity, record, stamp
from musicos.text import printable

Clock = Callable[[], datetime]


class Trace:
    def __init__(
        self, logs: Path, now: Clock, command: str, subject: str, **fields: Any
    ) -> None:
        self.logs = logs
        self.now = now
        self.command = command
        self.subject = printable(subject)
        self.fields = fields

    def _line(self, what: str, detail: str, when: datetime) -> None:
        text = f"{stamp(when)} {self.command} {self.subject} {what} {detail}"
        append_activity(self.logs, text.rstrip())

    def start(self, detail: str = "") -> None:
        self._line("start", detail, self.now())

    def done(self, detail: str = "") -> None:
        self._line("done", detail, self.now())

    def fail(self, error: str) -> None:
        when = self.now()
        self._line("FAIL", error, when)
        record(
            self.logs / CHANGES_LOG,
            "failed",
            when,
            command=self.command,
            subject=self.subject,
            error=printable(error),
            **self.fields,
        )

    @contextmanager
    def guard(self) -> Iterator[None]:
        """Log any error that escapes the block, an interrupt too, then raise it on."""
        try:
            yield
        except BaseException as exc:
            self.fail(
                f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            )
            raise
