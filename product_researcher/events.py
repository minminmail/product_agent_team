"""Shared streaming layer.

`run_stream()` runs the product-research pipeline and yields plain dict events
that both the CLI and the web dashboard consume. This keeps the SDK-message
translation in one place.

Event shapes (all have a "type"):
    {"type": "start",      "category", "top", "model"}
    {"type": "subagent",   "name", "task"}          # lead delegated to a subagent
    {"type": "tool",       "name", "summary", "agent"}   # a tool was called
    {"type": "tool_result","name", "is_error", "summary", "agent"}
    {"type": "text",       "text", "agent"}         # assistant prose
    {"type": "thinking",   "agent"}                 # model is reasoning (no content)
    {"type": "result",     "duration_ms", "cost_usd", "num_turns", "report"}
    {"type": "error",      "message"}
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

from .agents import AGENTS
from .tools import (
    TOOL_SAVE,
    TOOL_SAVE_SUPPLIERS,
    TOOL_SCORE,
    TOOL_SCORE_SUPPLIER,
    research_tools_server,
)

# How many of the top products get a supplier shortlist, and how many suppliers
# to shortlist per product.
SOURCE_TOP_PRODUCTS = 3
SUPPLIERS_PER_PRODUCT = 10


def build_lead_prompt(category: str, top: int, output_dir: str) -> str:
    """The lead agent's task brief. Single source of truth for the pipeline."""
    return f"""You lead a product-research team. Goal: find and predict the products
most likely to become popular in the category: "{category}", then source the best
manufacturers/suppliers for the top picks.

Run this pipeline using your subagents (delegate with the Task tool):

1. Call the `trend-scout` subagent to gather 8-15 specific emerging candidate
   products in this category, each with a rising signal and a cited source.
2. Call the `market-analyst` subagent to score every candidate on the five
   dimensions (demand, growth, margin, competition, feasibility, 0-10 each).
3. Call the `predictor` subagent to turn those sub-scores into final 0-100
   opportunity scores (it must use the {TOOL_SCORE} tool) and rank them.
4. Take the top {top} ranked products. Then call the `{TOOL_SAVE}` tool with:
   category="{category}", output_dir="{output_dir}", and products=[...] where
   each product is an object: name, score, verdict, rationale, evidence (a short
   source note or URL).
5. Take the TOP {SOURCE_TOP_PRODUCTS} ranked products and call the
   `sourcing-scout` subagent to find, for each, the best-quality manufacturers/
   suppliers — prioritising trustworthy reputation, high product quality, and
   valid EU certifications (CE, ISO 9001, REACH, RoHS, EN…). It must score every
   supplier with the {TOOL_SCORE_SUPPLIER} tool and return up to
   {SUPPLIERS_PER_PRODUCT} ranked suppliers per product.
6. Call the `{TOOL_SAVE_SUPPLIERS}` tool with: category="{category}",
   output_dir="{output_dir}", and products=[...] where each item is
   {{product, score, suppliers:[{{name, country, score, tier, certifications,
   reputation_note, evidence}}]}}.

Finally, output a clean Markdown report to me with these sections:
  # Product Predictions: {category}
  - a 2-3 sentence executive summary
  - a Markdown table of the top {top}: Rank | Product | Score | Verdict | Why
  - a "## Top suppliers" section: for each of the top {SOURCE_TOP_PRODUCTS}
    products, a subheading with the product name and a Markdown table of its
    suppliers: Rank | Supplier | Country | Score | Tier | Certifications
  - a short "Methodology & caveats" note (predictions are probabilistic; verify
    suppliers and certifications before ordering).

Be concrete and evidence-driven. Do not fabricate products, suppliers,
certifications, or sources."""


def _make_options(model: str, output_dir: str):
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        model=model,
        system_prompt=(
            "You are the lead of a product-research team. You are rigorous, "
            "evidence-driven, and you delegate to specialist subagents rather "
            "than doing everything yourself."
        ),
        agents=AGENTS,
        mcp_servers={"research-tools": research_tools_server},
        allowed_tools=[
            "Task",  # subagent dispatch
            "Agent",
            "WebSearch",
            "WebFetch",
            TOOL_SCORE,
            TOOL_SAVE,
            TOOL_SCORE_SUPPLIER,
            TOOL_SAVE_SUPPLIERS,
        ],
        # Non-interactive: never block waiting for a human to approve a tool.
        permission_mode="bypassPermissions",
        max_turns=60,
        cwd=output_dir,
    )


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_summary(name: str, tool_input: dict) -> str:
    if not isinstance(tool_input, dict):
        return _short(tool_input)
    if name in ("WebSearch",) and "query" in tool_input:
        return f'search: "{tool_input["query"]}"'
    if name in ("WebFetch",) and "url" in tool_input:
        return f'fetch: {tool_input["url"]}'
    if name.endswith("score_product"):
        return f'score: {tool_input.get("name", "?")}'
    if name.endswith("save_results"):
        prods = tool_input.get("products", [])
        return f'save: {len(prods) if isinstance(prods, list) else "?"} products'
    if name.endswith("score_supplier"):
        return f'supplier: {tool_input.get("name", "?")}'
    if name.endswith("save_suppliers"):
        prods = tool_input.get("products", [])
        n = sum(len(p.get("suppliers", [])) for p in prods if isinstance(p, dict)) \
            if isinstance(prods, list) else "?"
        return f'save: {n} suppliers'
    return _short(tool_input)


async def run_stream(
    category: str,
    top: int = 10,
    output_dir: str = "./reports",
    model: str = "sonnet",
) -> AsyncIterator[dict]:
    """Run the pipeline, yielding UI events as the agents work."""
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    yield {"type": "start", "category": category, "top": top, "model": model}

    # Map a tool_use id -> the agent that issued it, so results can be attributed
    # and Task dispatches can be labelled with their subagent name.
    tool_use_owner: dict[str, str] = {}
    report_parts: list[str] = []

    options = _make_options(model, output_dir)
    prompt = build_lead_prompt(category, top, output_dir)

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                # parent_tool_use_id present => this text came from a subagent
                agent = "lead" if not message.parent_tool_use_id else "subagent"
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if block.text.strip():
                            if agent == "lead":
                                report_parts.append(block.text)
                            yield {"type": "text", "agent": agent, "text": block.text}
                    elif isinstance(block, ThinkingBlock):
                        yield {"type": "thinking", "agent": agent}
                    elif isinstance(block, ToolUseBlock):
                        name = block.name
                        tin = block.input if isinstance(block.input, dict) else {}
                        if name in ("Task", "Agent"):
                            sub = (
                                tin.get("subagent_type")
                                or tin.get("subagentType")
                                or tin.get("name")
                                or "subagent"
                            )
                            tool_use_owner[block.id] = sub
                            yield {
                                "type": "subagent",
                                "name": sub,
                                "task": _short(
                                    tin.get("description")
                                    or tin.get("prompt", ""),
                                    200,
                                ),
                            }
                        else:
                            tool_use_owner[block.id] = name
                            yield {
                                "type": "tool",
                                "name": name,
                                "agent": agent,
                                "summary": _tool_summary(name, tin),
                            }
            elif isinstance(message, ResultMessage):
                report = "".join(report_parts).strip()
                yield {
                    "type": "result",
                    "duration_ms": getattr(message, "duration_ms", None),
                    "cost_usd": getattr(message, "total_cost_usd", None),
                    "num_turns": getattr(message, "num_turns", None),
                    "is_error": getattr(message, "is_error", False),
                    "report": report or getattr(message, "result", "") or "",
                }
    except Exception as exc:  # surface failures to the UI instead of dying silently
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
