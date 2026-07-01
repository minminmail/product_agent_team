"""Agent team package for the supplier sourcer.

The team's one specialist subagent lives in its own folder, holding its
definition plus the tools and pure logic it owns:

  sourcing_scout/  -> finds and quality-ranks EU-certified suppliers; owns the
                      supplier-scoring formula (scoring.py) and score_supplier
                      tool (tools.py).

`AGENTS` is assembled lazily (PEP 562 module __getattr__) so importing a pure
submodule like `sourcing_scout.scoring` never drags in claude_agent_sdk — which
keeps the offline mock pipeline SDK-free.
"""

from __future__ import annotations

# (display name -> folder module).
_AGENT_MODULES = [
    ("sourcing-scout", "sourcing_scout"),
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
    if attr == "AGENTS":
        agents = _build_agents()
        globals()["AGENTS"] = agents
        return agents
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")
