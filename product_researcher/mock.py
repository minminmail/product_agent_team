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
from .core import compute_score, write_results

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


# Canned audience segments / personas for the offline demo.
_MOCK_SEGMENTS = [
    {"name": "Early-adopter enthusiasts", "demo": "25–40, higher income, urban",
     "needs": "wants the newest thing first; willing to pay a premium",
     "channels": "YouTube reviews, Reddit, niche newsletters", "price": "low sensitivity"},
    {"name": "Practical value seekers", "demo": "30–55, mid income, suburban",
     "needs": "reliable, good value, solves a real daily pain point",
     "channels": "Amazon search, marketplace reviews, price comparison", "price": "high sensitivity"},
    {"name": "Gift buyers", "demo": "all ages, seasonal spikes",
     "needs": "easy, well-presented, safe choice for someone else",
     "channels": "social ads, gift guides, retail", "price": "moderate sensitivity"},
    {"name": "Prosumers / professionals", "demo": "28–50, uses it for work",
     "needs": "performance, durability, support; ROI matters",
     "channels": "trade communities, spec comparisons, direct", "price": "value-driven"},
]

# Canned competitor profiles for the offline demo.
_MOCK_COMPETITORS = [
    {"name": "MarketLeader Co.", "position": "premium incumbent",
     "messaging": "“trusted, best-in-class”", "price": "$$$",
     "spend": "heavy (TV + paid social)", "gap": "slow to innovate"},
    {"name": "ValueBrand", "position": "budget challenger",
     "messaging": "“great value for everyone”", "price": "$",
     "spend": "moderate (marketplace ads)", "gap": "thin quality perception"},
    {"name": "NicheStartup", "position": "design-led disruptor",
     "messaging": "“beautiful, modern, simple”", "price": "$$",
     "spend": "lean (organic + influencer)", "gap": "limited distribution"},
    {"name": "Generic White-label", "position": "commodity",
     "messaging": "price-only", "price": "$",
     "spend": "minimal", "gap": "no brand loyalty"},
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


def _price_for(seed: str) -> dict:
    """Deterministic mock pricing derived from a hash of the product name."""
    h = hashlib.sha256(("price:" + seed).encode()).digest()
    low = round(8 + (h[0] / 255) * 90, 2)          # $8–$98
    high = round(low * (1.4 + (h[1] / 255) * 1.1), 2)  # 1.4x–2.5x low
    typical = round(low + (high - low) * (0.3 + (h[2] / 255) * 0.4), 2)
    position = ("budget", "mid-market", "premium")[h[3] % 3]
    sensitivity = ("price-sensitive", "moderately sensitive", "value-driven")[h[4] % 3]
    return {
        "typical_price": f"${typical:.2f}",
        "price_range": f"${low:.2f}–${high:.2f}",
        "price_position": position,
        "willingness": f"buyers are {sensitivity} in this segment",
    }


# ---------------------------------------------------------------------------
# Pure stage helpers — deterministic, no streaming/IO. Shared by the linear
# mock (run_stream_mock) and the decomposed LangGraph nodes so both stay in
# sync from one source of truth.
# ---------------------------------------------------------------------------
def mock_candidates(category: str) -> list[tuple[str, str]]:
    """Return the (name, signal) candidate list for a category."""
    cat = category.strip().rstrip("s") if category.strip() else "product"
    return [(name.format(cat=cat), sig) for name, sig in _TEMPLATES]


def mock_analyse(candidates: list[tuple[str, str]]) -> list[tuple[str, str, dict, dict]]:
    """Attach deterministic sub-scores + pricing to each candidate."""
    return [(name, sig, _scores_for(name), _price_for(name)) for name, sig in candidates]


def mock_predict(analysed: list[tuple[str, str, dict, dict]], top: int) -> list[dict]:
    """Score (via the real scoring tool), rank, and take the top N."""
    scored = []
    for name, sig, sub, price in analysed:
        data = compute_score(name=name, **sub)
        scored.append({
            "name": name,
            "score": data["score"],
            "verdict": data["verdict"],
            "rationale": sig.capitalize() + ".",
            "evidence": "Mock signal (offline demo — no live source).",
            "breakdown": sub,
            "pricing": price,
        })
    scored.sort(key=lambda p: p["score"], reverse=True)
    return scored[:top]


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

    candidates = mock_candidates(category)

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
           "task": "score demand / growth / margin / competition / feasibility + pricing"}
    await pause()
    analysed = mock_analyse(candidates)
    for name, sig, sub, price in analysed:
        yield {"type": "tool", "name": "WebSearch", "agent": "subagent",
               "summary": f'sizing: "{name}"'}
        await asyncio.sleep(0 if fast else 0.06)
    yield {"type": "text", "agent": "subagent", "text": "Scored all candidates."}
    await pause()

    # 3) audience-researcher
    yield {"type": "subagent", "name": "audience-researcher",
           "task": "build target segments and buyer personas"}
    await pause()
    for seg in _MOCK_SEGMENTS:
        yield {"type": "tool", "name": "WebSearch", "agent": "subagent",
               "summary": f'audience: "{seg["name"]}"'}
        await asyncio.sleep(0 if fast else 0.05)
    yield {"type": "text", "agent": "subagent",
           "text": f"Defined {len(_MOCK_SEGMENTS)} target segments."}
    await pause()

    # 4) competitor-analyst
    yield {"type": "subagent", "name": "competitor-analyst",
           "task": "profile rival brands: positioning, messaging, ad spend"}
    await pause()
    for comp in _MOCK_COMPETITORS:
        yield {"type": "tool", "name": "WebSearch", "agent": "subagent",
               "summary": f'competitor: "{comp["name"]}"'}
        await asyncio.sleep(0 if fast else 0.05)
    yield {"type": "text", "agent": "subagent",
           "text": f"Profiled {len(_MOCK_COMPETITORS)} competitors."}
    await pause()

    # 5) predictor — use the REAL scoring tool (pure local, deterministic)
    yield {"type": "subagent", "name": "predictor",
           "task": "compute opportunity scores and rank"}
    await pause()
    for name, sig, sub, price in analysed:
        data = compute_score(name=name, **sub)
        yield {"type": "tool", "name": "mcp__research-tools__score_product",
               "agent": "subagent", "summary": f'score: {name} = {data["score"]}'}
        await asyncio.sleep(0 if fast else 0.05)

    top_products = mock_predict(analysed, top)

    # 4) save real JSON via the real (SDK-free) writer
    write_results(category=category, products=top_products, output_dir=output_dir)
    yield {"type": "tool", "name": "mcp__research-tools__save_results",
           "agent": "lead", "summary": f"save: {len(top_products)} products"}
    await pause()

    # Build the markdown report (streamed as lead text, like the real run)
    report = _build_report(category, top_products)
    for chunk in _chunks(report, 240):
        yield {"type": "text", "agent": "lead", "text": chunk}
        await asyncio.sleep(0 if fast else 0.04)

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    yield {"type": "result", "duration_ms": duration_ms, "cost_usd": 0.0,
           "num_turns": 0, "is_error": False, "report": report}


def _build_report(category: str, products: list) -> str:
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
    lines.append("| Rank | Product | Score | Verdict | Price | Why |")
    lines.append("|----:|---------|------:|---------|-------|-----|")
    for i, p in enumerate(products, 1):
        price = (p.get("pricing") or {}).get("typical_price", "—")
        lines.append(
            f"| {i} | {p['name']} | {p['score']} | {p['verdict']} | {price} | {p['rationale']} |"
        )
    lines.append("")
    lines.append("## Per-product scores & pricing")
    lines.append(
        "The market-analyst's per-product 0–10 sub-scores, plus the pricing read. "
        "*Opportunity* is the weighted 0–100 score the predictor computed from the sub-scores."
    )
    lines.append("")
    lines.append("| Product | Demand | Growth | Margin | Competition | Feasibility | Opportunity |")
    lines.append("|---------|------:|------:|------:|-----------:|-----------:|----------:|")
    for p in products:
        b = p.get("breakdown") or {}
        lines.append(
            f"| {p['name']} | {b.get('demand','—')} | {b.get('growth','—')} | "
            f"{b.get('margin','—')} | {b.get('competition','—')} | {b.get('feasibility','—')} | {p['score']} |"
        )
    lines.append("")
    lines.append("| Product | Typical price | Range | Position | Willingness to pay |")
    lines.append("|---------|---------------|-------|----------|--------------------|")
    for p in products:
        pr = p.get("pricing") or {}
        lines.append(
            f"| {p['name']} | {pr.get('typical_price','—')} | {pr.get('price_range','—')} | "
            f"{pr.get('price_position','—')} | {pr.get('willingness','—')} |"
        )
    lines.append("")
    lines.append("## Audience & personas")
    lines.append("| Segment | Who | Needs | Channels | Price sensitivity |")
    lines.append("|---------|-----|-------|----------|-------------------|")
    for s in _MOCK_SEGMENTS:
        lines.append(
            f"| {s['name']} | {s['demo']} | {s['needs']} | {s['channels']} | {s['price']} |"
        )
    lines.append("")
    lines.append("## Competitive landscape")
    lines.append("| Competitor | Positioning | Messaging | Price | Ad spend | Gap to exploit |")
    lines.append("|------------|-------------|-----------|-------|----------|----------------|")
    for c in _MOCK_COMPETITORS:
        lines.append(
            f"| {c['name']} | {c['position']} | {c['messaging']} | {c['price']} | {c['spend']} | {c['gap']} |"
        )
    lines.append("")
    lines.append("## Methodology & caveats")
    lines.append(
        "Opportunity score (0–100) weights demand, growth, margin, low competition "
        "and feasibility. **This is mock mode:** candidates and signals are "
        "generated offline for testing the pipeline and UI — they are not real "
        "market research. Run with a valid API key for live results."
    )
    lines.append("")
    return "\n".join(lines)


def _chunks(text: str, n: int):
    for i in range(0, len(text), n):
        yield text[i : i + n]
