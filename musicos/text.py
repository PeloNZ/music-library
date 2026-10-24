"""Text that is safe to print and to write as one log line."""

import re


def printable(text: str) -> str:
    """Control and line separator characters would act on the terminal or end a log line."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]", "?", text)
