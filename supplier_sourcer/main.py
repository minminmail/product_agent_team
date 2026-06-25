"""CLI for the supplier-sourcing agent.

Runs independently of the product-research agent — it reads the research team's
saved predictions_<category>.json and finds the best suppliers for the top picks.

Usage:
    # after product_researcher has produced a report for "smart home gadgets":
    python -m supplier_sourcer.main "smart home gadgets"
    python -m supplier_sourcer.main "smart home gadgets" --top 3 --per 10 --mock

Writes a Markdown supplier report and a suppliers_<category>.json of the
shortlists.
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


async def run(
    category: str,
    reports_dir: str,
    output_dir: str,
    model: str,
    top: int,
    per_product: int,
    mock: bool = False,
) -> str:
    report = ""
    tag = " [MOCK]" if mock else ""
    print(f"\n🏭 Sourcing suppliers for top {top} products in: {category!r}{tag}\n",
          flush=True)

    if mock:
        stream = run_stream_mock(category, reports_dir, output_dir, model, top, per_product)
    else:
        # Import the SDK-backed pipeline lazily so mock mode never requires
        # claude_agent_sdk to be installed.
        from .events import run_stream
        stream = run_stream(category, reports_dir, output_dir, model, top, per_product)

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
    path = os.path.join(output_dir, f"report_suppliers_{safe or 'general'}.md")
    header = (
        f"<!-- Generated {datetime.now(timezone.utc).isoformat()} "
        f"by supplier-sourcer -->\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Supplier-sourcing agent (reads a product-research report)."
    )
    parser.add_argument("category", help="Category to source suppliers for (matches a saved report).")
    parser.add_argument("--reports", default="./reports",
                        help="Directory holding predictions_<category>.json (input).")
    parser.add_argument("--out", default=None,
                        help="Output directory (defaults to --reports).")
    parser.add_argument("--top", type=int, default=3, help="How many top products to source.")
    parser.add_argument("--per", type=int, default=10, help="Suppliers per product.")
    parser.add_argument("--model", default="sonnet", help="Lead model (sonnet/opus/haiku).")
    parser.add_argument("--mock", action="store_true",
                        help="Run fully offline with canned suppliers (no API key or credits).")
    args = parser.parse_args(argv)

    if not args.mock and not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set. Copy .env.example to .env, "
              "or use --mock to run offline.", file=sys.stderr)
        return 1

    reports_dir = os.path.abspath(args.reports)
    output_dir = os.path.abspath(args.out or args.reports)
    body = asyncio.run(
        run(args.category, reports_dir, output_dir, args.model, args.top, args.per, args.mock)
    )

    if body:
        report_path = save_report(args.category, body, output_dir)
        print(f"\n📄 Supplier report: {report_path}")
        print(f"🗂  Supplier JSON: {output_dir}/suppliers_*.json")
    else:
        print("\nNo report text was produced.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
