"""Run-history storage for the dashboard.

Every dashboard run (research / sourcing / full pipeline) is recorded in
SQLite so users can revisit past searches: the input parameters, each agent's
captured output, and the final report(s). Three tables, one per result type:

    runs               — one row per run: who, when, all input parameters,
                         status and result stats (duration / cost / turns).
    run_agent_outputs  — one row per agent per run: the text that agent
                         produced (what the UI shows in its "output" popup).
    run_reports        — one row per stage per run: the final Markdown report
                         (research report, supplier shortlist).

SDK-free and dependency-free (stdlib sqlite3), like auth.py. The recorder
mirrors the UI's event-attribution logic so what is stored matches what the
user saw live.
"""

from __future__ import annotations

import json
import sqlite3
import time

_DB_PATH: str | None = None


def init_db(path: str) -> None:
    """Create the history tables if needed. Call once at startup."""
    global _DB_PATH
    _DB_PATH = path
    con = _conn()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT NOT NULL,
            created_at  INTEGER NOT NULL,
            kind        TEXT NOT NULL,             -- research | sourcing | pipeline
            category    TEXT NOT NULL,
            top_n       INTEGER,
            provider    TEXT,
            model       TEXT,
            source_provider TEXT,
            source_model    TEXT,
            engine      TEXT,
            lang        TEXT,
            mock        INTEGER NOT NULL DEFAULT 0,
            status      TEXT NOT NULL DEFAULT 'running',  -- running|complete|errors|error
            duration_ms REAL,
            cost_usd    REAL,
            num_turns   INTEGER,
            error       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_runs_email ON runs(email, created_at DESC);
        CREATE TABLE IF NOT EXISTS run_agent_outputs(
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            agent   TEXT NOT NULL,
            output  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rao_run ON run_agent_outputs(run_id);
        CREATE TABLE IF NOT EXISTS run_reports(
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            stage   TEXT NOT NULL,                 -- research | sourcing
            report  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rr_run ON run_reports(run_id);
        """
    )
    # Migration: single combined target-market column ("Town, Province, Country").
    cols = {r[1] for r in con.execute("PRAGMA table_info(runs)").fetchall()}
    if "location" not in cols:
        con.execute("ALTER TABLE runs ADD COLUMN location TEXT")
    con.commit()
    con.close()


def _conn() -> sqlite3.Connection:
    if not _DB_PATH:
        raise RuntimeError("history.init_db() must be called first")
    con = sqlite3.connect(_DB_PATH)
    con.execute("PRAGMA foreign_keys=ON")
    return con


class RunRecorder:
    """Observes the SSE event stream of one run and persists it.

    Usage in an endpoint:
        rec = RunRecorder(email, kind="research", params={...})
        async for ev in stream:
            rec.observe(ev)
            yield _sse(ev)
        rec.finish()
    """

    def __init__(self, email: str, kind: str, params: dict):
        self._agents: dict[str, list[str]] = {}     # agent -> text parts
        self._lead: dict[str, list[str]] = {}       # stage -> lead text parts
        self._reports: dict[str, str] = {}          # stage -> final report
        self._stage = "sourcing" if kind == "sourcing" else "research"
        self._active_sub: str | None = None
        self._ok = False
        self._had_error = False
        self._errors: list[str] = []
        self._duration = 0.0
        self._cost = 0.0
        self._turns = 0
        self._done = False
        location = ", ".join(
            p.strip() for p in (params.get("town"), params.get("province"),
                                params.get("country")) if p and p.strip())
        con = _conn()
        cur = con.execute(
            "INSERT INTO runs(email, created_at, kind, category, top_n, provider,"
            " model, source_provider, source_model, engine, lang, mock, location)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (email, int(time.time()), kind,
             params.get("category", ""), params.get("top"),
             params.get("provider"), params.get("model"),
             params.get("source_provider"), params.get("source_model"),
             params.get("engine"), params.get("lang"),
             1 if params.get("mock") else 0, location),
        )
        self.run_id = cur.lastrowid
        con.commit()
        con.close()

    # -- event observation (mirrors the UI's attribution logic) --------------
    def observe(self, ev: dict) -> None:
        try:
            self._observe(ev)
        except Exception:
            pass  # recording must never break the live stream

    def _observe(self, ev: dict) -> None:
        et = ev.get("type")
        if et == "stage":
            self._active_sub = None
            if ev.get("stage"):
                self._stage = ev["stage"]
        elif et == "subagent":
            self._active_sub = ev.get("name")
        elif et == "fallback":
            # the failed attempt's text is discarded by the UI too
            self._had_error = False
            self._errors.clear()
        elif et == "text":
            text = ev.get("text") or ""
            if not text.strip():
                return
            owner = ev.get("owner")
            if owner:
                self._agents.setdefault(owner, []).append(text)
            elif ev.get("agent") == "lead":
                self._lead.setdefault(self._stage, []).append(text)
            elif self._active_sub:
                self._agents.setdefault(self._active_sub, []).append(text)
        elif et == "result":
            if ev.get("is_error"):
                self._had_error = True
                if ev.get("message") or ev.get("report"):
                    self._errors.append(ev.get("message") or ev.get("report"))
            else:
                self._ok = True
                report = (ev.get("report") or "").strip() \
                    or "".join(self._lead.get(self._stage, [])).strip()
                if report:
                    self._reports[self._stage] = report
            self._duration += ev.get("duration_ms") or 0
            self._cost += ev.get("cost_usd") or 0
            self._turns += ev.get("num_turns") or 0
        elif et == "error":
            self._had_error = True
            if ev.get("message"):
                self._errors.append(ev["message"])

    # -- persistence ----------------------------------------------------------
    def finish(self) -> None:
        if self._done:
            return
        self._done = True
        # A stage whose lead spoke but never got a result event still has output
        # worth keeping (e.g. connection dropped right at the end).
        for stage, parts in self._lead.items():
            if stage not in self._reports and "".join(parts).strip():
                self._reports.setdefault(stage, "".join(parts).strip())
        status = ("complete" if self._ok and not self._had_error
                  else "errors" if self._ok else "error")
        try:
            con = _conn()
            con.execute(
                "UPDATE runs SET status=?, duration_ms=?, cost_usd=?, num_turns=?,"
                " error=? WHERE id=?",
                (status, self._duration or None, self._cost or None,
                 self._turns or None,
                 ("\n---\n".join(self._errors)[:4000] or None), self.run_id),
            )
            for agent, parts in self._agents.items():
                out = "".join(parts).strip()
                if out:
                    con.execute(
                        "INSERT INTO run_agent_outputs(run_id, agent, output)"
                        " VALUES(?,?,?)", (self.run_id, agent, out))
            for stage, report in self._reports.items():
                con.execute(
                    "INSERT INTO run_reports(run_id, stage, report) VALUES(?,?,?)",
                    (self.run_id, stage, report))
            con.commit()
            con.close()
        except Exception:
            pass


# --- queries (always scoped to the signed-in user) ---------------------------

_RUN_COLS = ("id", "created_at", "kind", "category", "top_n", "provider",
             "model", "source_provider", "source_model", "engine", "lang",
             "mock", "status", "duration_ms", "cost_usd", "num_turns", "error",
             "location")


def list_runs(email: str, limit: int = 50) -> list[dict]:
    con = _conn()
    try:
        rows = con.execute(
            f"SELECT {','.join(_RUN_COLS)} FROM runs WHERE email=?"
            " ORDER BY created_at DESC, id DESC LIMIT ?", (email, limit)
        ).fetchall()
    finally:
        con.close()
    return [dict(zip(_RUN_COLS, r)) for r in rows]


def get_run(email: str, run_id: int) -> dict | None:
    con = _conn()
    try:
        row = con.execute(
            f"SELECT {','.join(_RUN_COLS)} FROM runs WHERE id=? AND email=?",
            (run_id, email)).fetchone()
        if not row:
            return None
        run = dict(zip(_RUN_COLS, row))
        run["agents"] = [
            {"agent": a, "output": o} for a, o in con.execute(
                "SELECT agent, output FROM run_agent_outputs WHERE run_id=?"
                " ORDER BY id", (run_id,)).fetchall()]
        run["reports"] = [
            {"stage": s, "report": r} for s, r in con.execute(
                "SELECT stage, report FROM run_reports WHERE run_id=?"
                " ORDER BY id", (run_id,)).fetchall()]
        return run
    finally:
        con.close()


def delete_run(email: str, run_id: int) -> bool:
    con = _conn()
    try:
        cur = con.execute("DELETE FROM runs WHERE id=? AND email=?",
                          (run_id, email))
        # cascade needs PRAGMA foreign_keys (set in _conn); belt & braces:
        con.execute("DELETE FROM run_agent_outputs WHERE run_id=?", (run_id,))
        con.execute("DELETE FROM run_reports WHERE run_id=?", (run_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()
