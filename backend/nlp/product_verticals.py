import re
from typing import Dict, List, Tuple
import numpy as np
from .embeddings import embed_texts


# Canonical product verticals and seed keywords (bootstrapped; refine over time)
VERTICALS: List[Dict] = [
    {
        "slug": "multicurrency-accounts-wallets",
        "name": "Multicurrency Accounts and Wallets",
        "keywords": [
            "wallet", "virtual account", "multi-currency", "multicurrency", "ledger balance", "iban", "account number",
        ],
        "jira_projects": [],
        "jira_labels": [],
        "zendesk_tags": [],
    },
    {
        "slug": "fee-engine-invoicing",
        "name": "Fee Engine and Invoicing",
        "keywords": [
            "fee", "fees", "pricing", "invoice", "invoicing", "surcharge", "rate card",
        ],
        "jira_projects": [],
        "jira_labels": ["invoice", "pricing"],
        "zendesk_tags": ["invoice", "pricing", "fees"],
    },
    {
        "slug": "payins-direct-debits",
        "name": "Payins and Direct Debits",
        "keywords": [
            "pay-in", "payin", "direct debit", "ach debit", "sepa dd", "pull funds", "bank transfer in", "incoming payment",
        ],
        "jira_projects": [],
        "jira_labels": ["direct-debit", "payin"],
        "zendesk_tags": ["direct_debit", "payin"],
    },
    {
        "slug": "fx-service",
        "name": "FX Service",
        "keywords": [
            "fx", "convert", "conversion", "quote", "rate", "swap", "order", "fx rate", "fx quote",
        ],
        "jira_projects": ["FX"],
        "jira_labels": ["fx", "rates", "quote"],
        "zendesk_tags": ["fx", "rate", "quote"],
    },
    {
        "slug": "treasury-management-gl",
        "name": "Treasury Management and GL Spoc",
        "keywords": [
            "treasury", "liquidity", "gl", "general ledger", "reconciliation", "nostro", "cash management",
        ],
        "jira_projects": [],
        "jira_labels": ["treasury", "recon", "gl"],
        "zendesk_tags": ["treasury", "reconciliation"],
    },
    {
        "slug": "payouts-reliability-api",
        "name": "Payouts Reliability and API Experience",
        "keywords": [
            "payout", "payouts api", "stp", "webhook", "idempotency", "beneficiary", "transfer api", "payment api",
        ],
        "jira_projects": [],
        "jira_labels": ["payouts_api", "stp"],
        "zendesk_tags": ["payouts", "api"],
    },
    {
        "slug": "swift-connect",
        "name": "Swift Connect",
        "keywords": [
            "swift", "mt103", "bic", "gpi", "mt202",
        ],
        "jira_projects": ["SWIFT"],
        "jira_labels": ["swift", "mt103", "bic"],
        "zendesk_tags": ["swift"],
    },
    {
        "slug": "network-payouts",
        "name": "Network Payouts",
        "keywords": [
            "local rails", "upi", "fps", "ach credit", "pix", "domestic payout", "local transfer",
        ],
        "jira_projects": [],
        "jira_labels": ["local-rails", "ach", "pix", "upi", "fps"],
        "zendesk_tags": ["ach", "pix", "upi", "fps"],
    },
    {
        "slug": "global-wires",
        "name": "Global wires",
        "keywords": [
            "wire", "wire transfer", "international wire", "cross-border wire", "swift wire",
        ],
        "jira_projects": ["WIRES"],
        "jira_labels": ["wire"],
        "zendesk_tags": ["wire"],
    },
    {
        "slug": "verify",
        "name": "Verify",
        "keywords": [
            "verify", "account verification", "name match", "beneficiary check", "account check",
        ],
        "jira_projects": ["VERIFY"],
        "jira_labels": ["verify"],
        "zendesk_tags": ["verify"],
    },
    {
        "slug": "client-onboarding",
        "name": "Client Onboarding",
        "keywords": [
            "kyb", "client onboarding", "entitlements", "go-live", "contracting",
        ],
        "jira_projects": ["CLIENT"],
        "jira_labels": ["onboarding", "kyb"],
        "zendesk_tags": ["kyb"],
    },
    {
        "slug": "customer-onboarding",
        "name": "Customer Onboarding",
        "keywords": [
            "kyc", "identity", "customer verification", "level 2", "level 3", "l2", "l3",
        ],
        "jira_projects": ["CUSTOMER"],
        "jira_labels": ["onboarding", "kyc"],
        "zendesk_tags": ["kyc"],
    },
    {
        "slug": "caas",
        "name": "CaaS",
        "keywords": [
            "compliance", "screening", "transaction monitoring", "cdd", "aml",
        ],
        "jira_projects": ["CAAS"],
        "jira_labels": ["compliance", "screening", "monitoring"],
        "zendesk_tags": ["compliance"],
    },
    {
        "slug": "data-reporting",
        "name": "Data and Reporting",
        "keywords": [
            "report", "bi", "dashboard", "export", "looker", "analytics",
        ],
        "jira_projects": [],
        "jira_labels": ["report", "export"],
        "zendesk_tags": ["report", "export"],
    },
    {
        "slug": "b2b-travel",
        "name": "B2B Travel",
        "keywords": [
            "vcc", "virtual card", "ota", "gds", "settlement", "travel",
        ],
        "jira_projects": ["TRAVEL"],
        "jira_labels": ["vcc", "travel"],
        "zendesk_tags": ["travel"],
    },
    {
        "slug": "platform-issuing",
        "name": "Platform Issuing",
        "keywords": [
            "issuing", "cards", "card", "pan", "tokenization", "authorization", "auth", "issuer",
        ],
        "jira_projects": ["ISSUING"],
        "jira_labels": ["cards", "issuing"],
        "zendesk_tags": ["issuing", "card"],
    },
    {
        "slug": "api-docs",
        "name": "API and API Docs",
        "keywords": [
            "openapi", "swagger", "docs", "documentation", "api reference", "reference guide",
        ],
        "jira_projects": ["DOCS"],
        "jira_labels": ["docs", "openapi"],
        "zendesk_tags": ["docs"],
    },
    {
        "slug": "client-portal",
        "name": "Client Portal",
        "keywords": [
            "portal", "dashboard ui", "non-api", "web app", "client portal",
        ],
        "jira_projects": ["PORTAL"],
        "jira_labels": ["portal"],
        "zendesk_tags": ["portal"],
    },
]


def _tokenize(text: str) -> List[str]:
    # Very simple tokenization; keywords include multi-word phrases so we also substring match
    return re.findall(r"[a-z0-9_\-/]+", text.lower())


# ---- Embedding prototypes for each vertical ----
_PROTO_SLUGS: List[str] | None = None
_PROTO_TEXTS: List[str] | None = None
_PROTO_VECS: np.ndarray | None = None


def _ensure_prototypes():
    global _PROTO_SLUGS, _PROTO_TEXTS, _PROTO_VECS
    if _PROTO_VECS is not None:
        return
    proto_texts = []
    slugs = []
    for v in VERTICALS:
        name = v["name"]
        kws = " ".join(v.get("keywords", []))
        desc = f"{name}. {kws}".strip()
        proto_texts.append(desc)
        slugs.append(v["slug"])
    vecs = embed_texts(proto_texts)  # already normalized in embeddings.py
    _PROTO_SLUGS = slugs
    _PROTO_TEXTS = proto_texts
    _PROTO_VECS = vecs


def rule_based_vertical(source: str, labels_csv: str = "", project: str = "") -> Tuple[str | None, str | None, float, Dict]:
    """Return a vertical using only structured rules (JIRA project/labels, Zendesk tags)."""
    labels = {p.strip().lower() for p in (labels_csv or "").split(",") if p.strip()}
    project_key = (project or "").strip().upper()

    candidates: List[Tuple[str, str, float, Dict]] = []
    for v in VERTICALS:
        vslug = v["slug"]; vname = v["name"]
        if source == "jira" and project_key and project_key in {p.upper() for p in v.get("jira_projects", [])}:
            candidates.append((vslug, vname, 0.95, {"rule": "jira_project", "project": project_key}))
            continue
        if source == "jira" and labels and any(lbl in labels for lbl in [x.lower() for x in v.get("jira_labels", [])]):
            candidates.append((vslug, vname, 0.9, {"rule": "jira_label", "matched": list(labels.intersection({x.lower() for x in v.get("jira_labels", [])}))}))
        if source == "zendesk" and labels and any(tag in labels for tag in [x.lower() for x in v.get("zendesk_tags", [])]):
            candidates.append((vslug, vname, 0.9, {"rule": "zendesk_tag", "matched": list(labels.intersection({x.lower() for x in v.get("zendesk_tags", [])}))}))

    if not candidates:
        return None, None, 0.0, {"reason": "no_rule_match"}

    horizontal = {"api-docs", "client-portal", "data-reporting"}
    candidates.sort(key=lambda x: (x[2], 0 if x[0] in horizontal else 1))
    best = candidates[-1]
    return best[0], best[1], best[2], best[3]


def classify_product_vertical(source: str, title: str, content: str, labels_csv: str = "", project: str = "") -> Tuple[str | None, str | None, float, Dict]:
    """
    Rules-first keyword classifier. Returns (slug, name, confidence, explanation).
    Confidence is heuristic: number of keyword hits normalized; refined later.
    """
    text = f"{title} \n {content} \n {labels_csv} \n {project} \n {source}"
    text_lc = text.lower()
    labels = {p.strip().lower() for p in (labels_csv or "").split(",") if p.strip()}
    project_key = (project or "").strip().upper()

    kw_counts: Dict[str, int] = {}
    hits: Dict[str, List[str]] = {}

    # 1) High-precision structured rules first
    r_slug, r_name, r_conf, r_exp = rule_based_vertical(source, labels_csv=labels_csv, project=project)
    if r_slug:
        return r_slug, r_name, r_conf, r_exp

    # 2) Keywords + Embedding similarity ensemble
    # Keyword counts per vertical
    for v in VERTICALS:
        vslug = v["slug"]
        klist = v.get("keywords", [])
        count = 0
        matched: List[str] = []
        for kw in klist:
            if kw and kw.lower() in text_lc:
                count += 1
                matched.append(kw)
        if count:
            kw_counts[vslug] = count
            hits[vslug] = matched

    # Embedding similarity to prototypes
    _ensure_prototypes()
    vec = embed_texts([text])[0]  # normalized
    sims = (vec @ _PROTO_VECS.T).tolist()  # cosine similarity

    # Combine scores per vertical: w_sim * sim + w_kw * kw_norm
    w_sim, w_kw = 0.65, 0.35
    combined: Dict[str, float] = {}
    sim_map: Dict[str, float] = {}
    for slug, sim in zip(_PROTO_SLUGS or [], sims):
        # normalize keyword count to [0,1] capped at 3
        kw_norm = min(kw_counts.get(slug, 0), 3) / 3.0
        combined[slug] = w_sim * float(sim) + w_kw * kw_norm
        sim_map[slug] = float(sim)

    if not combined:
        return None, None, 0.0, {"reason": "no_signal"}

    horizontal = {"api-docs", "client-portal", "data-reporting"}
    best_slug = max(combined.keys(), key=lambda s: (combined[s], 0 if s in horizontal else 1))
    best_name = next(v["name"] for v in VERTICALS if v["slug"] == best_slug)

    # Confidence from combined score with mild scaling; clamp [0.5, 0.95]
    raw = combined[best_slug]
    conf = max(0.5, min(0.95, 0.55 + 0.4 * raw))

    # Top-3 embed sims for explanation
    top_idx = np.argsort(np.array(sims))[-3:][::-1]
    embed_top = []
    for idx in top_idx:
        slug = (_PROTO_SLUGS or [])[int(idx)]
        embed_top.append({"slug": slug, "sim": round(sim_map[slug], 4)})

    return best_slug, best_name, conf, {
        "matched_keywords": hits.get(best_slug, []),
        "kw_counts": kw_counts,
        "embed_top": embed_top,
        "combined": {best_slug: combined[best_slug]},
    }
