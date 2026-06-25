"""Offline mock pipeline — runs the whole team experience with ZERO API calls.

`run_stream_mock()` emits the exact same event schema as `events.run_stream()`,
so the dashboard and CLI behave identically. It uses the *real* scoring and
save tools (which are pure local Python), so the produced report and JSON are
genuine — only the "research" (model + web search) is faked with canned data.

Use it to test the UI and pipeline without an ANTHROPIC_API_KEY or any credits.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from typing import AsyncIterator

# Import the pure, SDK-free core directly so mock mode never loads
# claude_agent_sdk (that's the whole point of mock mode).
from .core import compute_score, compute_supplier_score, write_results, write_suppliers

# Stage 2 (sourcing) demo sizing — kept small so the mock report stays readable.
MOCK_SOURCE_TOP_PRODUCTS = 3
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

# Generic candidate templates. {cat} is filled with the user's category so the
# mock feels relevant to whatever was typed.
_TEMPLATES = [
    ("Smart {cat} starter kit", "bundling drives first-time buyers; high search growth"),
    ("Refillable / subscription {cat}", "recurring revenue model trending across DTC"),
    ("Compact travel {cat}", "portability is a rising purchase driver"),
    ("Eco / refurbished {cat}", "sustainability premium; strong on social"),
    ("AI-assisted {cat}", "'AI' label lifting conversion on marketplaces"),
    ("Premium artisanal {cat}", "consumers trading up in this niche"),
    ("Budget value {cat} multipack", "cost-of-living tailwind for value packs"),
    ("Personalized {cat}", "customization commands higher margins"),
    ("{cat} for beginners", "education-led demand; low competition long-tail"),
    ("Pro-grade {cat}", "prosumer segment underserved"),
    ("Kids-safe {cat}", "parent demand + gifting seasonality"),
    ("Connected / app-enabled {cat}", "IoT angle expands TAM"),
]


def _scores_for(seed: str) -> dict:
    """Deterministic but varied sub-scores from a hash of the product name."""
    h = hashlib.sha256(seed.encode()).digest()
    def s(i: int, lo: float = 3.0, hi: float = 9.5) -> float:
        return round(lo + (h[i] / 255) * (hi - lo), 1)
    return {
        "demand": s(0),
        "growth": s(1),
        "margin": s(2),
        "competition": s(3, 1.5, 9.0),
        "feasibility": s(4, 4.0, 9.5),
    }


def _supplier_scores_for(seed: str, n_certs: int) -> dict:
    """Deterministic supplier sub-scores; certification reflects # of EU certs."""
    h = hashlib.sha256(("supp:" + seed).encode()).digest()
    def s(i: int, lo: float = 5.0, hi: float = 9.7) -> float:
        return round(lo + (h[i] / 255) * (hi - lo), 1)
    return {
        "quality": s(0, 6.0, 9.8),
        "reputation": s(1, 5.5, 9.6),
        # More valid certs => higher certification sub-score (capped at 10).
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
    top: int = 10,
    output_dir: str = "./reports",
    model: str = "sonnet",
    fast: bool = False,
) -> AsyncIterator[dict]:
    """Yield UI events for a fully offline, deterministic mock run."""
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    pause = (lambda: asyncio.sleep(0)) if fast else (lambda: asyncio.sleep(0.35))
    started = datetime.now(timezone.utc)

    yield {"type": "start", "category": category, "top": top, "model": f"{model} (MOCK)"}
    await pause()

    cat = category.strip().rstrip("s") if category.strip() else "product"
    candidates = [(name.format(cat=cat), sig) for name, sig in _TEMPLATES]

    # 1) trend-scout
    yield {"type": "subagent", "name": "trend-scout",
           "task": f"find emerging products in '{category}'"}
    await pause()
    for name, sig in candidates:
        yield {"type": "tool", "name": "WebSearch", "agent": "subagent",
               "summary": f'search: "{name}"'}
        await asyncio.sleep(0 if fast else 0.08)
    yield {"type": "text", "agent": "subagent",
           "text": f"Found {len(candidates)} emerging candidates with rising signals."}
    await pause()

    # 2) market-analyst
    yield {"type": "subagent", "name": "market-analyst",
           "task": "score demand / growth / margin / competition / feasibility"}
    await pause()
    analysed = []
    for name, sig in candidates:
        sub = _scores_for(name)
        analysed.append((name, sig, sub))
        yield {"type": "tool", "name": "WebSearch", "agent": "subagent",
               "summary": f'sizing: "{name}"'}
        await asyncio.sleep(0 if fast else 0.06)
    yield {"type": "text", "agent": "subagent", "text": "Scored all candidates."}
    await pause()

    # 3) predictor — use the REAL scoring tool (pure local, deterministic)
    yield {"type": "subagent", "name": "predictor",
           "task": "compute opportunity scores and rank"}
    await pause()
    scored = []
    for name, sig, sub in analysed:
        data = compute_score(name=name, **sub)
        scored.append({
            "name": name,
            "score": data["score"],
            "verdict": data["verdict"],
            "rationale": sig.capitalize() + ".",
            "evidence": "Mock signal (offline demo — no live source).",
            "breakdown": sub,
        })
        yield {"type": "tool", "name": "mcp__research-tools__score_product",
               "agent": "subagent", "summary": f'score: {name} = {data["score"]}'}
        await asyncio.sleep(0 if fast else 0.05)

    scored.sort(key=lambda p: p["score"], reverse=True)
    top_products = scored[:top]

    # 4) save real JSON via the real (SDK-free) writer
    write_results(category=category, products=top_products, output_dir=output_dir)
    yield {"type": "tool", "name": "mcp__research-tools__save_results",
           "agent": "lead", "summary": f"save: {len(top_products)} products"}
    await pause()

    # 5) sourcing-scout — find best-quality, EU-certified suppliers for the top N
    sourced = []
    if top_products:
        yield {"type": "subagent", "name": "sourcing-scout",
               "task": f"source best-quality EU-certified suppliers for top "
                       f"{MOCK_SOURCE_TOP_PRODUCTS} products"}
        await pause()
        for p in top_products[:MOCK_SOURCE_TOP_PRODUCTS]:
            yield {"type": "tool", "name": "WebSearch", "agent": "subagent",
                   "summary": f'suppliers: "{p["name"]}"'}
            await asyncio.sleep(0 if fast else 0.06)
            suppliers = _mock_suppliers_for(p["name"], cat)
            for s in suppliers:
                yield {"type": "tool", "name": "mcp__research-tools__score_supplier",
                       "agent": "subagent",
                       "summary": f'supplier: {s["name"]} = {s["score"]}'}
                await asyncio.sleep(0 if fast else 0.03)
            sourced.append({"product": p["name"], "score": p["score"],
                            "suppliers": suppliers})
        yield {"type": "text", "agent": "subagent",
               "text": f"Shortlisted suppliers for {len(sourced)} products."}
        await pause()

        # 6) save suppliers JSON via the real (SDK-free) writer
        write_suppliers(category=category, products=sourced, output_dir=output_dir)
        n_supp = sum(len(s["suppliers"]) for s in sourced)
        yield {"type": "tool", "name": "mcp__research-tools__save_suppliers",
               "agent": "lead", "summary": f"save: {n_supp} suppliers"}
        await pause()

    # Build the markdown report (streamed as lead text, like the real run)
    report = _build_report(category, top_products, sourced)
    for chunk in _chunks(report, 240):
        yield {"type": "text", "agent": "lead", "text": chunk}
        await asyncio.sleep(0 if fast else 0.04)

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    yield {"type": "result", "duration_ms": duration_ms, "cost_usd": 0.0,
           "num_turns": 0, "is_error": False, "report": report}


def _build_report(category: str, products: list, sourced: list | None = None) -> str:
    lines = [f"# Product Predictions: {category}", ""]
    lines.append(
        f"*(MOCK / offline demo — generated with canned data and zero API calls.)*"
    )
    lines.append("")
    top_name = products[0]["name"] if products else "—"
    lines.append(
        f"This offline demo ranked {len(products)} candidates in **{category}**. "
        f"The strongest opportunity is **{top_name}**. Scores come from the real "
        f"scoring tool; the underlying market signals are simulated."
    )
    lines.append("")
    lines.append("| Rank | Product | Score | Verdict | Why |")
    lines.append("|----:|---------|------:|---------|-----|")
    for i, p in enumerate(products, 1):
        lines.append(
            f"| {i} | {p['name']} | {p['score']} | {p['verdict']} | {p['rationale']} |"
        )
    lines.append("")

    if sourced:
        lines.append("## Top suppliers")
        lines.append(
            "Best-quality manufacturers/suppliers for the top products, ranked on "
            "quality, reputation and valid EU certifications (CE, ISO 9001, REACH, "
            "RoHS…)."
        )
        lines.append("")
        for entry in sourced:
            lines.append(f"### {entry['product']}")
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

    lines.append("## Methodology & caveats")
    lines.append(
        "Opportunity score (0–100) weights demand, growth, margin, low competition "
        "and feasibility. Supplier score (0–100) weights quality, reputation, EU "
        "certification, reliability and price. **This is mock mode:** candidates, "
        "suppliers and signals are generated offline for testing the pipeline and "
        "UI — they are not real market research. Run with a valid API key for live "
        "results, and always verify suppliers and certifications before ordering."
    )
    lines.append("")
    return "\n".join(lines)


def _chunks(text: str, n: int):
    for i in range(0, len(text), n):
        yield text[i : i + n]
