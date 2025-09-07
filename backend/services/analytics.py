from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select, or_, and_

from db import SessionLocal, Ticket


def zendesk_label_frequencies(
    days: int = 90,
    include_internal: bool = False,
    min_count: int = 1,
    top: Optional[int] = None,
) -> Dict:
    """
    Compute frequency of Zendesk labels (tags) over the last N days.
    - include_internal: when False, excludes tickets where is_internal=True
    - min_count: filter out rare labels below this count
    - top: return only top-N labels after filtering (None for all)
    """
    since = datetime.utcnow() - timedelta(days=max(1, days))
    c = Counter()
    total_tickets = 0

    with SessionLocal() as session:
        base = [Ticket.source == "zendesk", or_(Ticket.source_updated_at == None, Ticket.source_updated_at >= since)]
        if not include_internal:
            base.append(or_(Ticket.is_internal == None, Ticket.is_internal == False))
        stmt = select(Ticket).where(and_(*base))
        rows: List[Ticket] = session.execute(stmt).scalars().all()
        total_tickets = len(rows)
        for t in rows:
            labels_csv = t.labels or ""
            if not labels_csv:
                continue
            for raw in labels_csv.split(","):
                lab = raw.strip().lower()
                if not lab:
                    continue
                c[lab] += 1

    # Apply min_count filter and sort desc
    items = [(lab, cnt) for lab, cnt in c.items() if cnt >= max(1, min_count)]
    items.sort(key=lambda x: (-x[1], x[0]))
    if top and top > 0:
        items = items[:top]

    return {
        "total_tickets": total_tickets,
        "unique_labels": len(c),
        "items": [{"label": lab, "count": cnt} for lab, cnt in items],
    }

