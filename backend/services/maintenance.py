from typing import Optional, List, Dict
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import SessionLocal, Ticket
from connectors.zendesk import annotate_is_internal


def backfill_zendesk_internal_flags(days: Optional[int] = None) -> Dict[str, int]:
    """Backfill Ticket.is_internal for Zendesk tickets using current rules.

    days: limit to last N days for speed; None means all.
    Returns counts of updated tickets.
    """
    updated, total = 0, 0
    with SessionLocal() as session:
        stmt = select(Ticket).where(Ticket.source == "zendesk")
        if isinstance(days, int) and days > 0:
            since = datetime.utcnow() - timedelta(days=days)
            stmt = stmt.where((Ticket.source_updated_at == None) | (Ticket.source_updated_at >= since))
        tickets: List[Ticket] = session.execute(stmt).scalars().all()
        total = len(tickets)
        if not tickets:
            return {"total": 0, "updated": 0}

        # Prepare minimal dicts for annotation
        items = [
            {
                "requester": t.requester,
                "submitter": t.submitter,
                "labels": t.labels,
                "via": {},
                "sharing_agreement_ids": [],
            }
            for t in tickets
        ]
        items = annotate_is_internal(items)

        for t, it in zip(tickets, items):
            new_val = it.get("is_internal", None)
            if new_val is not None and new_val != t.is_internal:
                t.is_internal = bool(new_val)
                updated += 1
            # Also update requester/submitter fields if present
            if it.get("requester_role") or it.get("requester_email"):
                t.requester_role = it.get("requester_role") or t.requester_role
                t.requester_email = it.get("requester_email") or t.requester_email
            if it.get("submitter_role") or it.get("submitter_email"):
                t.submitter_role = it.get("submitter_role") or t.submitter_role
                t.submitter_email = it.get("submitter_email") or t.submitter_email
            # Sharing flags
            if it.get("is_shared") is not None:
                t.is_shared = bool(it.get("is_shared"))
            if it.get("sharing_type"):
                t.sharing_type = it.get("sharing_type") or t.sharing_type
        session.commit()
    return {"total": total, "updated": updated}
