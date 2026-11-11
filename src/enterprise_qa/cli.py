from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .miniagent import write_json
from .runner import run_agent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="企业知识问答 Agent（校招项目 demo）")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="回答一次知识问题")
    run.add_argument("--input", required=True, help="请求 JSON")
    run.add_argument("--data-dir", default="data", help="合成文档目录")
    run.add_argument("--state-dir", default=".runs/latest", help="状态与输出目录")
    run.add_argument("--engine", choices=["offline", "live", "opencode-local"], default="offline")
    run.add_argument("--provider", default="opencode-go")
    run.add_argument("--model", default="deepseek-v4.1-flash")
    run.add_argument("--cli-path")
    run.add_argument("--max-context-chars", type=int, default=14000)
    run.add_argument("--now", help="固定当前时间，ISO 8601")
    run.add_argument("--fault", action="append", default=[], help="注入工具失败，如 search_docs:2")
    run.add_argument("--max-steps", type=int, default=12)
    run.add_argument("--max-tool-calls", type=int, default=20)
    run.add_argument("--run-id")
    run.add_argument("--output", help="输出 JSON 路径，默认 state-dir/output.json")
    run.add_argument("--trace", help="Trace JSON 路径，默认 state-dir/trace.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 2
    try:
        output, trace = run_agent(
            input_path=args.input,
            data_dir=args.data_dir,
            state_dir=args.state_dir,
            engine_name=args.engine,
            now=args.now,
            faults=args.fault,
            max_steps=args.max_steps,
            max_tool_calls=args.max_tool_calls,
            run_id=args.run_id,
            provider=args.provider,
            model=args.model,
            cli_path=args.cli_path,
            max_context_chars=args.max_context_chars,
        )
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output) if args.output else Path(args.state_dir) / "output.json"
    trace_path = Path(args.trace) if args.trace else Path(args.state_dir) / "trace.json"
    write_json(output_path, output)
    write_json(trace_path, trace)
    print(
        json.dumps(
            {
                "status": output["status"],
                "answer_status": output["answer_status"],
                "answer": output["answer"],
                "citations": [item.get("doc_id") for item in output["citations"]],
                "conflict": output["conflict"],
                "output": str(output_path),
                "trace": str(trace_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if output["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
