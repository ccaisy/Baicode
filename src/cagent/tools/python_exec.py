"""Local Python execution tool: subprocess + 10s timeout."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TIMEOUT_SECONDS = 10
WORKSPACE_DIR = Path(".workspace")
TEMP_SCRIPT = WORKSPACE_DIR / "temp_exec.py"


def run_python(code: str) -> dict:
    WORKSPACE_DIR.mkdir(exist_ok=True)
    TEMP_SCRIPT.write_text(code, encoding="utf-8")

    try:
        proc = subprocess.run(
            [sys.executable, str(TEMP_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr_partial = exc.stderr or ""
        marker = f"TIMEOUT after {TIMEOUT_SECONDS}s"
        stderr = f"{stderr_partial}\n{marker}" if stderr_partial else marker
        return {"stdout": stdout, "stderr": stderr, "returncode": -1}
