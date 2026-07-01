"""Team-level tool assembly for the product-researcher team.

Each agent owns its own tools in its folder (e.g. the predictor owns
`score_product` in agents/predictor/). This module collects those agent-owned
tools together with the team-level `save_results` tool (used by the lead to
persist the final report) into the single in-process `research-tools` MCP
server the SDK exposes to the team.

Pure scoring/save logic stays SDK-free: the scoring formula lives in
agents/predictor/scoring.py and the results-writer in core.py. Both are
re-exported here for backwards compatibility.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

# Agent-owned tool: the predictor's deterministic product scorer.
from .agents.predictor.scoring import SCORE_WEIGHTS, compute_score
from .agents.predictor.tools import TOOL_SCORE, score_product

# Team-level persistence logic (SDK-free) lives in core.py.
from .core import write_results

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


# In-process MCP server exposing the team's tools: the predictor's
# score_product (agent-owned) plus the team-level save_results.
research_tools_server = create_sdk_mcp_server(
    name="research-tools",
    version="1.0.0",
    tools=[score_product, save_results],
)

# Fully-qualified tool name for the allowed_tools list.
# SDK in-process MCP tools are namespaced as: mcp__<server>__<tool>
TOOL_SAVE = "mcp__research-tools__save_results"
