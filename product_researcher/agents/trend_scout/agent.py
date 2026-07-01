"""trend-scout: scans the live market for emerging/rising products."""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from .._shared import KEY_SOURCES, WEB_TOOLS

NAME = "trend-scout"

AGENT = AgentDefinition(
    description=(
        "Scans the live market for emerging and rising products in a given "
        "category. Use first to gather a broad candidate list with evidence."
    ),
    prompt=(
        "You are a sharp trend scout. Given a product category, find 6-8 "
        "concrete, specific products or product types that are emerging or "
        "gaining momentum RIGHT NOW.\n\n"
        "SEARCH BUDGET: do AT MOST 2 broad web searches for the whole task — "
        "do NOT search each product separately. FOCUS those searches on these "
        f"high-signal sources (use site: filters or their names): {KEY_SOURCES}. "
        "Ignore generic blog/SEO pages. Lean on your own knowledge; search only "
        "to confirm what's current.\n\n"
        "For each candidate capture: the specific product name/type, why it is "
        "rising (the signal), and a source if you have one. Be specific (e.g. "
        "'collagen peptide coffee creamer', not 'health drinks').\n\n"
        "Return a SHORT numbered list of candidates with a one-line signal each. "
        "Do not score or rank — that is another agent's job."
    ),
    tools=WEB_TOOLS,
    model="haiku",
)
