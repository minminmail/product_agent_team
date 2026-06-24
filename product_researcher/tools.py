"""Custom in-process tools for the product-researcher team.

These run inside the Python process (no external server) via the SDK's
in-process MCP support. The team uses them to score candidate products with a
deterministic, transparent formula and to persist the final results to disk.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

# Weights for the opportunity score. Tweak to change what the team rewards.
SCORE_WEIGHTS = {
    "demand": 0.30,        # how strong / growing is buyer interest
    "growth": 0.25,        # momentum of the trend
    "margin": 0.15,        # room for healthy margins
    "competition": 0.20,   # inverse: low competition scores high
    "feasibility": 0.10,   # how easy to source / build / launch
}


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


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
    demand = _clamp(float(args.get("demand", 0)))
    growth = _clamp(float(args.get("growth", 0)))
    margin = _clamp(float(args.get("margin", 0)))
    competition = _clamp(float(args.get("competition", 0)))
    feasibility = _clamp(float(args.get("feasibility", 0)))

    # Competition is a cost, not a benefit: invert it (10 = no competition).
    competition_inv = 10.0 - competition

    weighted = (
        demand * SCORE_WEIGHTS["demand"]
        + growth * SCORE_WEIGHTS["growth"]
        + margin * SCORE_WEIGHTS["margin"]
        + competition_inv * SCORE_WEIGHTS["competition"]
        + feasibility * SCORE_WEIGHTS["feasibility"]
    )
    score = round(weighted * 10, 1)  # scale 0-10 -> 0-100

    if score >= 75:
        verdict = "Strong bet"
    elif score >= 60:
        verdict = "Promising"
    elif score >= 45:
        verdict = "Watch"
    else:
        verdict = "Pass"

    payload = {
        "name": args.get("name", "unnamed"),
        "score": score,
        "verdict": verdict,
        "breakdown": {
            "demand": demand,
            "growth": growth,
            "margin": margin,
            "competition": competition,
            "competition_inverted": competition_inv,
            "feasibility": feasibility,
        },
    }
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
    category = args.get("category", "general")
    products = args.get("products", [])
    output_dir = args.get("output_dir") or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)

    record = {
        "category": category,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product_count": len(products),
        "products": products,
    }
    safe = "".join(c if c.isalnum() else "_" for c in category).strip("_").lower()
    path = os.path.join(output_dir, f"predictions_{safe or 'general'}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

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
