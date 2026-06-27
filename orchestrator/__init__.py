"""orchestrator — a tiny coordinator agent ("Amanda").

Amanda runs the full pipeline by chaining the two independent agents in order:

  1. product_researcher  → finds & ranks products, writes predictions_<cat>.json
  2. supplier_sourcer    → reads that report, finds suppliers for the top products

The sequencing is deterministic (sourcing simply can't start until products
exist), so this is a thin coordinator — no extra LLM. Each underlying agent
stays independently runnable; Amanda just offers a one-shot "do everything" path.
"""
