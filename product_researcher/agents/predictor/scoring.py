"""Deterministic opportunity-scoring formula — the predictor's core logic.

SDK-free on purpose: imports NOTHING from claude_agent_sdk, so both the tool
wrapper (tools.py) and the offline mock pipeline can share identical behaviour
without an API key or external dependencies.
"""

from __future__ import annotations

# Weights for the opportunity score. Tweak to change what the team rewards.
SCORE_WEIGHTS = {
    "demand": 0.30,        # how strong / growing is buyer interest
    "growth": 0.25,        # momentum of the trend
    "margin": 0.15,        # room for healthy margins
    "competition": 0.20,   # inverse: low competition scores high
    "feasibility": 0.10,   # how easy to source / build / launch
}


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def compute_score(
    name: str,
    demand: float,
    growth: float,
    margin: float,
    competition: float,
    feasibility: float,
) -> dict:
    """Return the opportunity-score payload (name, score, verdict, breakdown).

    Competition is a cost, not a benefit, so it is inverted (10 = no competition).
    """
    demand = _clamp(float(demand))
    growth = _clamp(float(growth))
    margin = _clamp(float(margin))
    competition = _clamp(float(competition))
    feasibility = _clamp(float(feasibility))

    competition_inv = 10.0 - competition

    weighted = (
        demand * SCORE_WEIGHTS["demand"]
        + growth * SCORE_WEIGHTS["growth"]
        + margin * SCORE_WEIGHTS["margin"]
        + competition_inv * SCORE_WEIGHTS["competition"]
        + feasibility * SCORE_WEIGHTS["feasibility"]
    )
    score = round(weighted * 10, 1)  # scale 0-10 -> 0-100

    if score >= 75:
        verdict = "Strong bet"
    elif score >= 60:
        verdict = "Promising"
    elif score >= 45:
        verdict = "Watch"
    else:
        verdict = "Pass"

    return {
        "name": name or "unnamed",
        "score": score,
        "verdict": verdict,
        "breakdown": {
            "demand": demand,
            "growth": growth,
            "margin": margin,
            "competition": competition,
            "competition_inverted": competition_inv,
            "feasibility": feasibility,
        },
    }
