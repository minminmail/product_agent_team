"""Shared streaming layer.

`run_stream()` runs the product-research pipeline and yields plain dict events
that both the CLI and the web dashboard consume. This keeps the SDK-message
translation in one place.

Event shapes (all have a "type"):
    {"type": "start",      "category", "top", "model"}
    {"type": "subagent",   "name", "task"}          # lead delegated to a subagent
    {"type": "tool",       "name", "summary", "agent"}   # a tool was called
    {"type": "tool_result","name", "is_error", "summary", "agent"}
    {"type": "text",       "text", "agent"}         # assistant prose
    {"type": "thinking",   "agent"}                 # model is reasoning (no content)
    {"type": "result",     "duration_ms", "cost_usd", "num_turns", "report"}
    {"type": "error",      "message"}
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

from .agents import AGENTS
from .tools import TOOL_SAVE, TOOL_SCORE, research_tools_server


def build_lead_prompt(category: str, top: int, output_dir: str) -> str:
    """The lead agent's task brief. Single source of truth for the pipeline."""
    return f"""You lead a product-research team. Goal: find and predict the products
most likely to become popular in the category: "{category}".

Run this pipeline using your subagents (delegate with the Task tool):

1. Call the `trend-scout` subagent to gather 8-15 specific emerging candidate
   products in this category, each with a rising signal and a cited source.
2. Call the `market-analyst` subagent to score every candidate on the five
   dimensions (demand, growth, margin, competition, feasibility, 0-10 each) and
   to research pricing (typical price, range, position, willingness to pay).
3. Call the `audience-researcher` subagent to build 3-4 target customer segments
   and buyer personas for the category and its candidates.
4. Call the `competitor-analyst` subagent to profile 4-6 rival brands
   (positioning, messaging, pricing, ad/marketing spend, strengths/gaps).
5. Call the `predictor` subagent to turn the sub-scores into final 0-100
   opportunity scores (it must use the {TOOL_SCORE} tool) and rank them.
6. Take the top {top} ranked products. Then call the `{TOOL_SAVE}` tool with:
   category="{category}", output_dir="{output_dir}", and products=[...] where
   each product is an object: name, score, verdict, rationale, evidence (a short
   source note or URL), and pricing (the market-analyst's pricing block).

Finally, output a clean Markdown report to me with these sections:
  # Product Predictions: {category}
  - a 2-3 sentence executive summary
  - a Markdown table of the top {top}: Rank | Product | Score | Verdict | Price | Why
  - an "Audience & personas" section summarising the target segments
  - a "Competitive landscape" section summarising the key rivals and whitespace
  - a short "Methodology & caveats" note (predictions are probabilistic).

Be concrete and evidence-driven. Do not fabricate sources.

(Supplier sourcing for the top products is handled by a separate agent — the
`supplier_sourcer` package — which reads the predictions_*.json you save here.)"""


def _make_options(model: str, output_dir: str, env: dict | None = None):
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        model=model,
        system_prompt=(
            "You are the lead of a product-research team. You are rigorous, "
            "evidence-driven, and you delegate to specialist subagents rather "
            "than doing everything yourself."
        ),
        agents=AGENTS,
        mcp_servers={"research-tools": research_tools_server},
        allowed_tools=[
            "Task",  # subagent dispatch
            "Agent",
            "WebSearch",   # WebFetch omitted to keep input tokens (cost) down
            TOOL_SCORE,
            TOOL_SAVE,
        ],
        # Non-interactive: never block waiting for a human to approve a tool.
        permission_mode="bypassPermissions",
        max_turns=30,
        cwd=output_dir,
        # env (merged over os.environ in the CLI subprocess) lets the fallback
        # re-point this run at the LiteLLM proxy → Gemini.
        env=env or {},
    )


def _read_dotenv_value(key: str) -> str | None:
    """Backstop: read KEY=value from the project .env directly, so the fallback
    works even if the server process was started before the key was added."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(here), ".env"),  # repo root (parent of package)
    ]
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip().strip('"').strip("'")
        except FileNotFoundError:
            continue
    return None


def _env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key) or _read_dotenv_value(key) or default


def _fallback_env() -> dict | None:
    """Env that re-points a run at the LiteLLM proxy (→ Groq or Gemini), or None
    if no fallback is configured. Enabled when GROQ_API_KEY or GEMINI_API_KEY is
    available (checked in the process env AND the .env file)."""
    if not (_env("GROQ_API_KEY") or _env("GEMINI_API_KEY")):
        return None
    base = (_env("GEMINI_FALLBACK_BASE_URL") or "http://localhost:4000").strip()
    # Must equal the proxy's master_key. Default to sk-local-test (same default
    # the proxy/run script uses). Do NOT fall back to the real ANTHROPIC_API_KEY
    # — that would mismatch the proxy and trigger "400 No connected db".
    key = (_env("LITELLM_MASTER_KEY") or "sk-local-test").strip()
    # ANTHROPIC_AUTH_TOKEN makes the CLI send the key as `Authorization: Bearer`,
    # which is what LiteLLM's master-key auth reads. With only ANTHROPIC_API_KEY
    # the CLI sends `x-api-key`, LiteLLM sees no Bearer token, tries a DB lookup,
    # and returns the misleading "No connected db".
    return {"ANTHROPIC_BASE_URL": base, "ANTHROPIC_API_KEY": key, "ANTHROPIC_AUTH_TOKEN": key}


def _proxy_reachable(base_url: str, timeout: float = 2.0) -> bool:
    """Quick TCP check so we never hand the SDK a dead proxy URL (which would
    hang the run). Returns False if the host:port can't be connected to."""
    try:
        u = urlparse(base_url)
        host = u.hostname or "localhost"
        port = u.port or (443 if u.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_summary(name: str, tool_input: dict) -> str:
    if not isinstance(tool_input, dict):
        return _short(tool_input)
    if name in ("WebSearch",) and "query" in tool_input:
        return f'search: "{tool_input["query"]}"'
    if name in ("WebFetch",) and "url" in tool_input:
        return f'fetch: {tool_input["url"]}'
    if name.endswith("score_product"):
        return f'score: {tool_input.get("name", "?")}'
    if name.endswith("save_results"):
        prods = tool_input.get("products", [])
        return f'save: {len(prods) if isinstance(prods, list) else "?"} products'
    return _short(tool_input)


# Fatal API/account errors can arrive flagged as "success" (or not flagged at
# all) while the real message sits in the result text. These phrases are
# specific to such errors and won't appear in a legitimate product report.
_FATAL_SIGNATURES = (
    "credit balance is too low",
    "your credit balance",
    "purchase credits",
    "plans & billing",
    "authentication_error",
    "invalid x-api-key",
    "rate_limit_error",
    "insufficient_quota",
)


def _looks_like_fatal(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in _FATAL_SIGNATURES)


def _result_is_error(message, report: str = "") -> bool:
    """Whether a ResultMessage is a genuine failure.

    A fatal error in the output (e.g. "credit balance is too low") is always a
    failure, even if the CLI didn't flag it. Conversely the CLI sometimes sets
    is_error=True with subtype "success" and no errors after a turn that DID
    produce a real report (it exits non-zero for shell consumers) — that is
    benign.
    """
    if _looks_like_fatal(report):
        return True
    if not getattr(message, "is_error", False):
        return False
    subtype = getattr(message, "subtype", "") or ""
    errors = getattr(message, "errors", None) or []
    if subtype == "success" and not errors and report.strip():
        return False  # clean success exit that produced real output
    return True


def _friendly_error(exc) -> str | None:
    """A user-facing error string, or None if the exception itself is benign.

    Returns None only for the "error result: success" case (caller then decides
    based on whether real output exists). Strips internal CLI branding.
    """
    msg = str(exc)
    if "error result: success" in msg.lower() and not _looks_like_fatal(msg):
        return None
    msg = msg.replace("Claude Code returned an error result:", "Agent run error:")
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


async def _attempt(prompt: str, model: str, output_dir: str, env: dict | None):
    """One query attempt. Yields (event, is_fatal) tuples; is_fatal is True for a
    final event caused by a fatal API error (e.g. credit balance too low)."""
    tool_use_owner: dict[str, str] = {}
    report_parts: list[str] = []
    result_emitted = False
    options = _make_options(model, output_dir, env=env)
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                agent = "lead" if not message.parent_tool_use_id else "subagent"
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if block.text.strip():
                            if agent == "lead":
                                report_parts.append(block.text)
                            yield {"type": "text", "agent": agent, "text": block.text}, False
                    elif isinstance(block, ThinkingBlock):
                        yield {"type": "thinking", "agent": agent}, False
                    elif isinstance(block, ToolUseBlock):
                        name = block.name
                        tin = block.input if isinstance(block.input, dict) else {}
                        if name in ("Task", "Agent"):
                            sub = (tin.get("subagent_type") or tin.get("subagentType")
                                   or tin.get("name") or "subagent")
                            tool_use_owner[block.id] = sub
                            yield {"type": "subagent", "name": sub,
                                   "task": _short(tin.get("description") or tin.get("prompt", ""), 200)}, False
                        else:
                            tool_use_owner[block.id] = name
                            yield {"type": "tool", "name": name, "agent": agent,
                                   "summary": _tool_summary(name, tin)}, False
            elif isinstance(message, ResultMessage):
                report = "".join(report_parts).strip() or (getattr(message, "result", "") or "").strip()
                is_err = _result_is_error(message, report)
                if not is_err:
                    result_emitted = True
                yield ({"type": "result",
                        "duration_ms": getattr(message, "duration_ms", None),
                        "cost_usd": getattr(message, "total_cost_usd", None),
                        "num_turns": getattr(message, "num_turns", None),
                        "is_error": is_err, "report": report},
                       is_err and _looks_like_fatal(report))
    except Exception as exc:
        msg = _friendly_error(exc)
        report = "".join(report_parts).strip()
        if msg is None and not _looks_like_fatal(report):
            if not result_emitted and report:
                yield {"type": "result", "duration_ms": None, "cost_usd": None,
                       "num_turns": None, "is_error": False, "report": report}, False
            elif not result_emitted:
                yield {"type": "error",
                       "message": "Agent run error: the run did not complete successfully."}, False
        elif not result_emitted:
            fatal = _looks_like_fatal(str(exc)) or _looks_like_fatal(report)
            yield {"type": "error", "message": msg or ("Agent run error: " + (report or "failed"))}, fatal


async def run_stream(
    category: str,
    top: int = 10,
    output_dir: str = "./reports",
    model: str = "sonnet",
    force_env: dict | None = None,
) -> AsyncIterator[dict]:
    """Run the pipeline, yielding UI events. If the primary (Anthropic) attempt
    hits a fatal API error such as a too-low credit balance, automatically
    retry the whole run via the LiteLLM proxy (when configured).

    force_env: when set (e.g. the "Run on Groq" button), route the WHOLE run
    through the proxy from the start — no Anthropic call, no fallback."""
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    prompt = build_lead_prompt(category, top, output_dir)

    yield {"type": "start", "category": category, "top": top, "model": model}

    if force_env is not None:
        if not _proxy_reachable(force_env.get("ANTHROPIC_BASE_URL", "")):
            yield {"type": "error",
                   "message": f"Proxy not reachable at {force_env.get('ANTHROPIC_BASE_URL')} — "
                              "start it with ./run_proxy.sh, then re-run."}
            return
        async for ev, _fatal in _attempt(prompt, model, output_dir, force_env):
            yield ev
        return

    fb = _fallback_env()
    envs = [None] + ([fb] if fb else [])
    for i, env in enumerate(envs):
        if i > 0:  # fallback attempt
            if not _proxy_reachable(env.get("ANTHROPIC_BASE_URL", "")):
                yield {"type": "error",
                       "message": f"Gemini fallback proxy not reachable at {env.get('ANTHROPIC_BASE_URL')} — "
                                  "start it with ./run_proxy.sh (and pip install \"litellm[proxy]\"), then re-run."}
                return
            yield {"type": "fallback",
                   "message": "Anthropic API unavailable (e.g. credit balance too low) — "
                              "retrying via the LiteLLM proxy → Gemini."}
        retry = False
        async for ev, fatal in _attempt(prompt, model, output_dir, env):
            if fatal and i == 0 and fb:
                retry = True  # suppress this fatal event; fall back instead
                break
            if fatal and i == 0 and not fb:
                hint = ("  (Gemini fallback not active — add GEMINI_API_KEY to .env "
                        "and run ./run_proxy.sh.)")
                if ev.get("type") == "error":
                    ev = {**ev, "message": ev.get("message", "") + hint}
                elif ev.get("type") == "result":
                    ev = {**ev, "report": (ev.get("report", "") + hint).strip()}
            yield ev
        if not retry:
            return


async def _segment_once(prompt, model, output_dir, env, collect):
    """One segment attempt. Yields (event, is_fatal) tuples."""
    options = _make_options(model, output_dir, env=env)
    tool_use_owner: dict[str, str] = {}
    seg_error_sent = False
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                agent = "lead" if not message.parent_tool_use_id else "subagent"
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if block.text.strip():
                            if collect is not None:
                                collect.append(block.text)
                            yield {"type": "text", "agent": agent, "text": block.text}, False
                    elif isinstance(block, ThinkingBlock):
                        yield {"type": "thinking", "agent": agent}, False
                    elif isinstance(block, ToolUseBlock):
                        name = block.name
                        tin = block.input if isinstance(block.input, dict) else {}
                        if name in ("Task", "Agent"):
                            sub = (tin.get("subagent_type") or tin.get("subagentType")
                                   or tin.get("name") or "subagent")
                            tool_use_owner[block.id] = sub
                            yield {"type": "subagent", "name": sub,
                                   "task": _short(tin.get("description") or tin.get("prompt", ""), 200)}, False
                        else:
                            tool_use_owner[block.id] = name
                            yield {"type": "tool", "name": name, "agent": agent,
                                   "summary": _tool_summary(name, tin)}, False
            elif isinstance(message, ResultMessage):
                seg_report = "".join(collect or []).strip() or (getattr(message, "result", "") or "").strip()
                if _result_is_error(message, seg_report):
                    seg_error_sent = True
                    yield ({"type": "error",
                            "message": "Agent run error: " + (seg_report or getattr(message, "subtype", "") or "failed")},
                           _looks_like_fatal(seg_report))
        if not seg_error_sent and _looks_like_fatal("".join(collect or [])):
            seg_error_sent = True
            yield {"type": "error", "message": "Agent run error: the agent reported a fatal error."}, True
    except Exception as exc:
        msg = _friendly_error(exc)
        if msg is not None and not seg_error_sent:
            yield {"type": "error", "message": msg}, (_looks_like_fatal(str(exc)) or _looks_like_fatal("".join(collect or [])))


async def run_segment(
    prompt: str,
    model: str,
    output_dir: str,
    collect: list[str] | None = None,
    force_env: dict | None = None,
) -> AsyncIterator[dict]:
    """Run ONE focused segment (a single lead prompt) and yield UI events,
    without the pipeline-level 'start'/'result' frames. On a fatal API error
    (e.g. credit balance too low) it retries via the LiteLLM proxy.

    force_env: route this segment through the proxy from the start (Groq button).
    """
    output_dir = os.path.abspath(output_dir)
    if force_env is not None:
        if not _proxy_reachable(force_env.get("ANTHROPIC_BASE_URL", "")):
            yield {"type": "error",
                   "message": f"Proxy not reachable at {force_env.get('ANTHROPIC_BASE_URL')} — "
                              "start it with ./run_proxy.sh, then re-run."}
            return
        async for ev, _fatal in _segment_once(prompt, model, output_dir, force_env, collect):
            yield ev
        return
    fb = _fallback_env()
    envs = [None] + ([fb] if fb else [])
    for i, env in enumerate(envs):
        if i > 0:  # fallback: discard the failed attempt's text and announce
            if not _proxy_reachable(env.get("ANTHROPIC_BASE_URL", "")):
                yield {"type": "error",
                       "message": f"Gemini fallback proxy not reachable at {env.get('ANTHROPIC_BASE_URL')} — "
                                  "start it with ./run_proxy.sh, then re-run."}
                return
            if collect is not None:
                collect.clear()
            yield {"type": "fallback",
                   "message": "Anthropic API unavailable (e.g. credit balance too low) — "
                              "retrying via the LiteLLM proxy → Gemini."}
        retry = False
        async for ev, fatal in _segment_once(prompt, model, output_dir, env, collect):
            if fatal and i == 0 and fb:
                retry = True
                break
            yield ev
        if not retry:
            return
