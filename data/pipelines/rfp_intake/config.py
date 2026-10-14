"""Single place that must match CONTEXT-healthcore.md (Milestone 9).

TODO: replace DEPARTMENTS and RFP_CRITERIA with the exact department names,
contacts and RFP format from your CONTEXT file. Everything else in the
pipeline reads from here, so nothing else needs to change.
"""

# key -> department definition. The key is what is stored in Postgres.
DEPARTMENTS: dict[str, dict[str, str]] = {
    "clinical_operations": {
        "label": "Clinical Operations",
        "focus": "clinic locations, patient volumes, supply usage, service levels, staffing needs",
        "contact_role": "TODO: contact role from CONTEXT",
    },
    "procurement": {
        "label": "Procurement",
        "focus": "products or services requested, quantities, specifications, delivery terms, suppliers",
        "contact_role": "TODO: contact role from CONTEXT",
    },
    "legal_compliance": {
        "label": "Legal & Compliance",
        "focus": "contract terms, regulatory requirements, data privacy (PHI), certifications, liability",
        "contact_role": "TODO: contact role from CONTEXT",
    },
    "finance": {
        "label": "Finance",
        "focus": "pricing requests, budget, payment terms, currency, invoicing",
        "contact_role": "TODO: contact role from CONTEXT",
    },
}

# What makes a document a legitimate RFP for this company.
RFP_CRITERIA = (
    "A legitimate RFP is a request from a client (formal or informal, e.g. a long email) "
    "asking HealthCore for a commercial proposal. It normally states what is needed "
    "(scope), asks for pricing or a quote, and mentions a deadline or timeline. "
    "Invoices, newsletters, resumes, contracts already signed, spam and unrelated "
    "documents are NOT RFPs."
)

MIN_CLASSIFIER_CONFIDENCE = 0.5
ROUTING_NEXT = "proposal_generation"  # handoff target for Part 2
