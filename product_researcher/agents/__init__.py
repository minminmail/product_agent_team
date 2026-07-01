"""Agent team package for the product researcher.

Each specialist subagent lives in its own folder, holding its definition (and,
where it owns them, its tools and pure logic):

  trend_scout/          -> finds emerging products / signals via web search
  market_analyst/       -> sizes demand, competition, margins, pricing
  audience_researcher/  -> builds target customer segments and buyer personas
  competitor_analyst/   -> profiles rival brands
  predictor/            -> scores candidates (owns the scoring formula + tool)

The lead orchestrator (configured in main.py) delegates to these subagents via
the built-in Agent (Task) tool, then assembles the final report.

`AGENTS` is assembled lazily (PEP 562 module __getattr__) so that importing a
pure submodule like `predictor.scoring` never drags in claude_agent_sdk — which
is what keeps the offline mock pipeline SDK-free.
"""

from __future__ import annotations

# (display name -> folder module). Order defines the order in the AGENTS dict.
_AGENT_MODULES = [
    ("trend-scout", "trend_scout"),
    ("market-analyst", "market_analyst"),
    ("audience-researcher", "audience_researcher"),
    ("competitor-analyst", "competitor_analyst"),
    ("predictor", "predictor"),
]

__all__ = ["AGENTS"]


def _build_agents() -> dict:
    import importlib

    agents = {}
    for name, mod in _AGENT_MODULES:
        module = importlib.import_module(f"{__name__}.{mod}.agent")
        agents[name] = module.AGENT
    return agents


def __getattr__(attr: str):
    # Built on first access so `from .agents import AGENTS` works while plain
    # submodule imports stay SDK-free.
    if attr == "AGENTS":
        agents = _build_agents()
        globals()["AGENTS"] = agents
        return agents
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")
