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

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .mock import run_stream_mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
REPORTS_DIR = os.path.abspath(os.environ.get("PR_REPORTS_DIR", os.path.join(BASE_DIR, "reports")))
os.makedirs(REPORTS_DIR, exist_ok=True)

app = FastAPI(title="Product Researcher Dashboard")


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "has_key": bool(os.getenv("ANTHROPIC_API_KEY"))})


@app.get("/api/has_report")
async def has_report(category: str = Query(..., min_length=2)) -> JSONResponse:
    """Whether a research report exists for this category (gates Stage 2 in the UI)."""
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
    category: str = Query(..., min_length=2),
    top: int = Query(10, ge=1, le=30),
    model: str = Query("sonnet"),
    mock: bool = Query(False, description="Run fully offline with canned data (no API key/credits)."),
) -> StreamingResponse:
    """Server-Sent Events stream of the research pipeline."""

    async def event_source():
        try:
            if mock:
                async for ev in run_stream_mock(category, top, REPORTS_DIR, model):
                    yield _sse(ev)
            else:
                if not os.getenv("ANTHROPIC_API_KEY"):
                    yield _sse({
                        "type": "error",
                        "message": "ANTHROPIC_API_KEY is not set. Tip: tick 'Mock mode' "
                                   "to run offline with no key or credits.",
                    })
                    return
                # Import the SDK-backed pipeline lazily so mock mode never
                # requires claude_agent_sdk to be installed.
                from .events import run_stream
                async for ev in run_stream(category, top, REPORTS_DIR, model):
                    yield _sse(ev)
        except Exception as exc:  # never leave the stream hanging
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        yield _sse({"type": "done"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sourcing")
async def sourcing(
    category: str = Query(..., min_length=2),
    top: int = Query(3, ge=1, le=10),
    per: int = Query(10, ge=1, le=20),
    model: str = Query("sonnet"),
    mock: bool = Query(False, description="Run fully offline with canned suppliers (no API key/credits)."),
) -> StreamingResponse:
    """SSE stream of the INDEPENDENT supplier-sourcing agent.

    Reads the saved predictions_<category>.json produced by the research agent.
    """

    async def event_source():
        try:
            if mock:
                from supplier_sourcer.mock import run_stream_mock as source_mock
                async for ev in source_mock(category, REPORTS_DIR, REPORTS_DIR, model, top, per):
                    yield _sse(ev)
            else:
                if not os.getenv("ANTHROPIC_API_KEY"):
                    yield _sse({
                        "type": "error",
                        "message": "ANTHROPIC_API_KEY is not set. Tip: tick 'Mock mode' "
                                   "to run offline with no key or credits.",
                    })
                    return
                # Lazy import so mock mode never requires claude_agent_sdk.
                from supplier_sourcer.events import run_stream as source_stream
                async for ev in source_stream(category, REPORTS_DIR, REPORTS_DIR, model, top, per):
                    yield _sse(ev)
        except Exception as exc:
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        yield _sse({"type": "done"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/report/{filename}")
async def get_report(filename: str):
    # Basename only: prevent path traversal.
    safe = os.path.basename(filename)
    path = os.path.join(REPORTS_DIR, safe)
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# Serve the dashboard at "/". Mounted last so /api/* routes take precedence.
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
