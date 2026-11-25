"""Small, credential-safe diagnostics shared by optional pipeline stages."""

import os
from pathlib import Path


def safe_error(error: Exception) -> str:
    """Do not log provider messages: they can contain keys, URLs or request data."""
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        status = getattr(getattr(error, "response", None), "status_code", None)
    suffix = f" (HTTP {status})" if isinstance(status, int) else ""
    return f"{type(error).__name__}{suffix}"


def summary(message: str) -> None:
    """Append a non-sensitive stage result to the Actions summary, best effort."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with Path(path).open("a", encoding="utf-8") as stream:
                stream.write(f"- {message}\n")
        except OSError:
            pass


def warning(message: str) -> None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning::{escaped}")
    else:
        print(f"[Warning] {message}")
    summary(f"DEGRADED: {message}")
