#!/usr/bin/env python3
"""Run pytest fast tests — used by pre-commit hook (cross-platform)."""

import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent
venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
if not venv_python.exists():
    # Linux/macOS path
    venv_python = repo_root / ".venv" / "bin" / "python"

result = subprocess.run(
    [str(venv_python), "-m", "pytest", "-m", "fast or not slow", "--no-cov", "-q"],
    cwd=str(repo_root),
)
sys.exit(result.returncode)
