"""predictor agent package.

Owns the deterministic opportunity-scoring formula (scoring.py) and the
score_product tool (tools.py), plus its agent definition (agent.py). scoring.py
is SDK-free so the mock pipeline can reuse it without importing claude_agent_sdk.
"""
