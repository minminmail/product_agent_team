# Product Researcher — a Claude Agent SDK team

A small **multi-agent team** (Python + [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/python)) that scans the **live market** with web search and predicts which products are likely to become popular in any category you give it.

## The team

A lead orchestrator delegates to four specialist subagents:

| Agent | Role |
|-------|------|
| **trend-scout** | Web-searches for 8–15 specific emerging products + rising signals + sources |
| **market-analyst** | Scores each candidate 0–10 on demand, growth, margin, competition, feasibility |
| **predictor** | Turns sub-scores into a deterministic 0–100 opportunity score and ranks them |
| **sourcing-scout** | For the top 3 products, finds the best-quality, EU-certified manufacturers/suppliers and ranks up to 10 per product |

Scoring is done by in-process **custom tools** so ranking is transparent and consistent — not vibes. `score_product` computes the 0–100 opportunity score; `score_supplier` computes a 0–100 supplier-quality score weighting **quality, reputation, EU certification (CE/ISO/REACH/RoHS…), reliability and price**. Two more tools (`save_results`, `save_suppliers`) write the JSON outputs.

## Setup

Requires Python 3.10+.

```bash
cd agent_team
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then paste your ANTHROPIC_API_KEY
```

Get a key at https://console.anthropic.com/.

## Run — Web dashboard (recommended)

A local dashboard lets you launch a run and **watch the team work live** — which subagent is active, every web search and tool call, and the final report streaming in.

```bash
python -m product_researcher.server
# open http://127.0.0.1:8000
```

Type a category, pick Top N and a model, hit **Run research**. The left pane shows the live timeline and team status; the right pane renders the final ranked report with download links to the `.md` and `.json`.

The dashboard streams events over Server-Sent Events (`GET /api/research`) from the *same* pipeline the CLI uses, so behaviour is identical.

## Run — CLI

```bash
# basic
python -m product_researcher.main "smart home gadgets"

# options
python -m product_researcher.main "eco-friendly pet products" --top 8 --out ./reports --model opus
```

Output (written to `--out`, default `./reports`; the dashboard writes to `./reports`):

- `report_<category>.md` — executive summary + ranked table + **top suppliers** per product + methodology
- `predictions_<category>.json` — structured predictions for downstream use
- `suppliers_<category>.json` — per-product supplier shortlists (name, country, score, tier, certifications, source)

## Test it locally

Step-by-step to get it running on your own machine (macOS/Linux).

**1. Create a virtual environment and install dependencies**

```bash
cd agent_team
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Add your Anthropic API key**

```bash
cp .env.example .env              # then edit .env and paste your key
```

```
ANTHROPIC_API_KEY=sk-ant-...
```

Get a key at https://console.anthropic.com/.

**3a. Run the web dashboard** (recommended)

```bash
python -m product_researcher.server
# open http://127.0.0.1:8000
```

Type a category (e.g. `smart home gadgets`), pick Top N and a model, hit **Run research**. The status dot in the top-left turns green when your key is detected.

**3b. Or run the CLI**

```bash
python -m product_researcher.main "smart home gadgets" --top 8
```

Outputs land in `./reports/` as `report_<category>.md` and `predictions_<category>.json`.

### Mock mode — test with no API key and no credits

You can run the **entire** pipeline offline with canned data — real subagent steps, tool calls, scoring, ranked report and JSON output — without an API key or spending anything. Great for trying the dashboard and seeing how it all works.

Dashboard: tick the **"Mock mode"** checkbox before hitting Run.

CLI:

```bash
python -m product_researcher.main "smart home gadgets" --top 5 --mock
```

Mock runs use the real scoring/save tools, so the generated `report_*.md` and `predictions_*.json` are real files — only the market "research" is simulated. Switch mock off (and add a funded API key) for genuine live results.

**Smoke test (no API credits used)** — confirm everything imports and wires up:

```bash
python -c "from product_researcher import server, events, agents, tools, core, mock; print('imports OK')"
```

**Notes & troubleshooting**

- Requires **Python 3.10+** — check with `python3 --version`.
- A real research run makes live web searches and consumes API credits, so start with a small `--top` value.
- If `python3 -m venv` fails on macOS, install the command-line tools: `xcode-select --install`.
- The dashboard loads `marked.js` from a CDN to render the report, so it needs internet at view time (it already does, for web search).

## How it works

```
your category
     │
     ▼
  ┌─────────────┐  delegates (Agent tool)
  │  LEAD AGENT │ ───────────────────────────────────────────┐
  └─────────────┘                                             │
     │  1              2              3            4           ▼
     ▼            ▼            ▼            ▼      score_product +
 trend-scout → market-analyst → predictor → sourcing-scout    score_supplier
 (WebSearch)   (WebSearch)     (scoring)   (WebSearch +        (tools)
                                            supplier scoring)      │
                                                                   ▼
                              save_results + save_suppliers (JSON) + Markdown report
```

**Stage 1** (trend-scout → market-analyst → predictor) finds and ranks the products.
**Stage 2** (sourcing-scout) takes the top 3 and finds the best-quality, EU-certified
suppliers for each.

## Project layout

```
agent_team/
├─ product_researcher/
│  ├─ core.py      # pure, SDK-free scoring/save logic (shared by tools + mock)
│  ├─ tools.py     # SDK tool wrappers: score_product, save_results, score_supplier, save_suppliers
│  ├─ agents.py    # the 4 subagent definitions
│  ├─ events.py    # shared pipeline + SDK-message → UI-event translator
│  ├─ mock.py      # fully offline pipeline (no SDK / API key needed)
│  ├─ main.py      # CLI
│  └─ server.py    # FastAPI dashboard (SSE)
├─ static/index.html  # single-file dashboard frontend
├─ requirements.txt
└─ .env.example
```

## Tuning

- **Scoring weights** live in `product_researcher/core.py` — `SCORE_WEIGHTS` (product opportunity) and `SUPPLIER_WEIGHTS` (supplier quality). Change what the team rewards.
- **How many products get sourced** and **suppliers per product** live in `product_researcher/events.py` (`SOURCE_TOP_PRODUCTS`, `SUPPLIERS_PER_PRODUCT`).
- **Agent behaviour** lives in `product_researcher/agents.py` — edit prompts, models, or add a new subagent.
- **Pipeline / lead brief** lives in `product_researcher/events.py` (`build_lead_prompt`, `run_stream`).
- **Dashboard** is `product_researcher/server.py` + `static/index.html`.

### Why the Claude Agent SDK (not LangChain/LangGraph)?

The SDK gives subagent orchestration, tool calling, web search and permissions out of the box, so the team stays small. The dashboard taps the SDK's structured message stream directly — no extra framework needed just to observe the agents. LangGraph would only earn its place if you needed deterministic, branching control over the pipeline or model-swapping; for "run the team and watch it," this is simpler and more robust.

## Notes

Predictions are probabilistic and depend on live search results at run time; treat them as a prioritised hypothesis list, not a guarantee. The agents are instructed not to fabricate sources, but always sanity-check evidence before acting on it.
