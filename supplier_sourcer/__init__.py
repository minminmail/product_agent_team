"""supplier_sourcer — an independent sourcing agent team.

A separate agent from `product_researcher`. It reads the product-research team's
saved output (`predictions_<category>.json`), picks the top products, and finds
the best-quality, EU-certified manufacturers/suppliers for each — writing a
`suppliers_<category>.json` file and a Markdown supplier report.

Because it works from a saved report rather than calling the research team
directly, the two agents are fully decoupled: each can run independently (and in
parallel on different categories).
"""
