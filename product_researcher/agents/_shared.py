"""Shared configuration for the product-researcher team's subagents.

SDK-free on purpose: holds only the research-source config and the common web
tool list that several agents reference in their prompts. Each agent's own
definition (and any tools/logic it owns) lives in its own folder.
"""

from __future__ import annotations

import os
import re

# Tools the web-research agents are allowed to reach for. WebFetch is
# intentionally excluded: pulling full web pages into context is the biggest
# token cost, so the research agents rely on WebSearch result snippets instead.
WEB_TOOLS = ["WebSearch"]

# Built-in default high-signal sources (used if no file / env override exists).
DEFAULT_SOURCES = [
    "Amazon (Best Sellers, Movers & Shakers, review counts/ratings) — demand & pricing",
    "Google Trends — search-interest momentum",
    "Exploding Topics — emerging trends",
    "Trend Hunter — trend reports",
    "Statista — market size & statistics",
    "Reddit — community demand & honest discussion",
    "TikTok (#TikTokMadeMeBuyIt) — social virality",
    "Etsy / eBay — niche & handmade demand",
    "Product Hunt / Kickstarter — new product launches",
]


def _load_sources() -> list[str]:
    """Load the focus-source list. Priority: RESEARCH_SOURCES env var (comma/
    newline separated) → research_sources.txt (repo root or cwd) → defaults.
    Makes the list editable without touching code."""
    env = os.getenv("RESEARCH_SOURCES")
    if env:
        items = [s.strip() for s in re.split(r"[\n,]", env) if s.strip()]
        if items:
            return items
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(here))  # agents/ -> package -> repo
    for path in (os.path.join(os.getcwd(), "research_sources.txt"),
                 os.path.join(repo_root, "research_sources.txt")):
        try:
            with open(path, encoding="utf-8") as f:
                items = [ln.strip() for ln in f
                         if ln.strip() and not ln.strip().startswith("#")]
            if items:
                return items
        except FileNotFoundError:
            continue
    return DEFAULT_SOURCES


# High-signal sources for product/market research. Agents focus their few
# searches HERE (via site: filters or by name) instead of crawling the open web.
KEY_SOURCES = "; ".join(_load_sources())
