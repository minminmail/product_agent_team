"""CLI for the orchestrator agent ("Amanda").

Runs the whole pipeline in one shot: research, then supplier sourcing.

Usage:
    python -m orchestrator.main "smart home gadgets"
    python -m orchestrator.main "smart home gadgets" --top 8 --source-top 3 --per 10 --mock
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional
    pass

from .pipeline import (
    DEFAULT_PER_PRODUCT,
    DEFAULT_SOURCE_TOP,
    DEFAULT_TOP,
    run_pipeline,
)


async def run(category, top, source_top, per_product, reports_dir, model, mock, langgraph=False):
    tag = " [MOCK]" if mock else ""
    engine = "LangGraph" if langgraph else "deterministic"
    print(f"\n🧭 Amanda is orchestrating the full pipeline for {category!r}{tag} "
          f"({engine} engine)\n", flush=True)
    if langgraph:
        from .graph import run_pipeline_graph as runner
    else:
        runner = run_pipeline
    async for ev in runner(category, top, source_top, per_product,
                           reports_dir, model, mock):
        kind = ev["type"]
        if kind == "stage":
            print(f"\n══ {ev.get('label', ev['stage'])} ══", flush=True)
        elif kind == "subagent":
            print(f"  ➤ delegating to [{ev['name']}]", flush=True)
        elif kind == "tool":
            print(f"    · {ev['name']}: {ev['summary']}", flush=True)
        elif kind == "text" and ev.get("agent") == "lead":
            print(ev["text"], end="", flush=True)
        elif kind == "result":
            dur = (ev.get("duration_ms") or 0) / 1000
            cost = ev.get("cost_usd")
            print(f"\n  ✓ stage done in {dur:.1f}s"
                  + (f" · ${cost:.4f}" if cost else ""), flush=True)
        elif kind == "error":
            print(f"\n❌ {ev['message']}", file=sys.stderr, flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Orchestrator agent — runs research then sourcing.")
    p.add_argument("category", help="Product category / market.")
    p.add_argument("--top", type=int, default=DEFAULT_TOP, help="Products to rank.")
    p.add_argument("--source-top", type=int, default=DEFAULT_SOURCE_TOP,
                   help="Top products to source suppliers for.")
    p.add_argument("--per", type=int, default=DEFAULT_PER_PRODUCT, help="Suppliers per product.")
    p.add_argument("--out", default="./reports", help="Reports directory (shared by both stages).")
    p.add_argument("--model", default="haiku", help="Lead model (haiku/sonnet/opus).")
    p.add_argument("--mock", action="store_true",
                   help="Run the whole pipeline offline (no API key or credits).")
    p.add_argument("--langgraph", action="store_true",
                   help="Use the LangGraph engine (pip install langgraph).")
    args = p.parse_args(argv)

    if not args.mock and not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set. Copy .env.example to .env, "
              "or use --mock to run offline.", file=sys.stderr)
        return 1

    reports_dir = os.path.abspath(args.out)
    asyncio.run(run(args.category, args.top, args.source_top, args.per,
                    reports_dir, args.model, args.mock, args.langgraph))
    print(f"\n📂 Outputs in {reports_dir}: predictions_*.json, suppliers_*.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
