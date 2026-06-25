"""Pure, dependency-free core logic for the product-researcher team.

This module deliberately imports NOTHING from claude_agent_sdk. It holds the
deterministic scoring formula and the results-writer so that both the SDK tool
wrappers (tools.py) and the offline mock pipeline (mock.py) can share identical
behaviour. Keeping it SDK-free is what lets mock mode run with zero external
dependencies and no API key.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

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


def compute_score(
    name: str,
    demand: float,
    growth: float,
    margin: float,
    competition: float,
    feasibility: float,
) -> dict:
    """Return the opportunity-score payload (name, score, verdict, breakdown).

    Competition is a cost, not a benefit, so it is inverted (10 = no competition).
    """
    demand = _clamp(float(demand))
    growth = _clamp(float(growth))
    margin = _clamp(float(margin))
    competition = _clamp(float(competition))
    feasibility = _clamp(float(feasibility))

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

    return {
        "name": name or "unnamed",
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


def write_results(category: str, products: list, output_dir: str | None = None) -> str:
    """Persist ranked predictions as JSON. Returns the absolute path written."""
    category = category or "general"
    products = products or []
    output_dir = output_dir or os.getcwd()
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
    return path


# ---------------------------------------------------------------------------
# Stage 2: supplier / manufacturer sourcing
# ---------------------------------------------------------------------------

# Weights for the supplier quality score. The user prioritises trustworthy,
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
    safe = "".join(c if c.isalnum() else "_" for c in category).strip("_").lower()
    path = os.path.join(output_dir, f"suppliers_{safe or 'general'}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return path
