"""LangGraph version of the orchestrator (proof-of-concept).

Same behaviour as `orchestrator.pipeline.run_pipeline` — research, then (only if
research produced products) supplier sourcing — but expressed as a LangGraph
`StateGraph` with a **conditional edge** instead of a straight `await a; await b`.

It yields the *exact same* event dicts as the deterministic orchestrator, so the
existing dashboard/SSE works unchanged. Streaming is done with an asyncio.Queue:
the graph runs as a task and each node pushes events onto the queue, which this
async generator drains. (LangGraph drives control flow; we keep our own event
stream — that's all the dashboard needs.)

Requires `pip install langgraph`. Selected at runtime via USE_LANGGRAPH=1 or the
orchestrator CLI's --langgraph flag; the default orchestrator has no LangGraph
dependency.
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
    research_ok: bool


def _build_graph(emit):
    """Compile a StateGraph whose nodes stream events through `emit`."""

    async def research_node(state: PipelineState) -> dict:
        await emit({"type": "stage", "stage": "research", "agent": "Maria",
                    "label": "Stage 1 · Research"})
        if state["mock"]:
            from product_researcher.mock import run_stream_mock as research
            stream = research(state["category"], state["top"], state["reports_dir"], state["model"])
        else:
            from product_researcher.events import run_stream as research
            stream = research(state["category"], state["top"], state["reports_dir"], state["model"])

        ok = False
        async for ev in stream:
            if ev.get("type") == "result" and not ev.get("is_error"):
                ok = True
            await emit(ev)
        if not ok:
            await emit({"type": "error",
                        "message": "Research stage did not complete — skipping supplier sourcing."})
        return {"research_ok": ok}

    async def sourcing_node(state: PipelineState) -> dict:
        await emit({"type": "stage", "stage": "sourcing", "agent": "Javier",
                    "label": "Stage 2 · Sourcing"})
        if state["mock"]:
            from supplier_sourcer.mock import run_stream_mock as sourcing
            stream = sourcing(state["category"], state["reports_dir"], state["reports_dir"],
                              state["model"], state["source_top"], state["per_product"])
        else:
            from supplier_sourcer.events import run_stream as sourcing
            stream = sourcing(state["category"], state["reports_dir"], state["reports_dir"],
                              state["model"], state["source_top"], state["per_product"])
        async for ev in stream:
            await emit(ev)
        return {}

    def route_after_research(state: PipelineState) -> str:
        # Conditional edge: only source suppliers if research produced output.
        return "sourcing" if state.get("research_ok") else "end"

    g = StateGraph(PipelineState)
    g.add_node("research", research_node)
    g.add_node("sourcing", sourcing_node)
    g.add_edge(START, "research")
    g.add_conditional_edges("research", route_after_research,
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
