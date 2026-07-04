"""FastAPI web dashboard for the product-researcher team.

Run:
    python -m product_researcher.server
    # then open http://127.0.0.1:8000

Exposes:
    GET  /                      -> the dashboard (static/index.html)
    GET  /api/research (SSE)    -> streams live agent events for a category
    GET  /api/health           -> {"ok": true, "has_key": bool}
    GET  /api/report/{file}     -> download a generated report/JSON
"""

from __future__ import annotations

import json
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, history, mailer
from .mock import run_stream_mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
REPORTS_DIR = os.path.abspath(os.environ.get("PR_REPORTS_DIR", os.path.join(BASE_DIR, "reports")))
os.makedirs(REPORTS_DIR, exist_ok=True)

# User database for email login (sits next to the app; gitignored).
# Override with PR_USERS_DB if the default location can't host a SQLite file.
USERS_DB = os.environ.get("PR_USERS_DB", os.path.join(BASE_DIR, "users.db"))
auth.init_db(USERS_DB)
history.init_db(USERS_DB)   # run-history tables live in the same SQLite file
SESSION_COOKIE = "session"

# Only hard-block unverified users from running agents when explicitly opted in
# AND email can actually be sent. Off by default so a broken/unconfigured mail
# setup can never lock anyone out.
REQUIRE_VERIFICATION = os.getenv("REQUIRE_VERIFICATION", "").strip().lower() in (
    "1", "true", "yes", "on",
)

app = FastAPI(title="Product Researcher Dashboard")

# Shown when "Run on Groq" is clicked but the proxy/key isn't configured.
_GROQ_HINT = ("Run on Groq needs GROQ_API_KEY in .env and the proxy running "
              "(./run_proxy.sh). See LITELLM_GEMINI_SETUP.md.")


def _provider_setup(provider: str, model: str):
    """Map the selected run provider to (force_env, model, error).

    - anthropic → direct Anthropic (no proxy).
    - deepseek  → direct DeepSeek via its Anthropic-compatible API (no proxy);
      just needs DEEPSEEK_API_KEY in .env.
    - groq      → routed through the local LiteLLM proxy; the model name selects
      the backend in litellm_proxy.yaml.
    """
    from .events import _proxy_env, _deepseek_env, _deepseek_model, _env  # SDK-free helpers
    if provider == "deepseek":
        env = _deepseek_env()
        if env is None:
            return None, model, "DeepSeek run needs DEEPSEEK_API_KEY in .env."
        # Use the DeepSeek model chosen in the UI (e.g. deepseek-v4-flash /
        # deepseek-v4-pro); fall back to the DEEPSEEK_MODEL env default.
        ds_model = model if (model or "").startswith("deepseek") else _deepseek_model()
        return env, ds_model, None            # call DeepSeek's API directly
    if provider == "groq":
        if not _env("GROQ_API_KEY"):
            return None, model, ("Groq run needs GROQ_API_KEY in .env "
                                 "and the proxy running (./run_proxy.sh).")
        return _proxy_env(), provider, None   # model name routes the proxy
    return None, model, None   # anthropic (direct)


# --- Auth helpers & endpoints ------------------------------------------------

class Credentials(BaseModel):
    email: str
    password: str


def _current_user(request: Request) -> str | None:
    return auth.session_email(request.cookies.get(SESSION_COOKIE))


def _effective_verified(email: str) -> bool:
    # When email sending isn't configured, verification is meaningless — treat
    # everyone as verified so no banner/gating appears.
    return (not mailer.smtp_configured()) or auth.is_verified(email)


def _user_can_run(request: Request) -> tuple[str | None, str | None]:
    """Authenticated AND (verified, when email verification is available)."""
    email = _current_user(request)
    if not email:
        return None, "Please sign in to run the agents."
    if REQUIRE_VERIFICATION and mailer.smtp_configured() and not auth.is_verified(email):
        return None, ("Please verify your email before running the agents — "
                      "check your inbox, or use the Resend link in the banner.")
    return email, None


def _set_session_cookie(resp: JSONResponse, token: str) -> None:
    # secure=False so it works over http on localhost; set True behind HTTPS.
    resp.set_cookie(SESSION_COOKIE, token, max_age=60 * 60 * 24 * 14,
                    httponly=True, samesite="lax", path="/")


def _base_url(request: Request) -> str:
    return (os.getenv("APP_BASE_URL") or str(request.base_url)).rstrip("/")


def _send_verification(request: Request, email: str) -> bool:
    """Send a verification email. Returns True if it was sent."""
    if not mailer.smtp_configured():
        return False
    token = auth.create_token(email, "verify", auth.VERIFY_TTL)
    link = f"{_base_url(request)}/api/auth/verify?token={token}"
    try:
        mailer.send_verification_email(email, link)
        return True
    except Exception:
        return False


@app.post("/api/auth/signup")
async def signup(creds: Credentials, request: Request) -> JSONResponse:
    ok, err = auth.create_user(creds.email, creds.password)
    if not ok:
        return JSONResponse({"error": err}, status_code=400)
    email = creds.email.strip().lower()
    email_sent = _send_verification(request, email)
    resp = JSONResponse({"email": email, "verified": _effective_verified(email),
                         "email_sent": email_sent})
    _set_session_cookie(resp, auth.create_session(email))
    return resp


@app.post("/api/auth/login")
async def login(creds: Credentials) -> JSONResponse:
    if not auth.verify_user(creds.email, creds.password):
        return JSONResponse({"error": "Invalid email or password."}, status_code=401)
    email = creds.email.strip().lower()
    resp = JSONResponse({"email": email, "verified": _effective_verified(email)})
    _set_session_cookie(resp, auth.create_session(email))
    return resp


@app.get("/api/auth/verify")
async def verify(token: str = Query(...)) -> HTMLResponse:
    email = auth.consume_token(token, "verify")
    if not email:
        return HTMLResponse(
            "<p style='font-family:sans-serif'>This verification link is invalid or "
            "has expired. Please sign in and resend the verification email.</p>"
            "<p><a href='/'>Back to the dashboard</a></p>",
            status_code=400,
        )
    auth.mark_verified(email)
    return RedirectResponse(url="/?verified=1", status_code=303)


@app.post("/api/auth/resend")
async def resend(request: Request) -> JSONResponse:
    email = _current_user(request)
    if not email:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    if auth.is_verified(email):
        return JSONResponse({"already_verified": True})
    if not mailer.smtp_configured():
        return JSONResponse(
            {"error": "Email sending is not configured on the server."},
            status_code=503,
        )
    sent = _send_verification(request, email)
    if not sent:
        return JSONResponse({"error": "Could not send the email — check SMTP settings."},
                            status_code=502)
    return JSONResponse({"email_sent": True})


class EmailOnly(BaseModel):
    email: str


class ResetPayload(BaseModel):
    token: str
    password: str


@app.post("/api/auth/forgot")
async def forgot(payload: EmailOnly, request: Request) -> JSONResponse:
    # Always return the same response so we don't reveal which emails exist.
    generic = JSONResponse({"ok": True})
    email = payload.email.strip().lower()
    if auth.user_exists(email) and mailer.smtp_configured():
        token = auth.create_token(email, "reset", auth.RESET_TTL)
        link = f"{_base_url(request)}/?reset={token}"
        try:
            mailer.send_reset_email(email, link)
        except Exception:
            pass
    return generic


@app.post("/api/auth/reset")
async def reset(payload: ResetPayload) -> JSONResponse:
    email = auth.consume_token(payload.token, "reset")
    if not email:
        return JSONResponse(
            {"error": "This reset link is invalid or has expired."}, status_code=400)
    ok, err = auth.set_password(email, payload.password)
    if not ok:
        return JSONResponse({"error": err}, status_code=400)
    return JSONResponse({"ok": True})


@app.post("/api/auth/logout")
async def logout(request: Request) -> JSONResponse:
    auth.delete_session(request.cookies.get(SESSION_COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/api/auth/me")
async def me(request: Request) -> JSONResponse:
    email = _current_user(request)
    if not email:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    return JSONResponse({
        "email": email,
        "verified": _effective_verified(email),
        "email_configured": mailer.smtp_configured(),
    })


@app.get("/api/health")
async def health() -> JSONResponse:
    import asyncio as _asyncio
    from .events import _fallback_env, _proxy_reachable

    base_url = (os.getenv("ANTHROPIC_BASE_URL") or "").strip()

    # Gemini auto-fallback status: configured? and is the LiteLLM proxy up?
    fb = _fallback_env()
    gemini_configured = fb is not None
    proxy_url = fb["ANTHROPIC_BASE_URL"] if fb else None
    proxy_reachable = False
    if fb:
        proxy_reachable = await _asyncio.to_thread(_proxy_reachable, proxy_url, 0.6)

    return JSONResponse({
        "ok": True,
        "has_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        # Where live runs send LLM calls — a custom base URL (e.g. a LiteLLM
        # proxy → Gemini) or Anthropic's default endpoint.
        "base_url": base_url or "https://api.anthropic.com",
        "custom_endpoint": bool(base_url),
        # Gemini fallback health for the UI indicator.
        "gemini_configured": gemini_configured,
        "gemini_proxy_url": proxy_url,
        "gemini_proxy_reachable": proxy_reachable,
    })


@app.get("/api/has_report")
async def has_report(request: Request, category: str = Query(..., min_length=2)) -> JSONResponse:
    """Whether a research report exists for this category (gates Stage 2 in the UI)."""
    if not _current_user(request):
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    from supplier_sourcer.core import list_available_reports, load_predictions

    pred = load_predictions(category, REPORTS_DIR)
    exists = bool(pred and pred.get("products"))
    return JSONResponse({
        "exists": exists,
        "product_count": len(pred.get("products", [])) if exists else 0,
        "available": list_available_reports(REPORTS_DIR),
    })


@app.get("/api/research")
async def research(
    request: Request,
    category: str = Query(..., min_length=2),
    top: int = Query(5, ge=1, le=30),
    model: str = Query("haiku"),
    provider: str = Query("anthropic", description="'groq' to force the free proxy."),
    mock: bool = Query(False, description="Run fully offline with canned data (no API key/credits)."),
    lang: str = Query("en", description="Report language: en | zh | es."),
) -> StreamingResponse:
    """Server-Sent Events stream of the research pipeline."""

    async def event_source():
        rec = None
        try:
            email, gate = _user_can_run(request)
            if gate:
                yield _sse({"type": "error", "message": gate})
                return
            rec = history.RunRecorder(email, "research", {
                "category": category, "top": top, "provider": provider,
                "model": model, "lang": lang, "mock": mock})
            if mock:
                async for ev in run_stream_mock(category, top, REPORTS_DIR, model):
                    rec.observe(ev)
                    yield _sse(ev)
            else:
                from .events import run_stream
                force_env, run_model, perr = _provider_setup(provider, model)
                if perr:
                    rec.observe({"type": "error", "message": perr})
                    yield _sse({"type": "error", "message": perr}); return
                if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
                    msg = ("ANTHROPIC_API_KEY is not set. Tip: use a Free "
                           "provider (Groq / Mock) instead.")
                    rec.observe({"type": "error", "message": msg})
                    yield _sse({"type": "error", "message": msg}); return
                async for ev in run_stream(category, top, REPORTS_DIR, run_model, force_env=force_env, lang=lang):
                    rec.observe(ev)
                    yield _sse(ev)
        except Exception as exc:  # never leave the stream hanging
            if rec:
                rec.observe({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            if rec:
                rec.finish()
        yield _sse({"type": "done"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sourcing")
async def sourcing(
    request: Request,
    category: str = Query(..., min_length=2),
    top: int = Query(2, ge=1, le=10),
    per: int = Query(5, ge=1, le=20),
    model: str = Query("haiku"),
    provider: str = Query("anthropic", description="'groq' to force the free proxy."),
    mock: bool = Query(False, description="Run fully offline with canned suppliers (no API key/credits)."),
    lang: str = Query("en", description="Report language: en | zh | es."),
) -> StreamingResponse:
    """SSE stream of the INDEPENDENT supplier-sourcing agent.

    Reads the saved predictions_<category>.json produced by the research agent.
    """

    async def event_source():
        rec = None
        try:
            email, gate = _user_can_run(request)
            if gate:
                yield _sse({"type": "error", "message": gate})
                return
            rec = history.RunRecorder(email, "sourcing", {
                "category": category, "top": top, "provider": provider,
                "model": model, "lang": lang, "mock": mock})
            if mock:
                from supplier_sourcer.mock import run_stream_mock as source_mock
                async for ev in source_mock(category, REPORTS_DIR, REPORTS_DIR, model, top, per):
                    rec.observe(ev)
                    yield _sse(ev)
            else:
                from supplier_sourcer.events import run_stream as source_stream
                force_env, run_model, perr = _provider_setup(provider, model)
                if perr:
                    rec.observe({"type": "error", "message": perr})
                    yield _sse({"type": "error", "message": perr}); return
                if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
                    msg = ("ANTHROPIC_API_KEY is not set. Tip: use a Free "
                           "provider (Groq / Mock) instead.")
                    rec.observe({"type": "error", "message": msg})
                    yield _sse({"type": "error", "message": msg}); return
                async for ev in source_stream(category, REPORTS_DIR, REPORTS_DIR, run_model, top, per, force_env=force_env, lang=lang):
                    rec.observe(ev)
                    yield _sse(ev)
        except Exception as exc:
            if rec:
                rec.observe({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            if rec:
                rec.finish()
        yield _sse({"type": "done"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/pipeline")
async def pipeline(
    request: Request,
    category: str = Query(..., min_length=2),
    top: int = Query(5, ge=1, le=30),
    source_top: int = Query(2, ge=1, le=10),
    per: int = Query(5, ge=1, le=20),
    model: str = Query("haiku"),
    provider: str = Query("anthropic", description="'groq' to force the free proxy."),
    source_provider: str = Query("", description="Provider for Stage 2 sourcing; blank = same as research."),
    source_model: str = Query("", description="Model for Stage 2 sourcing; blank = same as research."),
    engine: str = Query("", description="'langgraph' to use the LangGraph engine; else deterministic."),
    mock: bool = Query(False, description="Run the whole pipeline offline (no API key/credits)."),
    lang: str = Query("en", description="Report language: en | zh | es."),
) -> StreamingResponse:
    """SSE stream of the orchestrator (Amanda): research, then supplier sourcing."""

    async def event_source():
        rec = None
        try:
            email, gate = _user_can_run(request)
            if gate:
                yield _sse({"type": "error", "message": gate})
                return
            rec = history.RunRecorder(email, "pipeline", {
                "category": category, "top": top, "provider": provider,
                "model": model, "source_provider": source_provider,
                "source_model": source_model, "engine": engine or "standard",
                "lang": lang, "mock": mock})
            force_env = None
            run_model = model
            sourcing_model = None          # None → run_pipeline reuses the research model
            sourcing_force_env = None
            if not mock:
                force_env, run_model, perr = _provider_setup(provider, model)
                if perr:
                    rec.observe({"type": "error", "message": perr})
                    yield _sse({"type": "error", "message": perr}); return
                if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
                    msg = ("ANTHROPIC_API_KEY is not set. Tip: use a Free "
                           "provider (Groq / Mock) instead.")
                    rec.observe({"type": "error", "message": msg})
                    yield _sse({"type": "error", "message": msg}); return
                # Optional Stage 2 (sourcing) override — a different model/provider
                # than research (e.g. keep research cheap on DeepSeek, source on Anthropic).
                if source_provider.strip():
                    sourcing_force_env, sourcing_model, s_perr = _provider_setup(source_provider, source_model)
                    if s_perr:
                        rec.observe({"type": "error", "message": "Sourcing model — " + s_perr})
                        yield _sse({"type": "error", "message": "Sourcing model — " + s_perr}); return
                    if source_provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
                        msg = "Sourcing model needs ANTHROPIC_API_KEY set."
                        rec.observe({"type": "error", "message": msg})
                        yield _sse({"type": "error", "message": msg}); return
            # Engine selection: explicit ?engine=langgraph, else USE_LANGGRAPH env.
            use_langgraph = (engine.strip().lower() == "langgraph") or (
                engine == "" and
                os.getenv("USE_LANGGRAPH", "").strip().lower() in ("1", "true", "yes", "on"))
            if use_langgraph:
                try:
                    from orchestrator.graph import run_pipeline_graph as run_pipeline
                except ImportError:
                    msg = "LangGraph engine isn't installed. Run: pip install langgraph"
                    rec.observe({"type": "error", "message": msg})
                    yield _sse({"type": "error", "message": msg})
                    return
            else:
                from orchestrator.pipeline import run_pipeline
            async for ev in run_pipeline(category, top, source_top, per, REPORTS_DIR, run_model, mock,
                                         force_env=force_env, sourcing_model=sourcing_model,
                                         sourcing_force_env=sourcing_force_env, lang=lang):
                rec.observe(ev)
                yield _sse(ev)
        except Exception as exc:
            if rec:
                rec.observe({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            if rec:
                rec.finish()
        yield _sse({"type": "done"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Search history (stored per user in SQLite) ------------------------------

@app.get("/api/history")
async def history_list(request: Request, limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """List the signed-in user's past runs (parameters + status), newest first."""
    email = _current_user(request)
    if not email:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    return JSONResponse({"runs": history.list_runs(email, limit)})


@app.get("/api/history/{run_id}")
async def history_detail(run_id: int, request: Request) -> JSONResponse:
    """Full detail of one run: parameters, per-agent outputs, final reports."""
    email = _current_user(request)
    if not email:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    run = history.get_run(email, run_id)
    if not run:
        return JSONResponse({"error": "Not found."}, status_code=404)
    return JSONResponse(run)


@app.delete("/api/history/{run_id}")
async def history_delete(run_id: int, request: Request) -> JSONResponse:
    email = _current_user(request)
    if not email:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    return JSONResponse({"deleted": history.delete_run(email, run_id)})


@app.get("/api/report/{filename}")
async def get_report(filename: str, request: Request):
    if not _current_user(request):
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    # Basename only: prevent path traversal.
    safe = os.path.basename(filename)
    path = os.path.join(REPORTS_DIR, safe)
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# Serve the dashboard HTML with no-store so the browser always loads the latest
# version (avoids stale-cache 304s serving an old index.html after edits).
@app.get("/")
async def dashboard():
    index_file = os.path.join(STATIC_DIR, "index.html")
    # Explicit text/html so the browser always renders (not downloads/blank), and
    # no-store so it never serves a stale cached dashboard.
    return FileResponse(index_file, media_type="text/html",
                        headers={"Cache-Control": "no-store, max-age=0"})


# Serve remaining static assets at "/". Mounted last so /api/* and "/" take
# precedence. StaticFiles handles any other files under static/.
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def main() -> None:
    import uvicorn

    host = os.environ.get("PR_HOST", "127.0.0.1")
    port = int(os.environ.get("PR_PORT", "8000"))
    print(f"\n🚀 Product Researcher dashboard: http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
