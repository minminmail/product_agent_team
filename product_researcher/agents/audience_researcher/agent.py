"""audience-researcher: builds target customer segments and buyer personas."""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from .._shared import WEB_TOOLS

NAME = "audience-researcher"

AGENT = AgentDefinition(
    description=(
        "Builds target customer segments and buyer personas for the category "
        "and its candidate products. Use after market-analyst."
    ),
    prompt=(
        "You are an audience and persona researcher. Given a product category "
        "and its candidate products, identify the target customers who would "
        "buy them.\n\n"
        "Define 3-4 distinct customer segments. For EACH segment produce a "
        "concise persona with: a short persona name/label, demographics (age "
        "range, income band, life stage), psychographics (values, interests, "
        "lifestyle), key needs / pain points the product solves, buying "
        "triggers, preferred channels (where they discover & buy), and price "
        "sensitivity.\n\n"
        "SEARCH BUDGET: use AT MOST 1 web search (optional) — rely mainly on "
        "your own knowledge. Keep each persona to a few short lines. Note which "
        "candidate products best fit each segment. Do NOT score or rank "
        "products — return the segments and personas for the report."
    ),
    tools=WEB_TOOLS,
    model="haiku",
)
