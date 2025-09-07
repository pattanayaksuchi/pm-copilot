import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session

from db import SessionLocal, Ticket, TicketEmbedding, TicketProductVertical
from nlp.preprocess import clean_text
from nlp.embeddings import embed_texts


def _tickets_since_days(session: Session, days: int = 30, include_internal: bool = False) -> List[Ticket]:
    since = datetime.utcnow() - timedelta(days=days)
    base = or_(Ticket.source_updated_at == None, Ticket.source_updated_at >= since)
    if include_internal:
        stmt = select(Ticket).where(base)
    else:
        stmt = select(Ticket).where(and_(base, or_(Ticket.is_internal == None, Ticket.is_internal == False)))
    return session.execute(stmt).scalars().all()


def _ensure_embeddings(session: Session, tickets: List[Ticket]) -> None:
    need_texts, need_ids = [], []
    for t in tickets:
        emb = session.query(TicketEmbedding).filter_by(ticket_id=t.id).one_or_none()
        if not emb:
            text = clean_text(f"{t.title}. {t.content}")
            need_texts.append(text)
            need_ids.append(t.id)
    if need_texts:
        vecs = embed_texts(need_texts)
        for tid, vec in zip(need_ids, vecs):
            te = TicketEmbedding(ticket_id=tid, vector=vec.tolist(), dim=int(vec.shape[0]))
            session.add(te)
        session.commit()


def _fetch_vectors(session: Session, tickets: List[Ticket]):
    vectors = []
    ordered = []
    for t in tickets:
        te = session.query(TicketEmbedding).filter_by(ticket_id=t.id).one_or_none()
        if te:
            vectors.append(np.asarray(te.vector, dtype="float32"))
            ordered.append(t)
    if not vectors:
        return np.zeros((0, 384), dtype="float32"), []
    return np.vstack(vectors), ordered


def _apply_filters(
    tickets: List[Ticket],
    source: Optional[str] = None,
    kind: Optional[str] = None,
    vertical: Optional[str] = None,
) -> List[Ticket]:
    out = tickets
    if source and source.lower() != "all":
        out = [t for t in out if (t.source or "").lower() == source.lower()]
    if kind and kind.lower() in ("issue", "feature_request", "unknown"):
        out = [t for t in out if (t.type or "unknown").lower() == kind.lower()]
    if vertical and vertical.lower() != "all":
        # Join with TicketProductVertical to match either slug or name
        ids = [t.id for t in out]
        by_id = {t.id: t for t in out}
        with SessionLocal() as s2:
            rows = (
                s2.query(TicketProductVertical)
                .filter(TicketProductVertical.ticket_id.in_(ids))
                .all()
            )
        filt = []
        for r in rows:
            vslug = (r.vertical_slug or "").lower()
            vname = (r.vertical_name or "").lower()
            if vertical.lower() == vslug or vertical.lower() == vname:
                t = by_id.get(r.ticket_id)
                if t is not None:
                    filt.append(t)
        out = filt
    return out


def answer_question(
    question: str,
    days: int = 30,
    top_k: int = 5,
    source: Optional[str] = None,
    kind: Optional[str] = None,
    vertical: Optional[str] = None,
    include_internal: bool = False,
) -> Dict[str, Any]:
    """
    Very simple semantic search over tickets using sentence embeddings.
    Returns an "answer" string plus the top matching tickets.
    """
    q = (question or "").strip()
    if not q:
        return {"answer": "Please provide a question.", "results": []}

    with SessionLocal() as session:
        tickets = _tickets_since_days(session, days=days, include_internal=include_internal)
        if not tickets:
            return {"answer": "No tickets available to search.", "results": []}

        # Ensure we have up-to-date embeddings
        _ensure_embeddings(session, tickets)

        # Optionally apply filters by source/type/vertical
        tickets = _apply_filters(tickets, source=source, kind=kind, vertical=vertical)
        if not tickets:
            return {"answer": "No tickets matched the selected filters.", "results": []}

        # Fetch vectors and compute similarities
        matrix, ordered = _fetch_vectors(session, tickets)
        if matrix.shape[0] == 0:
            return {"answer": "No embeddings available to search.", "results": []}

        qvec = embed_texts([clean_text(q)])[0]
        # embeddings are normalized; dot = cosine similarity
        sims = matrix @ qvec.astype("float32")
        idx = np.argsort(-sims)[: max(1, top_k)]

        results = []
        for i in idx:
            t = ordered[int(i)]
            results.append({
                "id": t.id,
                "title": t.title,
                "source": t.source,
                "url": t.url,
                "similarity": float(sims[int(i)]),
                "type": t.type or "unknown",
            })

        # Compose a lightweight natural answer
        if results:
            titles = "; ".join([r.get("title") or r.get("url") or "(untitled)" for r in results])
            answer = (
                f"I found {len(results)} relevant items. Top matches: {titles}. "
                f"Use the links for details."
            )
        else:
            answer = "I didn’t find relevant tickets. Try rephrasing or widening filters."

        return {"answer": answer, "results": results}
