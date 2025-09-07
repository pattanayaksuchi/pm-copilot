import csv
import io
import random
from datetime import datetime, timedelta
from typing import List, Tuple

from db import SessionLocal, Ticket, upsert_gold_label, upsert_ticket_vertical
from nlp.product_verticals import classify_product_vertical
from nlp.product_verticals import VERTICALS


def _parse_bins(bins_param: str | None) -> List[Tuple[float, float]]:
    default = [(0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    if not bins_param:
        return default
    out = []
    for part in bins_param.split(","):
        try:
            lo_s, hi_s = part.split("-")
            lo, hi = float(lo_s), float(hi_s)
            out.append((lo, hi))
        except Exception:
            continue
    return out or default


def _sample_rows(days: int, per_bin: int, bins_list: list[tuple[float, float]]):
    cutoff = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as session:
        tickets = (
            session.query(Ticket)
            .filter((Ticket.source_updated_at == None) | (Ticket.source_updated_at >= cutoff))
            .all()
        )
    rows = []
    for t in tickets:
        v_slug, v_name, v_conf, _ = classify_product_vertical(
            t.source or "", t.title or "", t.content or "", t.labels or "", t.project or ""
        )
        rows.append({
            "ticket_id": t.id,
            "source": t.source,
            "external_id": t.external_id,
            "url": t.url,
            "title": (t.title or "").replace("\n", " ").strip(),
            "pred_vertical_slug": v_slug or "",
            "pred_vertical_name": v_name or "",
            "confidence": round(float(v_conf or 0.0), 4),
        })
    sampled = []
    for (lo, hi) in bins_list:
        bucket = [r for r in rows if (r["confidence"] >= lo and r["confidence"] < hi)]
        random.shuffle(bucket)
        sampled.extend(bucket[: per_bin])
    return sampled


def generate_review_sample_csv(days: int = 30, per_bin: int = 50, bins: str | None = None) -> str:
    bins_list = _parse_bins(bins)
    sampled = _sample_rows(days, per_bin, bins_list)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ticket_id","source","external_id","url","title",
        "pred_vertical_slug","pred_vertical_name","confidence",
        "gold_vertical_slug","gold_vertical_name",
    ])
    for r in sampled:
        writer.writerow([
            r["ticket_id"], r["source"], r["external_id"], r["url"], r["title"],
            r["pred_vertical_slug"], r["pred_vertical_name"], r["confidence"],
            "", "",
        ])
    return output.getvalue()


def generate_review_sample_json(days: int = 30, per_bin: int = 50, bins: str | None = None) -> list[dict]:
    bins_list = _parse_bins(bins)
    return _sample_rows(days, per_bin, bins_list)


def submit_labels(items: list[dict], reviewer: str = "") -> dict:
    # Accepts list of {ticket_id, vertical_slug?|vertical_name?, note?}
    idx_by_slug = {v["slug"].lower(): v for v in VERTICALS}
    idx_by_name = {v["name"].lower(): v for v in VERTICALS}
    updated = 0
    with SessionLocal() as session:
        for it in items:
            tid = int(it.get("ticket_id"))
            slug = (it.get("vertical_slug") or "").strip().lower()
            name = (it.get("vertical_name") or "").strip().lower()
            note = (it.get("note") or "").strip()
            v = idx_by_slug.get(slug) or idx_by_name.get(name)
            if not v:
                continue
            # Save gold label
            upsert_gold_label(session, ticket_id=tid, vertical_slug=v["slug"], vertical_name=v["name"], reviewer=reviewer, note=note)
            # Persist as manual override into product vertical table with conf=1.0
            upsert_ticket_vertical(session, ticket_id=tid, vertical_slug=v["slug"], vertical_name=v["name"], confidence=1.0, explanation={"source": "manual"})
            updated += 1
        session.commit()
    return {"updated": updated}
