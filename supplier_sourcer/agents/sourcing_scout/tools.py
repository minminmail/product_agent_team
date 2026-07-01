"""sourcing-scout's own in-process tool: score_supplier.

Wraps the SDK-free scoring formula in scoring.py as an MCP tool. The team-level
assembler (supplier_sourcer/tools.py) collects this tool together with the
shared save_suppliers tool into the single `sourcing-tools` MCP server.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .scoring import compute_supplier_score

# Fully-qualified name for the allowed_tools list / agent definition.
# SDK in-process MCP tools are namespaced as: mcp__<server>__<tool>
TOOL_SCORE_SUPPLIER = "mcp__sourcing-tools__score_supplier"


@tool(
    "score_supplier",
    "Compute a 0-100 supplier-quality score for a manufacturer/supplier from "
    "five 0-10 sub-scores: quality (product build quality), reputation (reviews, "
    "track record, buyer trust), certification (strength of valid EU/relevant "
    "certs like CE, ISO 9001, REACH, RoHS — 10 = full verifiable certs), "
    "reliability (on-time delivery, communication), price (value for money / "
    "reasonable MOQ). Prioritises trustworthy, high-quality, EU-certified "
    "suppliers. Pass product, country, the actual certifications list, and the "
    "supplier's contact details (phone, email, address, hours, website) for the "
    "shortlist. Always use this tool — never invent the score.",
    {
        "name": str,
        "quality": float,
        "reputation": float,
        "certification": float,
        "reliability": float,
        "price": float,
        "product": str,
        "country": str,
        "certifications": list,
        "phone": str,
        "email": str,
        "address": str,
        "hours": str,
        "website": str,
    },
)
async def score_supplier(args: dict[str, Any]) -> dict[str, Any]:
    payload = compute_supplier_score(
        name=args.get("name", "unnamed supplier"),
        quality=args.get("quality", 0),
        reputation=args.get("reputation", 0),
        certification=args.get("certification", 0),
        reliability=args.get("reliability", 0),
        price=args.get("price", 0),
        product=args.get("product", ""),
        country=args.get("country", ""),
        certifications=args.get("certifications") or [],
        phone=args.get("phone", ""),
        email=args.get("email", ""),
        address=args.get("address", ""),
        hours=args.get("hours", ""),
        website=args.get("website", ""),
    )
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, indent=2)}
        ]
    }
