from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from db import SessionLocal, Ticket, upsert_ticket_vertical
from nlp.product_verticals import classify_product_vertical


def backfill_verticals(days: Optional[int] = None) -> dict:
    """Classify and persist product vertical for tickets. If days is provided, only include tickets updated in last N days; otherwise all tickets."""
    with SessionLocal() as session:
        q = session.query(Ticket)
        if days is not None:
            since = datetime.utcnow() - timedelta(days=days)
            q = q.filter((Ticket.source_updated_at == None) | (Ticket.source_updated_at >= since))
        tickets = q.all()

        updated = 0
        for t in tickets:
            v_slug, v_name, v_conf, v_exp = classify_product_vertical(
                t.source or "",
                t.title or "",
                t.content or "",
                t.labels or "",
                t.project or "",
            )
            if v_slug and v_conf >= 0.80:
                upsert_ticket_vertical(session, ticket_id=t.id, vertical_slug=v_slug, vertical_name=v_name, confidence=v_conf, explanation=v_exp)
                updated += 1
        session.commit()
        return {"scanned": len(tickets), "labeled": updated}
