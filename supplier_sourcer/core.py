"""Pure, dependency-free core logic for the supplier-sourcing agent.

This module imports NOTHING from claude_agent_sdk, so the offline mock pipeline
can reuse it with zero external dependencies and no API key. It holds the
supplier-quality scoring formula, the suppliers-writer, and a loader that reads
the product-research team's saved predictions file.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def _slug(category: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (category or "")).strip("_").lower()


# Weights for the supplier quality score. The priority is trustworthy,
# high-quality, EU-certified manufacturers — so quality, reputation and
# certification dominate. Tweak to change what "best supplier" means.
SUPPLIER_WEIGHTS = {
    "quality": 0.30,        # product build quality / defect rate / materials
    "reputation": 0.25,     # reviews, years in business, buyer trust signals
    "certification": 0.25,  # valid EU/relevant certs (CE, ISO 9001, REACH, RoHS…)
    "reliability": 0.12,    # on-time delivery, communication, lead-time stability
    "price": 0.08,          # value for money / reasonable MOQ (higher = better value)
}


def compute_supplier_score(
    name: str,
    quality: float,
    reputation: float,
    certification: float,
    reliability: float,
    price: float,
    product: str = "",
    country: str = "",
    certifications: list | None = None,
) -> dict:
    """Return a 0-100 supplier-quality score payload from five 0-10 sub-scores.

    `certification` is the 0-10 strength of the supplier's certifications (10 =
    full, verifiable EU certs). `certifications` is the human-readable list of
    actual certs (e.g. ["CE", "ISO 9001", "REACH"]) carried through for display.
    """
    quality = _clamp(float(quality))
    reputation = _clamp(float(reputation))
    certification = _clamp(float(certification))
    reliability = _clamp(float(reliability))
    price = _clamp(float(price))

    weighted = (
        quality * SUPPLIER_WEIGHTS["quality"]
        + reputation * SUPPLIER_WEIGHTS["reputation"]
        + certification * SUPPLIER_WEIGHTS["certification"]
        + reliability * SUPPLIER_WEIGHTS["reliability"]
        + price * SUPPLIER_WEIGHTS["price"]
    )
    score = round(weighted * 10, 1)  # scale 0-10 -> 0-100

    if score >= 80:
        tier = "Top-tier supplier"
    elif score >= 65:
        tier = "Strong supplier"
    elif score >= 50:
        tier = "Viable supplier"
    else:
        tier = "Use with caution"

    return {
        "name": name or "unnamed supplier",
        "product": product,
        "country": country,
        "score": score,
        "tier": tier,
        "certifications": certifications or [],
        "breakdown": {
            "quality": quality,
            "reputation": reputation,
            "certification": certification,
            "reliability": reliability,
            "price": price,
        },
    }


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
