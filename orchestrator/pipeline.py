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
DEFAULT_TOP = 5            # products the research agent ranks
DEFAULT_SOURCE_TOP = 2     # top products to source suppliers for
DEFAULT_PER_PRODUCT = 5    # suppliers per product


async def run_pipeline(
    category: str,
    top: int = DEFAULT_TOP,
    source_top: int = DEFAULT_SOURCE_TOP,
    per_product: int = DEFAULT_PER_PRODUCT,
    reports_dir: str = "./reports",
    model: str = "sonnet",
    mock: bool = False,
    force_env: dict | None = None,
) -> AsyncIterator[dict]:
    """Run research, then (if it succeeded) supplier sourcing on its output.
    force_env routes both stages through the proxy (Groq button)."""
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
        research_stream = research(category, top, reports_dir, model, force_env=force_env)

    research_ok = False
    research_report = ""
    async for ev in research_stream:
        if ev.get("type") == "result" and not ev.get("is_error"):
            research_ok = True
            research_report = ev.get("report") or research_report
        yield ev

    if not research_ok:
        yield {"type": "error",
               "message": "Research stage did not complete — skipping supplier "
                          "sourcing."}
        return

    # Safeguard: if the research agent didn't save a predictions file (e.g. a
    # weaker model skipped the save tool), derive one from its report so Stage 2
    # has a handoff file instead of failing with "No research report found".
    if not mock:
        from product_researcher.core import ensure_predictions_saved
        ensure_predictions_saved(category, reports_dir, research_report)

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
                                   source_top, per_product, force_env=force_env)

    async for ev in sourcing_stream:
        yield ev
