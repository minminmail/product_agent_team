"""Team-level tool assembly for the supplier-sourcing agent.

The sourcing-scout owns its `score_supplier` tool in its folder
(agents/sourcing_scout/). This module collects that agent-owned tool together
with the team-level `save_suppliers` tool (used to persist the shortlist) into
the single in-process `sourcing-tools` MCP server the SDK exposes to the agent.

Pure scoring/save logic stays SDK-free: the scoring formula lives in
agents/sourcing_scout/scoring.py and the suppliers-writer in core.py. Both are
re-exported here for backwards compatibility.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

# Agent-owned tool: the sourcing-scout's deterministic supplier scorer.
from .agents.sourcing_scout.scoring import SUPPLIER_WEIGHTS, compute_supplier_score
from .agents.sourcing_scout.tools import TOOL_SCORE_SUPPLIER, score_supplier

# Team-level persistence logic (SDK-free) lives in core.py.
from .core import write_suppliers

__all__ = [
    "SUPPLIER_WEIGHTS",
    "compute_supplier_score",
    "write_suppliers",
    "score_supplier",
    "save_suppliers",
    "sourcing_tools_server",
    "TOOL_SCORE_SUPPLIER",
    "TOOL_SAVE_SUPPLIERS",
]


@tool(
    "save_suppliers",
    "Persist the per-product supplier shortlists as a JSON file. Pass category, "
    "output_dir, and products=[{product, score, suppliers:[{name, country, "
    "score, tier, certifications, reputation_note, evidence}]}]. Returns the "
    "absolute path written.",
    {
        "category": str,
        "products": list,
        "output_dir": str,
    },
)
async def save_suppliers(args: dict[str, Any]) -> dict[str, Any]:
    products = args.get("products", [])
    path = write_suppliers(
        category=args.get("category", "general"),
        products=products,
        output_dir=args.get("output_dir"),
    )
    total = sum(len(p.get("suppliers", [])) for p in products if isinstance(p, dict))
    return {
        "content": [
            {"type": "text", "text": f"Saved {total} suppliers across {len(products)} products to {path}"}
        ]
    }


# In-process MCP server exposing the team's tools: the sourcing-scout's
# score_supplier (agent-owned) plus the team-level save_suppliers.
sourcing_tools_server = create_sdk_mcp_server(
    name="sourcing-tools",
    version="1.0.0",
    tools=[score_supplier, save_suppliers],
)

# Fully-qualified tool name for the allowed_tools list.
# SDK in-process MCP tools are namespaced as: mcp__<server>__<tool>
TOOL_SAVE_SUPPLIERS = "mcp__sourcing-tools__save_suppliers"
