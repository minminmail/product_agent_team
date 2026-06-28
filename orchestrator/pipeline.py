"""The orchestrator pipeline — chains research then sourcing.

`run_pipeline()` yields the same plain-dict event schema the two agents use, with
an extra `{"type": "stage", ...}` marker emitted before each stage so the UI/CLI
can show the hand-off. It is mock-aware and imports the SDK-backed pipelines
lazily, so mock runs never require claude_agent_sdk.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

# Default sizing (kept here so the orchestrator has one place to tune the run).
DEFAULT_TOP = 8            # products the research agent ranks
DEFAULT_SOURCE_TOP = 3     # top products to source suppliers for
DEFAULT_PER_PRODUCT = 10   # suppliers per product


async def run_pipeline(
    category: str,
    top: int = DEFAULT_TOP,
    source_top: int = DEFAULT_SOURCE_TOP,
    per_product: int = DEFAULT_PER_PRODUCT,
    reports_dir: str = "./reports",
    model: str = "sonnet",
    mock: bool = False,
) -> AsyncIterator[dict]:
    """Run research, then (if it succeeded) supplier sourcing on its output."""
    reports_dir = os.path.abspath(reports_dir)
    os.makedirs(reports_dir, exist_ok=True)

    # --- Stage 1: product research (Maria) ---
    yield {"type": "stage", "stage": "research", "agent": "Maria",
           "label": "Stage 1 · Research"}

    if mock:
        from product_researcher.mock import run_stream_mock as research
        research_stream = research(category, top, reports_dir, model)
    else:
        from product_researcher.events import run_stream as research
        research_stream = research(category, top, reports_dir, model)

    research_ok = False
    async for ev in research_stream:
        if ev.get("type") == "result" and not ev.get("is_error"):
            research_ok = True
        yield ev

    if not research_ok:
        yield {"type": "error",
               "message": "Research stage did not complete — skipping supplier "
                          "sourcing."}
        return

    # --- Stage 2: supplier sourcing (Javier) ---
    yield {"type": "stage", "stage": "sourcing", "agent": "Javier",
           "label": "Stage 2 · Sourcing"}

    if mock:
        from supplier_sourcer.mock import run_stream_mock as sourcing
        sourcing_stream = sourcing(category, reports_dir, reports_dir, model,
                                   source_top, per_product)
    else:
        from supplier_sourcer.events import run_stream as sourcing
        sourcing_stream = sourcing(category, reports_dir, reports_dir, model,
                                   source_top, per_product)

    async for ev in sourcing_stream:
        yield ev
