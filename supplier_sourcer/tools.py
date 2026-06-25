"""Custom in-process tools for the supplier-sourcing agent.

These run inside the Python process via the SDK's in-process MCP support. The
agent uses them to score suppliers with a deterministic, transparent formula and
to persist the shortlist to disk. The pure logic lives in core.py (SDK-free) so
mock mode can reuse it without importing claude_agent_sdk.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .core import (
    SUPPLIER_WEIGHTS,
    compute_supplier_score,
    write_suppliers,
)

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


# In-process MCP server exposing the tools above to the sourcing agent.
sourcing_tools_server = create_sdk_mcp_server(
    name="sourcing-tools",
    version="1.0.0",
    tools=[score_supplier, save_suppliers],
)

# Fully-qualified tool names for the allowed_tools list.
# SDK in-process MCP tools are namespaced as: mcp__<server>__<tool>
TOOL_SCORE_SUPPLIER = "mcp__sourcing-tools__score_supplier"
TOOL_SAVE_SUPPLIERS = "mcp__sourcing-tools__save_suppliers"
