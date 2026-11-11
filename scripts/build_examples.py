from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_qa.runner import run_agent  # noqa: E402

CASES = [
    ("01-clear", [], ROOT / "data"),
    ("02-conflict", [], ROOT / "data"),
    ("03-paraphrase", [], ROOT / "data"),
    ("04-out-of-corpus", [], ROOT / "data"),
    ("05-followup", [], ROOT / "data"),
    ("06-tool-failure", ["search_docs:2"], ROOT / "data"),
    ("07-resolved-conflict", [], ROOT / "data"),
    ("08-doc-updated", [], ROOT / "examples" / "08-doc-updated" / "data"),
    ("09-tool-recovery", ["search_docs:1"], ROOT / "data"),
    ("10-single-policy", [], ROOT / "data"),
]


def main() -> None:
    for example, faults, data_dir in CASES:
        example_dir = ROOT / "examples" / example
        for name in ("output.json", "trace.json"):
            (example_dir / name).unlink(missing_ok=True)
        command = (
            f"python3 run.py run --input examples/{example}/input.json "
            f"--data-dir {data_dir.relative_to(ROOT)} --state-dir examples/{example} "
            f"--engine offline --now 2026-11-10T09:00:00+08:00"
        )
        if faults:
            command += " " + " ".join(f"--fault {fault}" for fault in faults)
        output, _ = run_agent(
            input_path=example_dir / "input.json",
            data_dir=data_dir,
            state_dir=example_dir,
            engine_name="offline",
            now="2026-11-10T09:00:00+08:00",
            faults=faults,
        )
        manifest = {
            "command": command,
            "engine": "offline",
            "model": "reference-policy",
            "faults": faults,
            "expected": output["answer_status"],
            "citations": [item["doc_id"] for item in output["citations"]],
        }
        (example_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(example, output["answer_status"])


if __name__ == "__main__":
    main()
