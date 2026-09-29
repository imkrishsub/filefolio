"""Run the hard-failing Node frontend tests as part of pytest (and so CI)."""

import shutil
import subprocess
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_frontend_escaping():
    result = subprocess.run(
        ["node", str(TESTS_DIR / "test_frontend_escaping.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
