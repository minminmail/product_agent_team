"""Deterministic supplier-quality scoring formula — sourcing-scout's core logic.

SDK-free on purpose: imports NOTHING from claude_agent_sdk, so both the tool
wrapper (tools.py) and the offline mock pipeline can share identical behaviour
without an API key or external dependencies.
"""

from __future__ import annotations


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


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
    phone: str = "",
    email: str = "",
    address: str = "",
    hours: str = "",
    website: str = "",
) -> dict:
    """Return a 0-100 supplier-quality score payload from five 0-10 sub-scores.

    `certification` is the 0-10 strength of the supplier's certifications (10 =
    full, verifiable EU certs). `certifications` is the human-readable list of
    actual certs (e.g. ["CE", "ISO 9001", "REACH"]) carried through for display.
    `phone`/`email`/`address`/`hours`/`website` are the supplier's contact
    details, carried through for the shortlist.
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
        "contact": {
            "phone": phone or "",
            "email": email or "",
            "address": address or "",
            "hours": hours or "",
            "website": website or "",
        },
        "breakdown": {
            "quality": quality,
            "reputation": reputation,
            "certification": certification,
            "reliability": reliability,
            "price": price,
        },
    }
