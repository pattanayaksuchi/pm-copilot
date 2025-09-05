import numpy as np
from typing import List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from nlp.preprocess import clean_text
from nlp.embeddings import embed_texts
from nlp.cluster import kmeans_clusters, top_terms_for_cluster
from nlp.classify import classify_ticket
from typing import Optional


from db import SessionLocal, Ticket, TicketEmbedding, Theme

import uuid

def _tickets_since_days(session: Session, days: int = 30) -> List[Ticket]:
    since = datetime.utcnow() - timedelta(days=days)
    stmt = select(Ticket).where(
        or_(Ticket.source_updated_at == None, Ticket.source_updated_at >= since)
    )
    return session.execute(stmt).scalars().all()

def _ensure_embeddings(session: Session, tickets: List[Ticket]) -> np.ndarray:
    need_texts, need_ids = [], []
    for t in tickets:
        emb = session.query(TicketEmbedding).filter_by(ticket_id=t.id).one_or_none()
        if not emb:
            text = clean_text(f"{t.title}. {t.content}")
            need_texts.append(text)
            need_ids.append(t.id)
    # create new embeddings
    if need_texts:
        vecs = embed_texts(need_texts)
        for tid, vec in zip(need_ids, vecs):
            te = TicketEmbedding(ticket_id=tid, vector=vec.tolist(), dim=vec.shape[0])
            session.add(te)
        session.commit()
    # fetch all in order
    vectors = []
    ordered = []
    for t in tickets:
        te = session.query(TicketEmbedding).filter_by(ticket_id=t.id).one_or_none()
        if te:
            vectors.append(np.asarray(te.vector, dtype="float32"))
            ordered.append(t)
    return np.vstack(vectors) if vectors else np.zeros((0,384), dtype="float32"), ordered

def _classify_and_count(tickets: List[Ticket]) -> Dict[str, int]:
    counts = {"issue":0, "feature_request":0, "unknown":0}
    for t in tickets:
        t.type = classify_ticket(t.source, t.title or "", t.content or "", t.labels or "", t.status or "")
        counts[t.type] = counts.get(t.type, 0) + 1
    return counts

def build_themes(days: int = 30, k: int = 12) -> Dict[str, Any]:
    with SessionLocal() as session:
        tickets = _tickets_since_days(session, days=days)
        if not tickets:
            return {"run_id": None, "themes": [], "top_issues": [], "top_features": []}

        # (1) classify/update types
        _ = _classify_and_count(tickets)
        session.commit()

        # (2) ensure embeddings
        vectors, ordered = _ensure_embeddings(session, tickets)
        texts = [clean_text(f"{t.title}. {t.content}") for t in ordered]

        # (3) cluster
        labels, _centroids = kmeans_clusters(vectors, k=k)
        if labels.size == 0:
            return {"run_id": None, "themes": [], "top_issues": [], "top_features": []}
        hints = top_terms_for_cluster(texts, labels)

        # (4) materialize themes (optional) and compute scores
        run_id = uuid.uuid4().hex[:12]
        theme_buckets = {}
        for t, lab in zip(ordered, labels):
            theme_buckets.setdefault(int(lab), {"tickets": [], "issue":0, "feature_request":0})
            theme_buckets[int(lab)]["tickets"].append(t)
            theme_buckets[int(lab)][t.type] = theme_buckets[int(lab)].get(t.type, 0) + 1

        out_themes = []
        for lab, data in theme_buckets.items():
            size = len(data["tickets"])
            # decide theme type by majority
            maj_type = "issue" if data.get("issue",0) >= data.get("feature_request",0) else "feature_request"
            # persist a Theme row (not mandatory, but nice for future)
            th = Theme(run_id=run_id, label=lab, centroid_hint=hints.get(lab, ""), type=maj_type, size=size)
            session.add(th)
            out_themes.append({
                "label": lab,
                "hint": hints.get(lab, ""),
                "type": maj_type,
                "size": size,
                "tickets": [{"id": t.id, "title": t.title, "source": t.source, "url": t.url, "type": t.type} for t in data["tickets"]]
            })
        session.commit()

        # (5) rank & extract top-10 lists
        # Simple score = frequency (size). You can add recency weighting later.
        out_themes.sort(key=lambda x: x["size"], reverse=True)

        def pick_top(kind: str):
            flat = []
            for th in out_themes:
                # include tickets of the requested type from each theme
                for t in th["tickets"]:
                    if t["type"] == kind:
                        flat.append(t)
            # aggregate by (title snippet) to avoid near-duplicates (very simple)
            # But for MVP: just take first 10
            return flat[:10]

        top_issues = pick_top("issue")
        top_features = pick_top("feature_request")

        return {
            "run_id": run_id,
            "themes": out_themes,
            "top_issues": top_issues,
            "top_features": top_features
        }
    
def _filter_tickets(tickets: List[Ticket], source: Optional[str]=None, type: Optional[str]=None) -> List[Ticket]:
    out = tickets
    if source and source.lower() != "all":
        out = [t for t in out if (t.source or "").lower() == source.lower()]
    if kind and kind.lower() in ["issue", "feature_request", "unknown"]:
        out = [t for t in out if (t.type or "unknown").lower() == kind.lower()]
    return out

def build_themes_filtered(days: int = 30, k: int = 12, source: Optional[str] = None, kind: Optional[str] = None):
    """Convenience wrapper: build themes then filter tickets in each theme."""
    data = build_themes(days=days, k=k)
    if not data["themes"]:
        return data
    # Filter tickets inside themes
    new_themes = []
    for th in data["themes"]:
        filt = []
        for t in th["tickets"]:
            if source and source.lower() != "all" and (t["source"] or "").lower() != source.lower():
                continue
            if kind and kind.lower() in ("issue","feature_request","unknown") and (t["type"] or "unknown").lower() != kind.lower():
                continue
            filt.append(t)
        if filt:
            th2 = {**th, "tickets": filt, "size": len(filt)}
            new_themes.append(th2)
    data["themes"] = sorted(new_themes, key=lambda x: x["size"], reverse=True)
    # Recompute top10 based on filtered tickets
    def _pick_top(knd: str):
        flat = []
        for th in data["themes"]:
            for t in th["tickets"]:
                if (t["type"] or "unknown") == knd:
                    flat.append(t)
        return flat[:10]
    data["top_issues"] = _pick_top("issue")
    data["top_features"] = _pick_top("feature_request")
    return data
