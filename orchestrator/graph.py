"""LangGraph version of the orchestrator.

The research stage is decomposed into explicit nodes so the team's structure is
visible in the graph — and so the two independent analysts run **in parallel**:

    START
      → trend_scout
      → market_analyst
      → audience_researcher  ┐ (these two run concurrently — they only depend
      → competitor_analyst   ┘  on the market_analyst output, not each other)
      → predictor            (fan-in: waits for BOTH analysts)
      → [conditional] sourcing | END

`audience_researcher` and `competitor_analyst` both have their only inbound edge
from `market_analyst` and both feed `predictor`, so LangGraph schedules them in
the same superstep and awaits them together — true parallel execution.

It yields the *exact same* event dicts as the deterministic orchestrator, so the
existing dashboard/SSE works unchanged. Streaming is done with an asyncio.Queue:
the graph runs as a task and each node pushes events onto the queue, which this
async generator drains.

Requires `pip install langgraph`. Selected at runtime via USE_LANGGRAPH=1 or the
orchestrator CLI's --langgraph flag; the default orchestrator has no LangGraph
dependency. Mock mode is fully self-contained (no SDK); live mode drives each
node with a focused single-subagent query via product_researcher.events.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, TypedDict

from langgraph.graph import END, START, StateGraph

# Sizing defaults shared with the deterministic orchestrator.
from .pipeline import DEFAULT_PER_PRODUCT, DEFAULT_SOURCE_TOP, DEFAULT_TOP


class PipelineState(TypedDict, total=False):
    category: str
    top: int
    source_top: int
    per_product: int
    reports_dir: str
    model: str
    mock: bool
    # Research sub-pipeline working state (parallel nodes write distinct keys).
    candidates: list            # mock: [(name, signal), ...]
    analysed: list              # mock: [(name, signal, sub_scores, pricing), ...]
    candidates_text: str        # live: trend-scout output
    analysis_text: str          # live: market-analyst output
    audience_text: str          # live: audience-researcher output
    competitor_text: str        # live: competitor-analyst output
    research_ok: bool


# --------------------------------------------------------------------------- #
# Live (SDK) prompts — one focused delegation per node. Prior nodes' textual
# output is threaded forward so each fresh query has the context it needs.
# --------------------------------------------------------------------------- #
def _trend_prompt(category: str) -> str:
    return (
        f"Call the `trend-scout` subagent to find 8-15 specific emerging candidate "
        f'products in the category "{category}", each with a rising signal and a '
        f"cited source. Return its numbered candidate list verbatim."
    )


def _analyst_prompt(category: str, candidates_text: str) -> str:
    return (
        f'For the category "{category}", call the `market-analyst` subagent to '
        f"score every candidate below on the five 0-10 dimensions (demand, growth, "
        f"margin, competition, feasibility) AND research pricing (typical price, "
        f"range, position, willingness to pay). Return the per-product sub-scores "
        f"and pricing.\n\nCandidates:\n{candidates_text}"
    )


def _audience_prompt(category: str, candidates_text: str) -> str:
    return (
        f'For the category "{category}", call the `audience-researcher` subagent to '
        f"build 3-4 target customer segments and buyer personas for these candidate "
        f"products. Return the segments and personas.\n\nCandidates:\n{candidates_text}"
    )


def _competitor_prompt(category: str, candidates_text: str) -> str:
    return (
        f'For the category "{category}", call the `competitor-analyst` subagent to '
        f"profile 4-6 rival brands (positioning, messaging, pricing, ad/marketing "
        f"spend, strengths/gaps) and the competitive whitespace. Return the "
        f"profiles.\n\nCandidates:\n{candidates_text}"
    )


def _predictor_prompt(category: str, top: int, output_dir: str,
                      analysis_text: str, audience_text: str,
                      competitor_text: str) -> str:
    from product_researcher.tools import TOOL_SAVE, TOOL_SCORE
    return (
        f"Call the `predictor` subagent to turn the market-analyst's sub-scores "
        f"below into final 0-100 opportunity scores (it must use the {TOOL_SCORE} "
        f"tool) and rank them. Take the top {top}. Then call `{TOOL_SAVE}` with "
        f'category="{category}", output_dir="{output_dir}", and products=[...] '
        f"(each: name, score, verdict, rationale, evidence, pricing).\n\n"
        f"Finally output a clean Markdown report with: an executive summary; a "
        f"table of the top {top} (Rank | Product | Score | Verdict | Price | Why); "
        f"an 'Audience & personas' section; a 'Competitive landscape' section; and "
        f"a short 'Methodology & caveats' note.\n\n"
        f"=== Market analysis ===\n{analysis_text}\n\n"
        f"=== Audience & personas ===\n{audience_text}\n\n"
        f"=== Competitive landscape ===\n{competitor_text}\n"
    )


def _build_graph(emit):
    """Compile a StateGraph whose nodes stream events through `emit`."""

    # ----- research sub-pipeline --------------------------------------------
    async def trend_scout_node(state: PipelineState) -> dict:
        await emit({"type": "start", "category": state["category"], "top": state["top"],
                    "model": f'{state["model"]} (MOCK)' if state["mock"] else state["model"]})
        await emit({"type": "stage", "stage": "research", "agent": "Maria",
                    "label": "Stage 1 · Research"})
        await emit({"type": "subagent", "name": "trend-scout",
                    "task": f"find emerging products in '{state['category']}'"})
        if state["mock"]:
            from product_researcher.mock import mock_candidates
            cands = mock_candidates(state["category"])
            for name, _sig in cands:
                await emit({"type": "tool", "name": "WebSearch", "agent": "subagent",
                            "summary": f'search: "{name}"'})
            await emit({"type": "text", "agent": "subagent",
                        "text": f"Found {len(cands)} emerging candidates with rising signals."})
            return {"candidates": cands}
        from product_researcher.events import run_segment
        text: list[str] = []
        async for ev in run_segment(_trend_prompt(state["category"]),
                                    state["model"], state["reports_dir"], text):
            await emit(ev)
        return {"candidates_text": "\n".join(text)}

    async def market_analyst_node(state: PipelineState) -> dict:
        await emit({"type": "subagent", "name": "market-analyst",
                    "task": "score demand / growth / margin / competition / feasibility + pricing"})
        if state["mock"]:
            from product_researcher.mock import mock_analyse
            analysed = mock_analyse(state["candidates"])
            for name, *_ in analysed:
                await emit({"type": "tool", "name": "WebSearch", "agent": "subagent",
                            "summary": f'sizing: "{name}"'})
            await emit({"type": "text", "agent": "subagent", "text": "Scored all candidates."})
            return {"analysed": analysed}
        from product_researcher.events import run_segment
        text: list[str] = []
        async for ev in run_segment(_analyst_prompt(state["category"], state.get("candidates_text", "")),
                                    state["model"], state["reports_dir"], text):
            await emit(ev)
        return {"analysis_text": "\n".join(text)}

    async def audience_node(state: PipelineState) -> dict:
        # Parallel branch A — depends only on market_analyst, not competitor_node.
        await emit({"type": "subagent", "name": "audience-researcher",
                    "task": "build target segments and buyer personas"})
        if state["mock"]:
            from product_researcher.mock import _MOCK_SEGMENTS
            for seg in _MOCK_SEGMENTS:
                await emit({"type": "tool", "name": "WebSearch", "agent": "subagent",
                            "summary": f'audience: "{seg["name"]}"'})
            await emit({"type": "text", "agent": "subagent",
                        "text": f"Defined {len(_MOCK_SEGMENTS)} target segments."})
            return {}
        from product_researcher.events import run_segment
        text: list[str] = []
        async for ev in run_segment(_audience_prompt(state["category"], state.get("candidates_text", "")),
                                    state["model"], state["reports_dir"], text):
            await emit(ev)
        return {"audience_text": "\n".join(text)}

    async def competitor_node(state: PipelineState) -> dict:
        # Parallel branch B — runs concurrently with audience_node.
        await emit({"type": "subagent", "name": "competitor-analyst",
                    "task": "profile rival brands: positioning, messaging, ad spend"})
        if state["mock"]:
            from product_researcher.mock import _MOCK_COMPETITORS
            for comp in _MOCK_COMPETITORS:
                await emit({"type": "tool", "name": "WebSearch", "agent": "subagent",
                            "summary": f'competitor: "{comp["name"]}"'})
            await emit({"type": "text", "agent": "subagent",
                        "text": f"Profiled {len(_MOCK_COMPETITORS)} competitors."})
            return {}
        from product_researcher.events import run_segment
        text: list[str] = []
        async for ev in run_segment(_competitor_prompt(state["category"], state.get("candidates_text", "")),
                                    state["model"], state["reports_dir"], text):
            await emit(ev)
        return {"competitor_text": "\n".join(text)}

    async def predictor_node(state: PipelineState) -> dict:
        # Fan-in: only runs after BOTH audience_node and competitor_node finish.
        await emit({"type": "subagent", "name": "predictor",
                    "task": "compute opportunity scores and rank"})
        if state["mock"]:
            from product_researcher.core import compute_score, write_results
            from product_researcher.mock import _build_report, mock_predict
            analysed = state["analysed"]
            for name, _sig, sub, _price in analysed:
                data = compute_score(name=name, **sub)
                await emit({"type": "tool", "name": "mcp__research-tools__score_product",
                            "agent": "subagent", "summary": f'score: {name} = {data["score"]}'})
            top_products = mock_predict(analysed, state["top"])
            write_results(category=state["category"], products=top_products,
                          output_dir=state["reports_dir"])
            await emit({"type": "tool", "name": "mcp__research-tools__save_results",
                        "agent": "lead", "summary": f"save: {len(top_products)} products"})
            report = _build_report(state["category"], top_products)
            await emit({"type": "text", "agent": "lead", "text": report})
            await emit({"type": "result", "duration_ms": 0, "cost_usd": 0.0,
                        "num_turns": 0, "is_error": False, "report": report})
            return {"research_ok": True}
        from product_researcher.events import run_segment
        text: list[str] = []
        async for ev in run_segment(
            _predictor_prompt(state["category"], state["top"], state["reports_dir"],
                              state.get("analysis_text", ""), state.get("audience_text", ""),
                              state.get("competitor_text", "")),
            state["model"], state["reports_dir"], text,
        ):
            await emit(ev)
        report = "".join(text).strip()
        ok = bool(report)
        if ok:
            await emit({"type": "result", "duration_ms": None, "cost_usd": None,
                        "num_turns": None, "is_error": False, "report": report})
        else:
            await emit({"type": "error",
                        "message": "Research stage did not complete — skipping supplier sourcing."})
        return {"research_ok": ok}

    # ----- stage 2 ----------------------------------------------------------
    async def sourcing_node(state: PipelineState) -> dict:
        await emit({"type": "stage", "stage": "sourcing", "agent": "Javier",
                    "label": "Stage 2 · Sourcing"})
        if state["mock"]:
            from supplier_sourcer.mock import run_stream_mock as sourcing
        else:
            from supplier_sourcer.events import run_stream as sourcing
        async for ev in sourcing(state["category"], state["reports_dir"], state["reports_dir"],
                                 state["model"], state["source_top"], state["per_product"]):
            await emit(ev)
        return {}

    def route_after_research(state: PipelineState) -> str:
        # Conditional edge: only source suppliers if research produced output.
        return "sourcing" if state.get("research_ok") else "end"

    g = StateGraph(PipelineState)
    g.add_node("trend_scout", trend_scout_node)
    g.add_node("market_analyst", market_analyst_node)
    g.add_node("audience_researcher", audience_node)
    g.add_node("competitor_analyst", competitor_node)
    g.add_node("predictor", predictor_node)
    g.add_node("sourcing", sourcing_node)

    g.add_edge(START, "trend_scout")
    g.add_edge("trend_scout", "market_analyst")
    # Fan-out: both analysts depend only on market_analyst → run in parallel.
    g.add_edge("market_analyst", "audience_researcher")
    g.add_edge("market_analyst", "competitor_analyst")
    # Fan-in: predictor waits for BOTH parallel analysts.
    g.add_edge("audience_researcher", "predictor")
    g.add_edge("competitor_analyst", "predictor")
    g.add_conditional_edges("predictor", route_after_research,
                            {"sourcing": "sourcing", "end": END})
    g.add_edge("sourcing", END)
    return g.compile()


def build_compiled_graph():
    """Compile with a no-op emitter — handy for diagrams / introspection."""
    async def _noop(_ev):
        return None
    return _build_graph(_noop)


async def run_pipeline_graph(
    category: str,
    top: int = DEFAULT_TOP,
    source_top: int = DEFAULT_SOURCE_TOP,
    per_product: int = DEFAULT_PER_PRODUCT,
    reports_dir: str = "./reports",
    model: str = "sonnet",
    mock: bool = False,
) -> AsyncIterator[dict]:
    """Run the LangGraph pipeline, yielding the same events as run_pipeline()."""
    reports_dir = os.path.abspath(reports_dir)
    os.makedirs(reports_dir, exist_ok=True)

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(ev: dict) -> None:
        await queue.put(ev)

    graph = _build_graph(emit)
    state: PipelineState = {
        "category": category, "top": top, "source_top": source_top,
        "per_product": per_product, "reports_dir": reports_dir,
        "model": model, "mock": mock,
    }

    async def run() -> None:
        try:
            await graph.ainvoke(state)
        except Exception as exc:  # surface failures as a stream event
            await queue.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            await queue.put(None)  # sentinel: done

    task = asyncio.create_task(run())
    while True:
        ev = await queue.get()
        if ev is None:
            break
        yield ev
    await task
