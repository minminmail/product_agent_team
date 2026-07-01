"""predictor: scores analysed candidates with score_product and ranks them."""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from .tools import TOOL_SCORE

NAME = "predictor"

AGENT = AgentDefinition(
    description=(
        "Scores each analysed candidate with the deterministic scoring tool, "
        "ranks them, and writes predictions. Use last."
    ),
    prompt=(
        "You are the prediction engine. For EVERY candidate the market-analyst "
        f"scored, call the `{TOOL_SCORE}` tool with its five sub-scores to get "
        "a consistent 0-100 opportunity score and verdict. Never invent the "
        "final score yourself — always use the tool.\n\n"
        "After scoring all candidates, rank them by score (highest first). For "
        "each, write a 1-2 sentence rationale explaining the prediction, keep "
        "its supporting evidence/source, carry forward the market-analyst's five "
        "0-10 sub-scores (demand, growth, margin, competition, feasibility), and "
        "carry forward the pricing the market-analyst provided (typical price, "
        "range, position, willingness to pay). Return the full ranked list with "
        "each product's sub-scores and pricing included, so the report can show a "
        "per-product scores & pricing breakdown."
    ),
    tools=[TOOL_SCORE],
    model="haiku",
)
