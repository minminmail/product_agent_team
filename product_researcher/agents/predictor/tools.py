"""The predictor's own in-process tool: score_product.

Wraps the SDK-free scoring formula in scoring.py as an MCP tool. The team-level
assembler (product_researcher/tools.py) collects this tool together with the
shared save_results tool into the single `research-tools` MCP server.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .scoring import compute_score

# Fully-qualified name for the allowed_tools list / agent definition.
# SDK in-process MCP tools are namespaced as: mcp__<server>__<tool>
TOOL_SCORE = "mcp__research-tools__score_product"


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
