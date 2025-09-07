import numpy as np
from typing import List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session
from nlp.preprocess import clean_text
from nlp.embeddings import embed_texts
from nlp.cluster import kmeans_clusters, top_terms_for_cluster
from nlp.classify import classify_ticket
from nlp.product_verticals import classify_product_vertical
from typing import Optional


from db import SessionLocal, Ticket, TicketEmbedding, Theme, TicketProductVertical, upsert_ticket_vertical

import uuid

def _tickets_since_days(session: Session, days: int = 30, include_internal: bool = False) -> List[Ticket]:
    since = datetime.utcnow() - timedelta(days=days)
    base = or_(Ticket.source_updated_at == None, Ticket.source_updated_at >= since)
    if include_internal:
        stmt = select(Ticket).where(base)
    else:
        # exclude internal by default: is_internal is NULL or False
        stmt = select(Ticket).where(and_(base, or_(Ticket.is_internal == None, Ticket.is_internal == False)))
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

def _classify_and_count(session: Session, tickets: List[Ticket]) -> Dict[str, int]:
    counts = {"issue":0, "feature_request":0, "unknown":0}
    for t in tickets:
        # Type classification (existing MVP)
        t.type = classify_ticket(t.source, t.title or "", t.content or "", t.labels or "", t.status or "")
        counts[t.type] = counts.get(t.type, 0) + 1

        # Product vertical classification (new)
        v_slug, v_name, v_conf, v_exp = classify_product_vertical(
            t.source or "",
            t.title or "",
            t.content or "",
            t.labels or "",
            t.project or "",
        )
        if v_slug and v_conf >= 0.80:
            upsert_ticket_vertical(session, ticket_id=t.id, vertical_slug=v_slug, vertical_name=v_name, confidence=v_conf, explanation=v_exp)
    return counts

def build_themes(days: int = 30, k: int = 12, include_internal: bool = False) -> Dict[str, Any]:
    with SessionLocal() as session:
        tickets = _tickets_since_days(session, days=days, include_internal=include_internal)
        if not tickets:
            return {"run_id": None, "themes": [], "top_issues": [], "top_features": []}

        # (1) classify/update types
        _ = _classify_and_count(session, tickets)
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
        # Prefetch product verticals for tickets to include in response
        pv_map = {}
        for t in ordered:
            tv = session.query(TicketProductVertical).filter_by(ticket_id=t.id).one_or_none()
            if tv:
                pv_map[t.id] = {"vertical": tv.vertical_name, "slug": tv.vertical_slug, "confidence": tv.confidence}

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
                "tickets": [{
                    "id": t.id,
                    "title": t.title,
                    "source": t.source,
                    "url": t.url,
                    "type": t.type,
                    "product_vertical": (pv_map.get(t.id) or {}).get("vertical"),
                    "product_vertical_slug": (pv_map.get(t.id) or {}).get("slug"),
                    "product_vertical_confidence": (pv_map.get(t.id) or {}).get("confidence"),
                } for t in data["tickets"]]
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

def build_themes_filtered(days: int = 30, k: int = 12, source: Optional[str] = None, kind: Optional[str] = None, vertical: Optional[str] = None, include_internal: bool = False):
    """Convenience wrapper: build themes then filter tickets in each theme."""
    data = build_themes(days=days, k=k, include_internal=include_internal)
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
            if vertical and vertical.lower() != "all":
                vslug = (t.get("product_vertical_slug") or "").lower()
                vname = (t.get("product_vertical") or "").lower()
                if not (vertical.lower() == vslug or vertical.lower() == vname):
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


def suggest_themes(days: int = 30, k: int = 12, top_n: int = 5, include_internal: bool = False) -> Dict[str, Any]:
    """
    Produce theme suggestions for PMs with a simple priority score.

    Score formula (0..1):
      0.6 * normalized_size + 0.3 * recency_ratio_7d + 0.1 * high_priority_ratio

    Returns a dict with run_id and a sorted list of suggestions.
    """
    # Build base themes first
    data = build_themes(days=days, k=k, include_internal=include_internal)
    themes = data.get("themes", [])
    if not themes:
        return {"run_id": data.get("run_id"), "suggestions": []}

    # Compute max size for normalization
    max_size = max((th.get("size", 0) for th in themes), default=1) or 1

    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    suggestions = []
    with SessionLocal() as session:
        for th in themes:
            t_ids = [t.get("id") for t in th.get("tickets", []) if t.get("id") is not None]
            if not t_ids:
                continue
            # Pull extra fields needed for scoring
            q = session.query(Ticket).filter(Ticket.id.in_(t_ids))
            rows: List[Ticket] = q.all()

            size = int(th.get("size", len(rows)))
            recent_7d = sum(1 for r in rows if (r.source_updated_at or r.created_at or now) >= week_ago)
            high_priority = 0
            for r in rows:
                pr = (r.priority or "").lower()
                if any(p in pr for p in ["p0", "p1", "blocker", "critical", "high"]):
                    high_priority += 1

            # Simple majority vertical for context
            vnames = [
                (tht.get("product_vertical") or "").strip().lower()
                for tht in th.get("tickets", [])
                if (tht.get("product_vertical") or "").strip()
            ]
            top_vertical = ""
            if vnames:
                from collections import Counter
                top_vertical = Counter(vnames).most_common(1)[0][0]

            # Ratios and score
            normalized_size = size / max_size
            recency_ratio = (recent_7d / size) if size else 0.0
            high_priority_ratio = (high_priority / size) if size else 0.0
            score = 0.6 * normalized_size + 0.3 * recency_ratio + 0.1 * high_priority_ratio

            # Suggested action
            typ = th.get("type", "mixed")
            hint = th.get("hint", "")
            if typ == "issue":
                action = f"Prioritize a bugfix sprint for: {hint}"
            elif typ == "feature_request":
                action = f"Scope an epic and RFC for: {hint}"
            else:
                action = f"Triage and split theme into fixes and features: {hint}"

            # Rationale blurb
            rationale = (
                f"{size} tickets; {recent_7d} updated in last 7d; "
                f"{high_priority} high-priority"
            )

            # Surface a couple of example tickets
            samples = []
            for t in th.get("tickets", [])[:2]:
                samples.append({"title": t.get("title", ""), "url": t.get("url", "")})

            suggestions.append({
                "label": th.get("label"),
                "type": typ,
                "hint": hint,
                "size": size,
                "score": round(float(score), 4),
                "recent_7d": recent_7d,
                "high_priority": high_priority,
                "top_vertical": top_vertical or None,
                "suggested_action": action,
                "rationale": rationale,
                "samples": samples,
            })

    # Sort and trim
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    if top_n and top_n > 0:
        suggestions = suggestions[: top_n]

    return {"run_id": data.get("run_id"), "suggestions": suggestions}
