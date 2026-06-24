"""Agent team definitions for the product researcher.

The team is a lead orchestrator plus three specialist subagents:

  trend-scout     -> finds emerging products / signals via web search
  market-analyst  -> sizes demand, competition, margins for each candidate
  predictor       -> scores candidates and predicts winners

The lead agent (configured in main.py) delegates to these subagents via the
built-in Agent (Task) tool, then assembles the final report.
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from .tools import TOOL_SAVE, TOOL_SCORE

# Tools the whole team is allowed to reach for.
WEB_TOOLS = ["WebSearch", "WebFetch"]

AGENTS: dict[str, AgentDefinition] = {
    "trend-scout": AgentDefinition(
        description=(
            "Scans the live market for emerging and rising products in a given "
            "category. Use first to gather a broad candidate list with evidence."
        ),
        prompt=(
            "You are a sharp trend scout. Given a product category, use web "
            "search to find 8-15 concrete, specific products or product types "
            "that are emerging or gaining momentum RIGHT NOW. Prioritise recency.\n\n"
            "For each candidate capture: the specific product name/type, why it is "
            "rising (the signal), and at least one cited source URL with a date. "
            "Look across marketplaces, trend reports, social buzz, search interest, "
            "news, and startup launches. Avoid generic categories — be specific "
            "(e.g. 'collagen peptide coffee creamer', not 'health drinks').\n\n"
            "Return a clean numbered list of candidates with their signals and "
            "sources. Do not score or rank — that is another agent's job."
        ),
        tools=WEB_TOOLS,
        model="sonnet",
    ),
    "market-analyst": AgentDefinition(
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
            "Use web search to ground each estimate; cite sources where you can. "
            "Be honest and calibrated — not everything is a 9. For each product "
            "return the five sub-scores plus a one-line justification each. "
            "Do NOT compute a final score; hand the sub-scores to the predictor."
        ),
        tools=WEB_TOOLS,
        model="sonnet",
    ),
    "predictor": AgentDefinition(
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
            "each, write a 1-2 sentence rationale explaining the prediction and "
            "keep its supporting evidence/source. Return the full ranked list."
        ),
        tools=[TOOL_SCORE],
        model="sonnet",
    ),
}
