"""CLI for the product-researcher agent team.

Usage:
    python -m product_researcher.main "smart home gadgets"
    python -m product_researcher.main "eco-friendly pet products" --top 8 --out ./reports

Streams the team's progress to the terminal, then writes a Markdown report and a
JSON file of predictions. The web dashboard (product_researcher.server) uses the
same underlying event stream.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional
    pass

from .mock import run_stream_mock


async def run(category: str, top: int, output_dir: str, model: str, mock: bool = False) -> str:
    report = ""
    tag = " [MOCK]" if mock else ""
    print(f"\n🔎 Researching category: {category!r} (top {top}){tag}\n", flush=True)

    if mock:
        stream = run_stream_mock(category, top, output_dir, model)
    else:
        # Import the SDK-backed pipeline lazily so mock mode never requires
        # claude_agent_sdk to be installed.
        from .events import run_stream
        stream = run_stream(category, top, output_dir, model)
    async for ev in stream:
        kind = ev["type"]
        if kind == "subagent":
            print(f"\n  ➤ delegating to [{ev['name']}]", flush=True)
        elif kind == "tool":
            print(f"    · {ev['name']}: {ev['summary']}", flush=True)
        elif kind == "text" and ev["agent"] == "lead":
            print(ev["text"], end="", flush=True)
        elif kind == "result":
            report = ev.get("report", "")
            dur = (ev.get("duration_ms") or 0) / 1000
            cost = ev.get("cost_usd")
            print(
                f"\n\n✅ Done in {dur:.1f}s"
                + (f" · ${cost:.4f}" if cost else "")
                + f" · {ev.get('num_turns', '?')} turns",
                flush=True,
            )
        elif kind == "error":
            print(f"\n❌ {ev['message']}", file=sys.stderr, flush=True)

    return report.strip()


def save_report(category: str, body: str, output_dir: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in category).strip("_").lower()
    path = os.path.join(output_dir, f"report_{safe or 'general'}.md")
    header = (
        f"<!-- Generated {datetime.now(timezone.utc).isoformat()} "
        f"by product-researcher -->\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-agent product researcher (Claude Agent SDK)."
    )
    parser.add_argument("category", help="Product category / market to research.")
    parser.add_argument("--top", type=int, default=10, help="How many products to predict.")
    parser.add_argument("--out", default="./reports", help="Output directory.")
    parser.add_argument("--model", default="sonnet", help="Lead model (sonnet/opus/haiku).")
    parser.add_argument("--mock", action="store_true",
                        help="Run fully offline with canned data (no API key or credits).")
    args = parser.parse_args(argv)

    if not args.mock and not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set. Copy .env.example to .env, "
              "or use --mock to run offline.", file=sys.stderr)
        return 1

    output_dir = os.path.abspath(args.out)
    body = asyncio.run(run(args.category, args.top, output_dir, args.model, args.mock))

    if body:
        report_path = save_report(args.category, body, output_dir)
        print(f"\n📄 Markdown report: {report_path}")
        print(f"🗂  JSON predictions: {output_dir}/predictions_*.json")
    else:
        print("\nNo report text was produced.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
