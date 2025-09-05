import re

RE_FEATURE = re.compile(r"\b(feature|request|enhancement|support.*|would like|nice to have|roadmap)\b", re.I)
RE_ISSUE   = re.compile(r"\b(bug|error|fail|failing|broken|crash|incident|downtime|not working|fix)\b", re.I)

def classify_ticket(source: str, title: str, content: str, labels_csv: str, status: str) -> str:
    text = f"{title} {content} {labels_csv} {status}".lower()
    # source-specific hints (Jira issuetype not fetched here; rely on text)
    if RE_FEATURE.search(text) and not RE_ISSUE.search(text):
        return "feature_request"
    if RE_ISSUE.search(text) and not RE_FEATURE.search(text):
        return "issue"
    # tie-breaker by source norms
    if source == "jira":
        # many jira items are engineering/issue oriented
        return "issue"
    if source == "zendesk":
        # many zendesk items are requests
        return "feature_request"
    return "unknown"
