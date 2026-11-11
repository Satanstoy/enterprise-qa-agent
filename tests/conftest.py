from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_qa.runner import run_agent  # noqa: E402


@pytest.fixture
def run_case(tmp_path):
    def _run(example: str, *, faults=None, data_dir=None, state_dir=None):
        output, trace = run_agent(
            input_path=ROOT / "examples" / example / "input.json",
            data_dir=data_dir or (ROOT / "data"),
            state_dir=state_dir or (tmp_path / example),
            engine_name="offline",
            now="2026-11-10T09:00:00+08:00",
            faults=faults or [],
        )
        return output, trace

    return _run
