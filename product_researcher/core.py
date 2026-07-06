"""Shared, dependency-free report I/O for the product-researcher team.

This module deliberately imports NOTHING from claude_agent_sdk, so the offline
mock pipeline (mock.py) can reuse it with zero external dependencies and no API
key. It holds the team-level results-writer and the predictions-file helpers
used to hand off to the supplier-sourcing agent.

The deterministic opportunity-scoring formula now lives with the agent that
owns it — agents/predictor/scoring.py — and is re-exported here (SCORE_WEIGHTS,
compute_score) for backwards compatibility with existing imports.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

# Re-export the predictor's scoring formula for backwards compatibility.
# scoring.py is SDK-free, so importing it keeps this module SDK-free too.
from .agents.predictor.scoring import SCORE_WEIGHTS, compute_score

__all__ = [
    "SCORE_WEIGHTS",
    "compute_score",
    "write_results",
    "predictions_path",
    "parse_report_products",
    "ensure_predictions_saved",
]


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


def predictions_path(category: str, output_dir: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in (category or "general")).strip("_").lower()
    return os.path.join(output_dir, f"predictions_{safe or 'general'}.json")


def parse_report_products(markdown: str) -> list:
    """Best-effort extraction of products from the report's ranked table
    (| Rank | Product | Score | Verdict | ... | Why |). Used as a fallback so
    Stage 2 has a handoff file even if the model didn't call the save tool."""
    # Multilingual models emit full-width pipes (｜) and decorated rank cells.
    md = (markdown or "").replace("｜", "|")
    _HEADERS = ("product", "产品", "产品名称", "producto")
    products = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        # Rank cell: a small number under light decoration — "1", "**1**",
        # "1.", "1)", "#1", "第1名", full-width "１"… Reduce to digits and
        # require the cell itself to be short (rules out prose/other tables).
        raw = cells[0].translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        digits = re.sub(r"\D", "", raw)
        if not digits or len(digits) > 3 or len(raw) > 12:
            continue
        name = cells[1].replace("*", "").strip()
        if not name or name.lower() in _HEADERS or set(name) <= set("-: "):
            continue
        score = 0.0
        if len(cells) >= 3:
            m = re.search(r"[\d.]+", cells[2])
            score = float(m.group()) if m else 0.0
        products.append({
            "name": name,
            "score": score,
            "verdict": cells[3] if len(cells) >= 4 else "",
            "rationale": cells[-1] if len(cells) >= 5 else "",
            "evidence": "",
        })
    if not products:
        # Last resort: a numbered list ("1. **Name** — why", "1) Name：…").
        for line in md.splitlines():
            m = re.match(r"^\s*(?:[-*]\s*)?([0-9０-９]{1,3})\s*[.)、．：:]\s+(.+)$",
                         line.strip())
            if not m:
                continue
            rest = m.group(2).strip()
            b = re.search(r"\*\*(.+?)\*\*", rest)
            name = (b.group(1) if b else
                    re.split(r"\s*[—–:：(（]\s*| - ", rest)[0]).replace("*", "").strip()
            if not name or name.lower() in _HEADERS:
                continue
            sm = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:/\s*100|分)", rest)
            products.append({"name": name[:80],
                             "score": float(sm.group(1)) if sm else 0.0,
                             "verdict": "", "rationale": rest[:200], "evidence": ""})
        products = products[:15]
    return products


def ensure_predictions_saved(category: str, output_dir: str, report_md: str) -> str | None:
    """If no predictions file exists for this category, derive one from the
    research report so supplier sourcing can proceed. Returns the path or None."""
    path = predictions_path(category, output_dir)
    if os.path.exists(path):
        return path
    products = parse_report_products(report_md)
    if not products:
        return None
    return write_results(category, products, output_dir)
