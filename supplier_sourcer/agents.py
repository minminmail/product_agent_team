"""Agent definition for the supplier-sourcing team.

A lead orchestrator delegates to one specialist subagent:

  sourcing-scout -> for each given product, finds the best-quality, EU-certified
                    manufacturers/suppliers and scores them with score_supplier.
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from .tools import TOOL_SCORE_SUPPLIER

WEB_TOOLS = ["WebSearch", "WebFetch"]

AGENTS: dict[str, AgentDefinition] = {
    "sourcing-scout": AgentDefinition(
        description=(
            "Finds and quality-ranks real manufacturers/suppliers for given "
            "products, prioritising trustworthy, high-quality, EU-certified firms."
        ),
        prompt=(
            "You are a meticulous sourcing specialist. You are given a small list "
            "of products. For EACH product, use web search to find real, specific "
            "manufacturers or suppliers that could produce/supply it.\n\n"
            "Quality matters far more than quantity. Prioritise suppliers that are:\n"
            "  • TRUSTWORTHY — strong reputation, verifiable reviews, years in "
            "business, real company presence (not anonymous listings).\n"
            "  • HIGH QUALITY — good build quality, quality-control processes, "
            "low defect/complaint history.\n"
            "  • EU-CERTIFIED — hold valid, relevant certifications, especially "
            "EU ones: CE marking, ISO 9001, REACH, RoHS, EN standards, GS, etc. "
            "Capture which certifications each supplier actually holds.\n\n"
            "For each supplier capture: company name, country, the product it "
            "supplies, the certifications it holds, a one-line reputation note, "
            "and a cited source URL. Then call the "
            f"`{TOOL_SCORE_SUPPLIER}` tool with five 0-10 sub-scores (quality, "
            "reputation, certification, reliability, price) to get a consistent "
            "0-100 supplier-quality score — never invent the score yourself.\n\n"
            "Rank each product's suppliers by score (highest first). Do not "
            "fabricate companies, certifications, or sources — if you cannot "
            "verify a supplier, leave it out."
        ),
        tools=WEB_TOOLS + [TOOL_SCORE_SUPPLIER],
        model="sonnet",
    ),
}
