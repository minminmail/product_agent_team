"""Custom in-process tools for the product-researcher team.

These run inside the Python process (no external server) via the SDK's
in-process MCP support. The team uses them to score candidate products with a
deterministic, transparent formula and to persist the final results to disk.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

# Pure scoring/save logic lives in core.py (SDK-free) so the offline mock
# pipeline can reuse it without importing claude_agent_sdk. Re-exported here for
# backwards compatibility.
from .core import SCORE_WEIGHTS, compute_score, write_results

__all__ = [
    "SCORE_WEIGHTS",
    "compute_score",
    "write_results",
    "score_product",
    "save_results",
    "research_tools_server",
    "TOOL_SCORE",
    "TOOL_SAVE",
]


@tool(
    "score_product",
    "Compute a 0-100 opportunity score for a candidate product from five "
    "sub-scores (each 0-10): demand, growth, margin, competition (low=better, "
    "the tool inverts it), feasibility. Returns the weighted score and a "
    "verdict so the team ranks candidates consistently.",
    {
        "name": str,
        "demand": float,
        "growth": float,
        "margin": float,
        "competition": float,
        "feasibility": float,
    },
)
async def score_product(args: dict[str, Any]) -> dict[str, Any]:
    payload = compute_score(
        name=args.get("name", "unnamed"),
        demand=args.get("demand", 0),
        growth=args.get("growth", 0),
        margin=args.get("margin", 0),
        competition=args.get("competition", 0),
        feasibility=args.get("feasibility", 0),
    )
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, indent=2)}
        ]
    }


@tool(
    "save_results",
    "Persist the final ranked product predictions as a JSON file. Pass the "
    "category and a list of product objects (name, score, verdict, rationale, "
    "evidence). Returns the absolute path written.",
    {
        "category": str,
        "products": list,
        "output_dir": str,
    },
)
async def save_results(args: dict[str, Any]) -> dict[str, Any]:
    products = args.get("products", [])
    path = write_results(
        category=args.get("category", "general"),
        products=products,
        output_dir=args.get("output_dir"),
    )
    return {
        "content": [
            {"type": "text", "text": f"Saved {len(products)} predictions to {path}"}
        ]
    }


# In-process MCP server exposing the tools above to the agent team.
research_tools_server = create_sdk_mcp_server(
    name="research-tools",
    version="1.0.0",
    tools=[score_product, save_results],
)

# Fully-qualified tool names for the allowed_tools list.
# SDK in-process MCP tools are namespaced as: mcp__<server>__<tool>
TOOL_SCORE = "mcp__research-tools__score_product"
TOOL_SAVE = "mcp__research-tools__save_results"
