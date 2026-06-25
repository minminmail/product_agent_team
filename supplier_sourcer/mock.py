"""Offline mock pipeline for the supplier-sourcing agent — ZERO API calls.

`run_stream_mock()` emits the same event schema as `events.run_stream()`, so the
CLI and dashboard behave identically. It reads the *real* saved predictions file
(if present) and uses the *real* SDK-free scoring/save logic, so the produced
supplier report and JSON are genuine — only the supplier "research" is faked with
canned EU manufacturers.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from typing import AsyncIterator

# Import the pure, SDK-free core directly so mock mode never loads
# claude_agent_sdk (that's the whole point of mock mode).
from .core import (
    compute_supplier_score,
    list_available_reports,
    load_predictions,
    top_products,
    write_suppliers,
)

MOCK_SUPPLIERS_PER_PRODUCT = 5

# Canned EU-leaning manufacturers used to demo the supplier stage offline.
_SUPPLIER_FORMS = [
    ("{cat} Werke GmbH", "Germany", ["CE", "ISO 9001", "REACH"]),
    ("Nordic {cat} Manufacturing AB", "Sweden", ["CE", "ISO 9001", "RoHS"]),
    ("{cat} Italia S.p.A.", "Italy", ["CE", "EN 71"]),
    ("Iberia {cat} Industries S.L.", "Spain", ["CE", "ISO 9001"]),
    ("{cat} Benelux B.V.", "Netherlands", ["CE", "ISO 14001", "REACH"]),
    ("Atlantic {cat} Co.", "Ireland", ["CE", "ISO 9001"]),
    ("{cat} Polska Sp. z o.o.", "Poland", ["CE", "RoHS"]),
    ("Alpine {cat} AG", "Austria", ["CE", "ISO 9001", "EN 71"]),
]

def _supplier_scores_for(seed: str, n_certs: int) -> dict:
    """Deterministic supplier sub-scores; certification reflects # of EU certs."""
    h = hashlib.sha256(("supp:" + seed).encode()).digest()
    def s(i: int, lo: float = 5.0, hi: float = 9.7) -> float:
        return round(lo + (h[i] / 255) * (hi - lo), 1)
    return {
        "quality": s(0, 6.0, 9.8),
        "reputation": s(1, 5.5, 9.6),
        "certification": round(min(10.0, 5.0 + 1.5 * n_certs + h[2] / 255), 1),
        "reliability": s(3, 5.0, 9.5),
        "price": s(4, 4.0, 9.0),
    }


def _mock_suppliers_for(product: str, cat: str) -> list:
    """Build a deterministic, ranked supplier shortlist for one product."""
    suppliers = []
    for idx in range(MOCK_SUPPLIERS_PER_PRODUCT):
        form, country, certs = _SUPPLIER_FORMS[idx % len(_SUPPLIER_FORMS)]
        name = form.format(cat=cat.title())
        sub = _supplier_scores_for(product + "|" + name, len(certs))
        scored = compute_supplier_score(
            name=name, product=product, country=country,
            certifications=certs, **sub,
        )
        scored["reputation_note"] = "Established EU manufacturer (mock demo signal)."
        scored["evidence"] = "Mock directory entry (offline demo — no live source)."
        suppliers.append(scored)
    suppliers.sort(key=lambda s: s["score"], reverse=True)
    return suppliers


async def run_stream_mock(
    category: str,
    reports_dir: str = "./reports",
    output_dir: str | None = None,
    model: str = "sonnet",
    top: int = 3,
    per_product: int = MOCK_SUPPLIERS_PER_PRODUCT,
    fast: bool = False,
) -> AsyncIterator[dict]:
    """Yield UI events for a fully offline, deterministic sourcing run."""
    reports_dir = os.path.abspath(reports_dir)
    output_dir = os.path.abspath(output_dir or reports_dir)
    os.makedirs(output_dir, exist_ok=True)
    pause = (lambda: asyncio.sleep(0)) if fast else (lambda: asyncio.sleep(0.35))
    started = datetime.now(timezone.utc)

    cat = category.strip().rstrip("s") if category.strip() else "product"

    # The sourcing agent only works if the research agent has produced output.
    # Require a real predictions_<category>.json — same rule as the live run, so
    # the UI behaves identically in both modes.
    predictions = load_predictions(category, reports_dir)
    if not predictions or not predictions.get("products"):
        available = list_available_reports(reports_dir)
        hint = (" Available reports: " + ", ".join(available) + ".") if available \
            else " No reports found yet."
        yield {
            "type": "error",
            "message": (
                f"No research report found for '{category}' in {reports_dir}. "
                f"Run the product_researcher agent first to produce "
                f"predictions_*.json.{hint}"
            ),
        }
        return

    products = top_products(predictions, top)
    source_note = os.path.basename(predictions.get("_source_path", "saved report"))

    yield {"type": "start", "category": category,
           "products": [p["name"] for p in products], "model": f"{model} (MOCK)"}
    await pause()
    yield {"type": "text", "agent": "lead",
           "text": f"Sourcing suppliers for top {len(products)} products "
                   f"({source_note})."}
    await pause()

    yield {"type": "subagent", "name": "sourcing-scout",
           "task": "find best-quality EU-certified suppliers for the top products"}
    await pause()

    sourced = []
    for p in products:
        yield {"type": "tool", "name": "WebSearch", "agent": "subagent",
               "summary": f'suppliers: "{p["name"]}"'}
        await asyncio.sleep(0 if fast else 0.06)
        suppliers = _mock_suppliers_for(p["name"], cat)
        for s in suppliers:
            yield {"type": "tool", "name": "mcp__sourcing-tools__score_supplier",
                   "agent": "subagent",
                   "summary": f'supplier: {s["name"]} = {s["score"]}'}
            await asyncio.sleep(0 if fast else 0.03)
        sourced.append({"product": p["name"], "score": p.get("score"),
                        "suppliers": suppliers})
    yield {"type": "text", "agent": "subagent",
           "text": f"Shortlisted suppliers for {len(sourced)} products."}
    await pause()

    write_suppliers(category=category, products=sourced, output_dir=output_dir)
    n_supp = sum(len(s["suppliers"]) for s in sourced)
    yield {"type": "tool", "name": "mcp__sourcing-tools__save_suppliers",
           "agent": "lead", "summary": f"save: {n_supp} suppliers"}
    await pause()

    report = _build_report(category, sourced)
    for chunk in _chunks(report, 240):
        yield {"type": "text", "agent": "lead", "text": chunk}
        await asyncio.sleep(0 if fast else 0.04)

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    yield {"type": "result", "duration_ms": duration_ms, "cost_usd": 0.0,
           "num_turns": 0, "is_error": False, "report": report}


def _build_report(category: str, sourced: list) -> str:
    lines = [f"# Supplier Shortlist: {category}", ""]
    lines.append("*(MOCK / offline demo — generated with canned data and zero API calls.)*")
    lines.append("")
    lines.append(
        f"Best-quality manufacturers/suppliers for the top {len(sourced)} products, "
        f"ranked on quality, reputation and valid EU certifications (CE, ISO 9001, "
        f"REACH, RoHS…). Supplier scores come from the real scoring tool; the "
        f"underlying supplier data is simulated."
    )
    lines.append("")
    for entry in sourced:
        lines.append(f"## {entry['product']}")
        lines.append("")
        lines.append("| Rank | Supplier | Country | Score | Tier | Certifications |")
        lines.append("|----:|----------|---------|------:|------|----------------|")
        for i, s in enumerate(entry["suppliers"], 1):
            certs = ", ".join(s.get("certifications", []))
            lines.append(
                f"| {i} | {s['name']} | {s['country']} | {s['score']} | "
                f"{s['tier']} | {certs} |"
            )
        lines.append("")
    lines.append("## Caveats")
    lines.append(
        "Supplier score (0–100) weights quality, reputation, EU certification, "
        "reliability and price. **This is mock mode:** suppliers are generated "
        "offline for testing — not real sourcing data. Run with a valid API key "
        "for live results, and always verify suppliers and certifications before "
        "ordering."
    )
    lines.append("")
    return "\n".join(lines)


def _chunks(text: str, n: int):
    for i in range(0, len(text), n):
        yield text[i : i + n]
