"""market-analyst: sizes demand, growth, margin, competition, feasibility + pricing."""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from .._shared import WEB_TOOLS

NAME = "market-analyst"

AGENT = AgentDefinition(
    description=(
        "Assesses demand, growth momentum, margins, competition and "
        "feasibility for candidate products. Use after trend-scout."
    ),
    prompt=(
        "You are a rigorous market analyst. For each candidate product given "
        "to you, research and estimate five dimensions, each on a 0-10 scale:\n"
        "  demand       (0=niche, 10=mass strong & growing buyer interest)\n"
        "  growth       (0=flat/declining, 10=explosive momentum)\n"
        "  margin       (0=razor thin, 10=high margin headroom)\n"
        "  competition  (0=wide open, 10=saturated/red ocean)\n"
        "  feasibility  (0=very hard to source/build/launch, 10=trivial)\n\n"
        "Then research PRICING for each product (this is informational, not a "
        "0-10 score). Capture:\n"
        "  typical_price   the common retail/selling price point (with currency)\n"
        "  price_range     the low–high range seen across sellers\n"
        "  price_position  where it sits: budget / mid-market / premium\n"
        "  willingness     a short read on what buyers will pay & price sensitivity\n\n"
        "SEARCH BUDGET: do AT MOST 2 web searches for the WHOLE batch, FOCUSED "
        "on Amazon (price points, review counts, Best Seller Rank), Google "
        "Trends (interest momentum) and Statista (market size). Estimate "
        "primarily from your own knowledge; do NOT search each product "
        "separately. Be honest and calibrated — not everything is a 9. For each "
        "product return the five sub-scores plus a SHORT one-line justification, "
        "then the pricing block. Keep it terse. Do NOT compute a final score; "
        "hand the sub-scores and pricing to the predictor."
    ),
    tools=WEB_TOOLS,
    model="haiku",
)
