from typing import Dict, List, Optional, Tuple
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import SessionLocal, Ticket
from connectors.zendesk import _fetch_users_by_ids  # reuse helper


def _domain(email: str) -> str:
    if not email:
        return ""
    try:
        return email.split("@", 1)[1].lower()
    except Exception:
        return ""


def audit_zendesk_internal(days: int = 30, limit: int = 500) -> Dict:
    """Compute simple accuracy audit for Ticket.is_internal on Zendesk tickets.

    Compares stored `is_internal` vs. a fresh classification using requester role/email domain
    (submitter/sharing omitted unless later persisted). Returns counts and samples.
    """
    now = datetime.utcnow()
    since = now - timedelta(days=max(1, days))
    with SessionLocal() as session:
        stmt = (
            select(Ticket)
            .where(Ticket.source == "zendesk")
            .where((Ticket.source_updated_at == None) | (Ticket.source_updated_at >= since))
            .limit(max(50, limit))
        )
        rows: List[Ticket] = session.execute(stmt).scalars().all()
        if not rows:
            return {"total": 0, "matches": 0, "mismatches": 0, "samples": []}

        # Fetch requester and submitter users for role/email
        req_ids = [str(r.requester or "") for r in rows if (r.requester or "")]
        sub_ids = [str(r.submitter or "") for r in rows if (r.submitter or "")]
        users = {}
        try:
            users = _fetch_users_by_ids(sorted(set([*req_ids, *sub_ids])))
        except Exception:
            users = {}

        # Domains to treat as internal (defaults enforced in connector env)
        from connectors.zendesk import INTERNAL_EMAIL_DOMAINS

        def classify_external(req_id: str, sub_id: str, sharing_type: Optional[str]) -> Tuple[bool, str]:
            def _is_external(uid: str) -> bool:
                u = users.get(str(uid) or "") or {}
                role = (u.get("role") or "").lower()
                email = (u.get("email") or "").lower()
                dom = _domain(email)
                return role == "end-user" and (dom and dom not in INTERNAL_EMAIL_DOMAINS) and (sharing_type != "inbound")

            if _is_external(sub_id):
                return True, "submitter_enduser_external_domain"
            if _is_external(req_id):
                return True, "requester_enduser_external_domain"
            return False, "default_internal"

        samples = []
        matches = 0
        mismatches = 0
        by_reason = Counter()
        for t in rows:
            is_external, reason = classify_external(t.requester or "", t.submitter or "", (t.sharing_type or None))
            predicted_internal = not is_external
            stored = t.is_internal if t.is_internal is not None else False  # default to False (external) if unknown
            if bool(stored) == bool(predicted_internal):
                matches += 1
            else:
                mismatches += 1
            by_reason[reason] += 1
            if len(samples) < 50:  # cap sample payload
                samples.append({
                    "ticket_id": t.id,
                    "external_id": t.external_id,
                    "title": t.title,
                    "url": t.url,
                    "stored_is_internal": stored,
                    "predicted_is_internal": predicted_internal,
                    "requester_id": t.requester,
                    "requester_role": (users.get(str(t.requester) or "") or {}).get("role"),
                    "requester_email": (users.get(str(t.requester) or "") or {}).get("email"),
                    "submitter_role": (users.get(str(t.submitter) or "") or {}).get("role"),
                    "submitter_email": (users.get(str(t.submitter) or "") or {}).get("email"),
                    "requester_domain": _domain((users.get(str(t.requester) or "") or {}).get("email") or ""),
                    "submitter_domain": _domain((users.get(str(t.submitter) or "") or {}).get("email") or ""),
                    "sharing_type": (t.sharing_type or None),
                    "reason": reason,
                    "labels": t.labels,
                })

        return {
            "total": len(rows),
            "matches": matches,
            "mismatches": mismatches,
            "accuracy": round(matches / max(1, len(rows)), 4),
            "by_reason": dict(by_reason),
            "samples": samples,
        }


def audit_zendesk_internal_csv(days: int = 30, limit: int = 1000) -> str:
    """Return a CSV (string) of mismatches with key fields for manual review."""
    import csv
    from io import StringIO

    res = audit_zendesk_internal(days=days, limit=limit)
    out = StringIO()
    w = csv.writer(out)
    w.writerow([
        "ticket_id","external_id","url",
        "stored_is_internal","predicted_is_internal",
        "requester_id","requester_role","requester_email","requester_domain",
        "submitter_role","submitter_email","submitter_domain",
        "sharing_type","reason","labels"
    ])
    for s in res.get("samples", []):
        if s.get("stored_is_internal") == s.get("predicted_is_internal"):
            continue
        w.writerow([
            s.get("ticket_id"), s.get("external_id"), s.get("url"),
            s.get("stored_is_internal"), s.get("predicted_is_internal"),
            s.get("requester_id"), s.get("requester_role"), s.get("requester_email"), s.get("requester_domain"),
            s.get("submitter_role"), s.get("submitter_email"), s.get("submitter_domain"),
            s.get("sharing_type"), s.get("reason"), s.get("labels"),
        ])
    return out.getvalue()
