"""Local shell execution tool: subprocess shell=True + 60s timeout."""

from __future__ import annotations

import subprocess

TIMEOUT_SECONDS = 60
MAX_CHARS = 4000
HEAD_CHARS = 2000
TAIL_CHARS = 2000


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    dropped = len(text) - HEAD_CHARS - TAIL_CHARS
    return (
        f"{text[:HEAD_CHARS]}"
        f"\n...[truncated {dropped} chars]...\n"
        f"{text[-TAIL_CHARS:]}"
    )


def run_shell(command: str) -> dict:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        return {
            "stdout": _truncate(proc.stdout or ""),
            "stderr": _truncate(proc.stderr or ""),
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        stdout_partial = exc.stdout or ""
        stderr_partial = exc.stderr or ""
        if isinstance(stdout_partial, bytes):
            stdout_partial = stdout_partial.decode("utf-8", errors="replace")
        if isinstance(stderr_partial, bytes):
            stderr_partial = stderr_partial.decode("utf-8", errors="replace")
        marker = f"TIMEOUT after {TIMEOUT_SECONDS}s"
        stderr = f"{stderr_partial}\n{marker}" if stderr_partial else marker
        return {
            "stdout": _truncate(stdout_partial),
            "stderr": _truncate(stderr),
            "returncode": -1,
        }
