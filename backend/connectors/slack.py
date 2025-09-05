import requests
import os
from datetime import datetime, timezone

SLACK_TOKEN = os.getenv("SLACK_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

def fetch_slack_messages():
    """
    Simple convenience fetch (last page only). Not used by sync.
    """
    url = "https://slack.com/api/conversations.history"
    headers = {"Authorization": f"Bearer {SLACK_TOKEN}"}
    params = {"channel": SLACK_CHANNEL, "limit": 100}

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    messages = []
    if data.get("ok"):
        for msg in data.get("messages", []):
            messages.append({
                "id": msg.get("ts"),
                "text": msg.get("text", "")
            })
    return messages


def _ts_to_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def fetch_incremental_messages(updated_after: datetime | None):
    """
    Fetch Slack messages from a channel since the given datetime using pagination.
    Maps results to the normalized sync item shape expected by sync._sync_source.
    """
    if not SLACK_TOKEN or not SLACK_CHANNEL:
        return []

    url = "https://slack.com/api/conversations.history"
    headers = {"Authorization": f"Bearer {SLACK_TOKEN}"}
    params = {
        "channel": SLACK_CHANNEL,
        "limit": 200,
    }
    if updated_after is not None:
        params["oldest"] = str(updated_after.replace(tzinfo=timezone.utc).timestamp())

    items = []
    next_cursor = None
    while True:
        if next_cursor:
            params["cursor"] = next_cursor
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            break

        for msg in data.get("messages", []):
            if msg.get("subtype"):
                # skip non-user message events for MVP
                continue
            ts = msg.get("ts")
            text = msg.get("text") or ""
            items.append({
                "external_id": ts or "",
                "title": text[:80],
                "content": text,
                "status": "",
                "priority": "",
                "requester": msg.get("user") or "",
                "assignee": "",
                "labels": "slack",
                "url": "",
                "project": "",
                "source_created_at": _ts_to_dt(ts),
                "source_updated_at": _ts_to_dt(ts),
            })

        next_cursor = ((data.get("response_metadata") or {}).get("next_cursor") or "").strip()
        if not next_cursor:
            break

    return items
