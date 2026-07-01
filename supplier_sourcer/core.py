"""Shared, dependency-free report I/O for the supplier-sourcing agent.

This module imports NOTHING from claude_agent_sdk, so the offline mock pipeline
can reuse it with zero external dependencies and no API key. It holds the
team-level suppliers-writer and the loader that reads the product-research
team's saved predictions file.

The supplier-quality scoring formula now lives with the agent that owns it —
agents/sourcing_scout/scoring.py — and is re-exported here (SUPPLIER_WEIGHTS,
compute_supplier_score) for backwards compatibility with existing imports.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone

# Re-export the sourcing-scout's scoring formula for backwards compatibility.
# scoring.py is SDK-free, so importing it keeps this module SDK-free too.
from .agents.sourcing_scout.scoring import SUPPLIER_WEIGHTS, compute_supplier_score

__all__ = [
    "SUPPLIER_WEIGHTS",
    "compute_supplier_score",
    "write_suppliers",
    "load_predictions",
    "list_available_reports",
    "top_products",
]


def _slug(category: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (category or "")).strip("_").lower()


def write_suppliers(category: str, products: list, output_dir: str | None = None) -> str:
    """Persist per-product supplier shortlists as JSON.

    `products` is a list of objects shaped like:
        {"product": <name>, "score": <0-100>, "suppliers": [<supplier objs>]}
    Returns the absolute path written.
    """
    category = category or "general"
    products = products or []
    output_dir = output_dir or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)

    supplier_total = sum(len(p.get("suppliers", [])) for p in products)
    record = {
        "category": category,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product_count": len(products),
        "supplier_count": supplier_total,
        "products": products,
    }
    path = os.path.join(output_dir, f"suppliers_{_slug(category) or 'general'}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return path


def load_predictions(category: str, reports_dir: str) -> dict | None:
    """Load the research team's saved predictions for a category.

    Looks for `predictions_<slug>.json` in reports_dir (exact category match, so
    the sourcing agent never silently sources a different category). Returns the
    parsed record ({"category", "products": [...]}) or None if it doesn't exist.
    """
    reports_dir = os.path.abspath(reports_dir or ".")
    path = os.path.join(reports_dir, f"predictions_{_slug(category) or 'general'}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_source_path"] = path
        return data
    except (OSError, json.JSONDecodeError):
        return None


def list_available_reports(reports_dir: str) -> list:
    """Return category slugs that have a saved predictions file (for hints)."""
    reports_dir = os.path.abspath(reports_dir or ".")
    out = []
    for p in sorted(glob.glob(os.path.join(reports_dir, "predictions_*.json"))):
        base = os.path.basename(p)
        out.append(base[len("predictions_"):-len(".json")])
    return out


def top_products(predictions: dict, n: int) -> list:
    """Return the top-n products (by score) from a predictions record."""
    products = list(predictions.get("products", [])) if predictions else []
    products.sort(key=lambda p: p.get("score", 0), reverse=True)
    return products[:n]
