import os, base64, requests
from datetime import datetime, timedelta

J_DOMAIN = os.getenv("JIRA_DOMAIN")
J_EMAIL  = os.getenv("JIRA_EMAIL")
J_TOKEN  = os.getenv("JIRA_API_TOKEN")
J_PROJECT_KEYS = os.getenv("JIRA_PROJECT_KEYS", "")
HISTORY_DAYS = int(os.getenv("SYNC_HISTORY_DAYS", "30"))

BASE = f"https://{J_DOMAIN}/rest/api/3"

def _auth_header():
    raw = f"{J_EMAIL}:{J_TOKEN}".encode()
    return {
        "Authorization": "Basic " + base64.b64encode(raw).decode(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def _to_dt(s):
    if not s: return None
    if s.endswith("+0000"): s = s[:-5] + "+00:00"
    try: return datetime.fromisoformat(s).replace(tzinfo=None)
    except: return None

def build_jql(updated_after: datetime | None):
    dt = updated_after or (datetime.utcnow() - timedelta(days=HISTORY_DAYS))
    jql_time = dt.strftime("%Y-%m-%d %H:%M")
    parts = [f'updated >= "{jql_time}"']
    if J_PROJECT_KEYS.strip():
        keys = ",".join(k.strip() for k in J_PROJECT_KEYS.split(",") if k.strip())
        parts.append(f"project in ({keys})")
    return " AND ".join(parts)

def _search_post_jql(headers, jql, next_token=None, max_results=100):
    payload = {
        "jql": jql,
        "maxResults": max_results,
        "fields": ["summary","description","status","priority","assignee","reporter","created","updated","labels","project"],
    }
    if next_token:
        payload["nextPageToken"] = next_token
    resp = requests.post(f"{BASE}/search/jql", headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()

def fetch_issues(updated_after: datetime | None):
    headers = _auth_header()
    jql = build_jql(updated_after)

    items = []
    next_token = None
    while True:
        data = _search_post_jql(headers, jql, next_token, max_results=100)

        for issue in data.get("issues", []):
            key = issue["key"]; f = issue.get("fields", {})
            desc = f.get("description")
            if isinstance(desc, dict):  # ADF → stringify for MVP
                desc = str(desc)
            items.append({
                "external_id": key,
                "title": f.get("summary") or "",
                "content": desc or "",
                "status": (f.get("status") or {}).get("name") or "",
                "priority": (f.get("priority") or {}).get("name") or "",
                "assignee": (f.get("assignee") or {}).get("displayName") or "",
                "requester": (f.get("reporter") or {}).get("displayName") or "",
                "labels": ",".join(f.get("labels") or []),
                "url": f"https://{J_DOMAIN}/browse/{key}",
                "project": (f.get("project") or {}).get("key") or "",
                "source_created_at": _to_dt(f.get("created")),
                "source_updated_at": _to_dt(f.get("updated")),
            })

        # New pagination model
        is_last = data.get("isLast", True)
        next_token = data.get("nextPageToken")
        if is_last or not next_token:
            break

    return items
