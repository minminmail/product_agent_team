"""sourcing-scout agent package.

Owns the supplier-quality scoring formula (scoring.py) and the score_supplier
tool (tools.py), plus its agent definition (agent.py). scoring.py is SDK-free so
the mock pipeline can reuse it without importing claude_agent_sdk.
"""
