import os
import time
from datetime import datetime, timedelta, timezone
import requests

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
    return items

def _map_ticket_from_incremental(t: dict):
    return {
        "external_id": str(t["id"]),
        "title": t.get("subject") or "",
        "content": t.get("description") or "",
        "status": t.get("status") or "",
        "priority": t.get("priority") or "",
        "requester": str(t.get("requester_id") or ""),
        "assignee": str(t.get("assignee_id") or ""),
        "labels": ",".join(t.get("tags") or []),
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
                "assignee": str(r.get("assignee_id") or ""),
                "labels": ",".join(r.get("tags") or []),
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

    return results
