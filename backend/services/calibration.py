from collections import Counter
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from db import SessionLocal, Ticket
from nlp.product_verticals import classify_product_vertical, rule_based_vertical


def _iter_labeled_examples(session: Session, sources: List[str], days: Optional[int] = None):
    q = session.query(Ticket).filter(Ticket.source.in_(sources))
    if days is not None and days > 0:
        from datetime import datetime, timedelta
        since = datetime.utcnow() - timedelta(days=days)
        q = q.filter((Ticket.source_updated_at == None) | (Ticket.source_updated_at >= since))
    for t in q.all():
        # Ground truth from structured rules only
        gt_slug, gt_name, gt_conf, _ = rule_based_vertical(
            t.source or "", labels_csv=t.labels or "", project=t.project or ""
        )
        if gt_slug:
            yield t, gt_slug, gt_name


def calibrate_precision_coverage(days: Optional[int] = 30, sources: Optional[List[str]] = None) -> Dict:
    sources = sources or ["jira", "zendesk"]
    thresholds = [round(x, 2) for x in [0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90,0.95]]

    with SessionLocal() as session:
        dataset = list(_iter_labeled_examples(session, sources, days))
        total = len(dataset)
        if total == 0:
            return {"total_labeled": 0, "by_threshold": [], "label_dist": {}, "note": "No rule-labeled examples found. Add jira_labels/zendesk_tags in product_verticals.py or ensure labels/tags exist in the data."}

        # Precompute predictions and confidences
        preds = []
        for (t, gt_slug, gt_name) in dataset:
            p_slug, p_name, p_conf, _ = classify_product_vertical(
                t.source or "", t.title or "", t.content or "", t.labels or "", t.project or ""
            )
            preds.append({
                "gt_slug": gt_slug,
                "pred_slug": p_slug,
                "conf": p_conf,
                "ticket_id": t.id,
                "source": t.source,
            })

        out = []
        for th in thresholds:
            assigned = [r for r in preds if (r["pred_slug"] and r["conf"] >= th)]
            n_assigned = len(assigned)
            correct = sum(1 for r in assigned if r["pred_slug"] == r["gt_slug"])
            precision = (correct / n_assigned) if n_assigned else None
            coverage = n_assigned / total if total else 0.0
            out.append({
                "threshold": th,
                "precision": precision,
                "coverage": coverage,
                "n_assigned": n_assigned,
                "correct_assigned": correct,
                "total_labeled": total,
            })

        label_dist = Counter([gt for (_, gt, _) in [(t, gt_slug, gt_name) for (t, gt_slug, gt_name) in dataset]])
        return {
            "total_labeled": total,
            "by_threshold": out,
            "label_dist": dict(label_dist),
            "sources": sources,
            "days": days,
        }


def calibrate_by_vertical(days: Optional[int] = 30, sources: Optional[List[str]] = None, threshold: float = 0.8) -> Dict:
    sources = sources or ["jira", "zendesk"]
    with SessionLocal() as session:
        dataset = list(_iter_labeled_examples(session, sources, days))
        total = len(dataset)
        if total == 0:
            return {"total_labeled": 0, "by_vertical": {}, "note": "No rule-labeled examples found."}

        # Predictions
        per_vert = {}
        for (t, gt_slug, gt_name) in dataset:
            p_slug, p_name, p_conf, _ = classify_product_vertical(
                t.source or "", t.title or "", t.content or "", t.labels or "", t.project or ""
            )
            # ensure keys
            if gt_slug not in per_vert:
                per_vert[gt_slug] = {
                    "label": gt_slug,
                    "gt_count": 0,
                    "assigned_count": 0,
                    "correct_assigned": 0,
                }
            per_vert[gt_slug]["gt_count"] += 1

            if p_slug and p_conf is not None and p_conf >= threshold:
                # count assigned for the predicted label as well (in case it differs)
                if p_slug not in per_vert:
                    per_vert[p_slug] = {
                        "label": p_slug,
                        "gt_count": 0,
                        "assigned_count": 0,
                        "correct_assigned": 0,
                    }
                per_vert[p_slug]["assigned_count"] += 1
                if p_slug == gt_slug:
                    per_vert[p_slug]["correct_assigned"] += 1

        # compute metrics
        for v in per_vert.values():
            a = v["assigned_count"]
            c = v["correct_assigned"]
            g = v["gt_count"]
            v["precision"] = (c / a) if a else None
            v["recall_on_labeled"] = (c / g) if g else None

        return {
            "total_labeled": total,
            "threshold": threshold,
            "by_vertical": per_vert,
            "sources": sources,
            "days": days,
        }
