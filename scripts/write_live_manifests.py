from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    for directory in sorted((ROOT / "examples" / "live").iterdir()):
        if not directory.is_dir():
            continue
        trace_path = directory / "trace.json"
        output_path = directory / "output.json"
        if not trace_path.exists() or not output_path.exists():
            continue
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        output = json.loads(output_path.read_text(encoding="utf-8"))
        tools = [
            step["tool"]
            for step in trace.get("steps", [])
            if step.get("type") == "tool_result"
        ]
        context = next(
            (step for step in trace.get("steps", []) if step.get("type") == "context_stats"),
            {},
        )
        faults = ["search_docs:2"] if directory.name == "06-tool-failure" else []
        manifest = {
            "command": (
                f"python3 run.py run --input {directory.relative_to(ROOT)}/input.json "
                f"--data-dir {'examples/08-doc-updated/data' if directory.name == '08-doc-updated' else 'data'} "
                f"--state-dir {directory.relative_to(ROOT)} --engine opencode-local "
                f"--provider opencode-go --model deepseek-v4.1-flash "
                f"--now 2026-11-10T09:00:00+08:00"
                + (" --fault search_docs:2" if faults else "")
            ),
            "engine": trace.get("engine"),
            "model": trace.get("model"),
            "provider": "opencode-go",
            "real_model_call": True,
            "faults": faults,
            "expected": output.get("answer_status"),
            "citations": [item.get("doc_id") for item in output.get("citations", [])],
            "tool_sequence": tools,
            "context_stats": {k: v for k, v in context.items() if k not in ("type", "index")},
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(directory.name, output.get("answer_status"))


if __name__ == "__main__":
    main()
