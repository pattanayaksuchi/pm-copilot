from datetime import datetime, timedelta
import os
from sqlalchemy.exc import SQLAlchemyError

from db import SessionLocal, upsert_ticket, get_or_create_sync_state
from connectors import zendesk as zc
from connectors import jira as jc
from connectors import slack as sc

HISTORY_DAYS = int(os.getenv("SYNC_HISTORY_DAYS", "30"))
ENABLE_ZENDESK = os.getenv("ENABLE_ZENDESK", "1") not in ("0", "false", "False")
ENABLE_JIRA     = os.getenv("ENABLE_JIRA", "1") not in ("0", "false", "False")
ENABLE_SLACK    = os.getenv("ENABLE_SLACK", "1") not in ("0", "false", "False")

def _watermark(st, default_days=30):
    if st and st.last_updated_at:
        return st.last_updated_at
    return datetime.utcnow() - timedelta(days=default_days)

def _safe_dt(dt): return dt if isinstance(dt, datetime) else None

def _commit_session(session):
    try:
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        raise e

def _sync_source(name, fetch_fn):
    out = {"source": name, "fetched": 0, "last_updated_at": None, "ok": False}
    try:
        with SessionLocal() as session:
            st = get_or_create_sync_state(session, name)
            since_dt = _watermark(st, HISTORY_DAYS)
            items = fetch_fn(since_dt)

            latest = since_dt
            for it in items:
                payload = {
                    "source": name,
                    "external_id": it["external_id"],
                    "title": it.get("title","") or "",
                    "content": it.get("content","") or "",
                    "type": it.get("type","unknown") or "unknown",
                    "status": it.get("status","") or "",
                    "priority": it.get("priority","") or "",
                    "requester": it.get("requester","") or "",
                    "requester_role": it.get("requester_role","") or "",
                    "requester_email": it.get("requester_email","") or "",
                    "submitter": it.get("submitter","") or "",
                    "submitter_role": it.get("submitter_role","") or "",
                    "submitter_email": it.get("submitter_email","") or "",
                    "assignee": it.get("assignee","") or "",
                    "labels": it.get("labels","") or "",
                    "url": it.get("url","") or "",
                    "project": it.get("project","") or "",
                    "is_internal": it.get("is_internal", None),
                    "is_shared": it.get("is_shared", None),
                    "sharing_type": it.get("sharing_type", "") or "",
                    "source_created_at": _safe_dt(it.get("source_created_at")),
                    "source_updated_at": _safe_dt(it.get("source_updated_at")),
                }
                upsert_ticket(session, payload)
                if it.get("source_updated_at") and it["source_updated_at"] > latest:
                    latest = it["source_updated_at"]

            st.last_run_at = datetime.utcnow()
            st.last_updated_at = latest
            _commit_session(session)

            out.update(ok=True, fetched=len(items), last_updated_at=latest.isoformat())
    except Exception as e:
        out["error"] = str(e)
    return out

def sync_zendesk():
    return _sync_source("zendesk", zc.fetch_incremental_tickets)

def sync_jira():
    return _sync_source("jira", jc.fetch_issues)

def sync_slack():
    return _sync_source("slack", sc.fetch_incremental_messages)

def sync_all():
    results = []
    if ENABLE_ZENDESK:
        results.append(sync_zendesk())
    if ENABLE_JIRA:
        results.append(sync_jira())
    if ENABLE_SLACK:
        results.append(sync_slack())
    return results
