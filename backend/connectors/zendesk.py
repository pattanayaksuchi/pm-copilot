import os
import time
from datetime import datetime, timedelta, timezone
import requests
from typing import Dict, List, Set

Z_SUB = os.getenv("ZENDESK_SUBDOMAIN")
Z_EMAIL = os.getenv("ZENDESK_EMAIL")
Z_TOKEN = os.getenv("ZENDESK_API_TOKEN")
HISTORY_DAYS = int(os.getenv("SYNC_HISTORY_DAYS", "30"))

AUTH = (f"{Z_EMAIL}/token", Z_TOKEN)
BASE = f"https://{Z_SUB}.zendesk.com/api/v2"

JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Config for internal-vs-external classification (non-destructive)
INTERNAL_EMAIL_DOMAINS: Set[str] = set(
    [d.strip().lower() for d in (os.getenv("INTERNAL_EMAIL_DOMAINS", "nium.com,instarem.com").split(",")) if d.strip()]
)
ALLOWED_REQUESTER_ROLES: Set[str] = set(
    [r.strip().lower() for r in (os.getenv("ZENDESK_ALLOWED_REQUESTER_ROLES", "end-user").split(",")) if r.strip()]
)
INTERNAL_TAGS: Set[str] = set(
    [t.strip().lower() for t in (os.getenv("ZENDESK_INTERNAL_TAGS", "internal,partner,vendor").split(",")) if t.strip()]
)

def _to_dt(s: str | None):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)

def _watermark_dt(updated_after: datetime | None):
    if updated_after is None:
        return datetime.utcnow() - timedelta(days=HISTORY_DAYS)
    return updated_after

def fetch_incremental_tickets(updated_after: datetime | None):
    """
    Try Incremental Tickets (cursor) API; on 401/403, fall back to windowed Search API.
    """
    since_dt = _watermark_dt(updated_after)

    try:
        items = _fetch_incremental_cursor(since_dt)
        return items
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status in (401, 403):
            return _fetch_search_api_windowed(since_dt)
        raise
    except Exception:
        return _fetch_search_api_windowed(since_dt)

def _fetch_incremental_cursor(since_dt: datetime):
    items = []
    start_time = int(since_dt.replace(tzinfo=timezone.utc).timestamp())
    url = f"{BASE}/incremental/tickets/cursor.json?start_time={start_time}"

    while url:
        resp = requests.get(url, auth=AUTH, headers=JSON_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for t in data.get("tickets", []):
            items.append(_map_ticket_from_incremental(t))

        url = data.get("after_url")
        time.sleep(0.2)
    return annotate_is_internal(items)

def _map_ticket_from_incremental(t: dict):
    return {
        "external_id": str(t["id"]),
        "title": t.get("subject") or "",
        "content": t.get("description") or "",
        "status": t.get("status") or "",
        "priority": t.get("priority") or "",
        "requester": str(t.get("requester_id") or ""),
        "submitter": str(t.get("submitter_id") or ""),
        "assignee": str(t.get("assignee_id") or ""),
        "labels": ",".join(t.get("tags") or []),
        # Keep minimal via info needed to infer sharing
        "via": t.get("via") or {},
        "sharing_agreement_ids": t.get("sharing_agreement_ids") or [],
        "url": f"https://{Z_SUB}.zendesk.com/agent/tickets/{t['id']}",
        "source_created_at": _to_dt(t.get("created_at")),
        "source_updated_at": _to_dt(t.get("updated_at")),
    }

# ---------- Windowed Search fallback (avoids 1000-result cap) ----------

def _fetch_search_api_windowed(since_dt: datetime, initial_window_days: int = 7):
    """
    Iterate over time windows: [start, end) with updated>=start updated<end
    Keeps each query under ~1000 results to avoid 422.
    Shrinks the window if 422 still occurs.
    """
    items = []
    now = datetime.utcnow()

    start = since_dt
    while start < now:
        window_days = initial_window_days
        window_fetched = []

        # Try shrinking window on 422 (cap exceeded)
        while window_days >= 1:
            end = min(start + timedelta(days=window_days), now)
            try:
                batch = _search_api_paged(start, end)
                window_fetched = batch
                break
            except requests.HTTPError as e:
                if getattr(e.response, "status_code", None) == 422:
                    # Shrink window and retry
                    window_days = 3 if window_days > 3 else 1 if window_days > 1 else 0
                    if window_days == 0:
                        raise
                    continue
                else:
                    raise

        items.extend(window_fetched)
        # Advance to end of successful window
        start = end

    return items

def _search_api_paged(start_dt: datetime, end_dt: datetime):
    """
    Pull pages for a given window. Zendesk Search limit ~1000 results per query.
    We cap pages at 10 (per_page=100) and then the caller will shrink window if needed.
    """
    results = []
    page = 1
    per_page = 100
    max_pages = 10  # 10 * 100 = 1000 max

    # Search syntax: updated>=YYYY-MM-DD updated<YYYY-MM-DD
    q_start = start_dt.strftime("%Y-%m-%d")
    q_end = end_dt.strftime("%Y-%m-%d")
    query = f'type:ticket updated>={q_start} updated<{q_end}'

    while page <= max_pages:
        params = {
            "query": query,
            "sort_by": "updated_at",
            "sort_order": "asc",
            "page": page,
            "per_page": per_page
        }
        resp = requests.get(f"{BASE}/search.json", auth=AUTH, headers=JSON_HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        chunk = []
        for r in data.get("results", []):
            if r.get("result_type") != "ticket":
                continue
            chunk.append({
                "external_id": str(r["id"]),
                "title": r.get("subject") or "",
                "content": r.get("description") or "",
                "status": r.get("status") or "",
                "priority": r.get("priority") or "",
                "requester": str(r.get("requester_id") or ""),
                "submitter": str(r.get("submitter_id") or ""),
                "assignee": str(r.get("assignee_id") or ""),
                "labels": ",".join(r.get("tags") or []),
                "via": r.get("via") or {},
                "sharing_agreement_ids": r.get("sharing_agreement_ids") or [],
                "url": f"https://{Z_SUB}.zendesk.com/agent/tickets/{r['id']}",
                "source_created_at": _to_dt(r.get("created_at")),
                "source_updated_at": _to_dt(r.get("updated_at")),
            })

        results.extend(chunk)

        # Stop if fewer than per_page (no more)
        if len(chunk) < per_page:
            break

        page += 1
        time.sleep(0.2)  # rate limit friendliness

    return annotate_is_internal(results)


def _fetch_users_by_ids(ids: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not ids:
        return out
    # Zendesk allows up to 100 ids per call
    for i in range(0, len(ids), 100):
        chunk = [id for id in ids[i:i+100] if id]
        if not chunk:
            continue
        ids_param = ",".join(chunk)
        url = f"{BASE}/users/show_many.json?ids={ids_param}"
        resp = requests.get(url, auth=AUTH, headers=JSON_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for u in data.get("users", []):
            uid = str(u.get("id") or "")
            out[uid] = {
                "role": (u.get("role") or "").lower(),
                "email": (u.get("email") or "").lower(),
            }
        time.sleep(0.1)
    return out


def _fetch_sharing_types_by_ids(ids: List[int]) -> Dict[int, str]:
    """Return mapping of sharing_agreement_id -> type (e.g., inbound|outbound)."""
    out: Dict[int, str] = {}
    if not ids:
        return out
    for i in range(0, len(ids), 100):
        chunk = ids[i:i+100]
        ids_param = ",".join(str(x) for x in chunk)
        url = f"{BASE}/sharing_agreements/show_many.json?ids={ids_param}"
        resp = requests.get(url, auth=AUTH, headers=JSON_HEADERS, timeout=30)
        if resp.status_code == 404:
            # Some accounts may not expose this; skip gracefully
            continue
        resp.raise_for_status()
        data = resp.json()
        for a in data.get("sharing_agreements", []):
            try:
                aid = int(a.get("id"))
                atype = (a.get("type") or "").lower()
                if aid and atype:
                    out[aid] = atype
            except Exception:
                continue
        time.sleep(0.1)
    return out


def _is_internal_email(email: str) -> bool:
    if not email:
        return False
    try:
        domain = email.split('@', 1)[1].lower()
    except Exception:
        return False
    return domain in INTERNAL_EMAIL_DOMAINS if INTERNAL_EMAIL_DOMAINS else False


def annotate_is_internal(items: List[dict]) -> List[dict]:
    """Annotate items with `is_internal` (True/False) using org rule.

    Rule (External if any of these is true):
      - submitter.role = 'end-user' AND submitter.email domain NOT IN INTERNAL_EMAIL_DOMAINS AND (sharing.type != 'inbound' OR sharing.type IS NULL)
      - requester.role = 'end-user' AND requester.email domain NOT IN INTERNAL_EMAIL_DOMAINS AND (sharing.type != 'inbound' OR sharing.type IS NULL)
    Else Internal.
    """
    if not items:
        return items
    requester_ids = sorted({str(it.get("requester") or "") for it in items if str(it.get("requester") or "").strip()})
    submitter_ids = sorted({str(it.get("submitter") or "") for it in items if str(it.get("submitter") or "").strip()})
    users: Dict[str, dict] = {}
    try:
        ids = sorted({*requester_ids, *submitter_ids})
        users = _fetch_users_by_ids(ids)
    except Exception:
        users = {}

    # Resolve sharing types for items that have explicit sharing_agreement_ids
    aggr_ids: List[int] = []
    for it in items:
        for sid in (it.get("sharing_agreement_ids") or []):
            try:
                aggr_ids.append(int(sid))
            except Exception:
                continue
    sharing_types: Dict[int, str] = {}
    try:
        sharing_types = _fetch_sharing_types_by_ids(sorted(set(aggr_ids)))
    except Exception:
        sharing_types = {}

    def _domain(email: str) -> str:
        if not email:
            return ""
        try:
            return email.split('@', 1)[1].lower()
        except Exception:
            return ""

    for it in items:
        # Determine sharing type; check agreements first, then fallback to rel
        sharing_type = None
        ag_ids = it.get("sharing_agreement_ids") or []
        for sid in ag_ids:
            try:
                st = sharing_types.get(int(sid))
                if st:
                    sharing_type = st
                    break
            except Exception:
                continue
        if not sharing_type:
            via = it.get("via") or {}
            src = (via.get("source") or {}) if isinstance(via, dict) else {}
            rel = (src.get("rel") or "").lower()
            # rel='ticket_sharing' without agreement details → unknown
            sharing_type = None

        # Gather users
        req = users.get(str(it.get("requester") or "")) or {}
        sub = users.get(str(it.get("submitter") or "")) or {}

        # Evaluate external conditions
        submitter_external = (
            (sub.get("role") == "end-user") and (_domain(sub.get("email")) not in INTERNAL_EMAIL_DOMAINS) and (sharing_type != "inbound")
        )
        requester_external = (
            (req.get("role") == "end-user") and (_domain(req.get("email")) not in INTERNAL_EMAIL_DOMAINS) and (sharing_type != "inbound")
        )

        is_external = submitter_external or requester_external

        it["is_internal"] = (not is_external)
        # Also attach resolved metadata for persistence/audit
        it["requester_role"] = (req.get("role") or "")
        it["requester_email"] = (req.get("email") or "")
        it["submitter_role"] = (sub.get("role") or "")
        it["submitter_email"] = (sub.get("email") or "")
        it["is_shared"] = True if sharing_type in ("inbound", "outbound") else None
        it["sharing_type"] = sharing_type

    return items
