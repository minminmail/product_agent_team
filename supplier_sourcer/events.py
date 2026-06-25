"""Streaming layer for the supplier-sourcing agent.

`run_stream()` loads the product-research team's saved predictions, asks the
sourcing team to find the best-quality, EU-certified suppliers for the top
products, and yields the same plain-dict event schema the CLI and dashboard use
(so the two agents render identically).

Event shapes (all have a "type"):
    {"type": "start",     "category", "products", "model"}
    {"type": "subagent",  "name", "task"}
    {"type": "tool",      "name", "summary", "agent"}
    {"type": "text",      "text", "agent"}
    {"type": "thinking",  "agent"}
    {"type": "result",    "duration_ms", "cost_usd", "num_turns", "report"}
    {"type": "error",     "message"}
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
    ToolUseBlock,
    query,
)

from .agents import AGENTS
from .core import list_available_reports, load_predictions, top_products
from .tools import TOOL_SAVE_SUPPLIERS, TOOL_SCORE_SUPPLIER, sourcing_tools_server

# How many of the top products to source, and how many suppliers per product.
SOURCE_TOP_PRODUCTS = 3
SUPPLIERS_PER_PRODUCT = 10


def build_lead_prompt(
    category: str, products: list, output_dir: str, per_product: int
) -> str:
    """The sourcing lead's brief, with the chosen products embedded."""
    listing = "\n".join(
        f"  {i}. {p.get('name', '?')} (opportunity score {p.get('score', '?')})"
        for i, p in enumerate(products, 1)
    )
    return f"""You lead a supplier-sourcing team. The product-research team has already
ranked products in the category "{category}". Your job is to find the best
manufacturers/suppliers for these TOP products:

{listing}

Do this:

1. Call the `sourcing-scout` subagent with these products. For EACH product it
   must find the best-quality manufacturers/suppliers — prioritising trustworthy
   reputation, high product quality, and valid EU certifications (CE, ISO 9001,
   REACH, RoHS, EN…). It must score every supplier with the
   {TOOL_SCORE_SUPPLIER} tool and rank them, returning up to {per_product}
   suppliers per product.
2. Call the `{TOOL_SAVE_SUPPLIERS}` tool with: category="{category}",
   output_dir="{output_dir}", and products=[...] where each item is
   {{product, score, suppliers:[{{name, country, score, tier, certifications,
   reputation_note, evidence}}]}}.

Finally, output a clean Markdown report to me:
  # Supplier Shortlist: {category}
  - a 1-2 sentence summary
  - for each product, a subheading with the product name and a Markdown table of
    its suppliers: Rank | Supplier | Country | Score | Tier | Certifications
  - a short "Caveats" note (verify suppliers and certifications before ordering).

Be concrete and evidence-driven. Do not fabricate suppliers, certifications, or
sources."""


def _make_options(model: str, output_dir: str):
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        model=model,
        system_prompt=(
            "You are the lead of a supplier-sourcing team. You are rigorous and "
            "evidence-driven, you prioritise trustworthy, high-quality, "
            "EU-certified suppliers, and you delegate to your sourcing-scout "
            "subagent rather than doing everything yourself."
        ),
        agents=AGENTS,
        mcp_servers={"sourcing-tools": sourcing_tools_server},
        allowed_tools=[
            "Task",
            "Agent",
            "WebSearch",
            "WebFetch",
            TOOL_SCORE_SUPPLIER,
            TOOL_SAVE_SUPPLIERS,
        ],
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
    reports_dir: str = "./reports",
    output_dir: str | None = None,
    model: str = "sonnet",
    top: int = SOURCE_TOP_PRODUCTS,
    per_product: int = SUPPLIERS_PER_PRODUCT,
) -> AsyncIterator[dict]:
    """Run the sourcing agent against a saved research report, yielding events."""
    reports_dir = os.path.abspath(reports_dir)
    output_dir = os.path.abspath(output_dir or reports_dir)
    os.makedirs(output_dir, exist_ok=True)

    predictions = load_predictions(category, reports_dir)
    if not predictions or not predictions.get("products"):
        available = list_available_reports(reports_dir)
        hint = (" Available reports: " + ", ".join(available) + ".") if available \
            else " No reports found yet."
        yield {
            "type": "error",
            "message": (
                f"No research report found for '{category}' in {reports_dir}. "
                f"Run the product_researcher agent first to produce "
                f"predictions_*.json.{hint}"
            ),
        }
        return

    products = top_products(predictions, top)
    yield {
        "type": "start",
        "category": category,
        "products": [p.get("name") for p in products],
        "model": model,
    }

    tool_use_owner: dict[str, str] = {}
    report_parts: list[str] = []

    options = _make_options(model, output_dir)
    prompt = build_lead_prompt(category, products, output_dir, per_product)

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
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
                                or "sourcing-scout"
                            )
                            tool_use_owner[block.id] = sub
                            yield {
                                "type": "subagent",
                                "name": sub,
                                "task": _short(
                                    tin.get("description") or tin.get("prompt", ""),
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
    except Exception as exc:
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
