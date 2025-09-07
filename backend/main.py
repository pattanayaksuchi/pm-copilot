import os
import io
import csv
from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from sync import sync_all, sync_jira, sync_zendesk, sync_slack
from services.insights import build_themes, build_themes_filtered, suggest_themes
from services.cache import themes_cache
from services.verticals import backfill_verticals
from services.maintenance import backfill_zendesk_internal_flags
from services.review import generate_review_sample_csv, generate_review_sample_json, submit_labels
from pydantic import BaseModel
from services.calibration import calibrate_precision_coverage, calibrate_by_vertical
from services.query import answer_question
from pydantic import BaseModel
import uvicorn
from services.audit import audit_zendesk_internal, audit_zendesk_internal_csv
from services.analytics import zendesk_label_frequencies


load_dotenv()  # take environment variables from .env.
# Silence HuggingFace tokenizers fork warning by default (unless user overrides)
if "TOKENIZERS_PARALLELISM" not in os.environ:
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

app = FastAPI(title="PM Copilot MVP Phase 1")

# CORS for local React dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sample model for connecting a data source
class DataSource(BaseModel):
    source: str
    token: str

@app.get("/")
def health():
    return {"status": "ok"}

@app.post("/sync/run")
def run_sync():
    result = sync_all()
    # Always 200: frontend can show per-source ok/error
    return {"result": result}

@app.post("/sync/jira")
def run_sync_jira():
    return {"result": sync_jira()}

@app.post("/sync/zendesk")
def run_sync_zd():
    return {"result": sync_zendesk()}

# ---- Daily scheduler ----
scheduler = BackgroundScheduler()

def _schedule_jobs():
    hour = int(os.getenv("SYNC_DAILY_CRON_HOUR", "2"))
    minute = int(os.getenv("SYNC_DAILY_CRON_MINUTE", "0"))
    scheduler.add_job(sync_all, "cron", hour=hour, minute=minute, id="daily_sync_all", replace_existing=True)

@app.on_event("startup")
def on_startup():
    _schedule_jobs()
    scheduler.start()

@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown(wait=False)

@app.post("/connect")
def connect_source(ds: DataSource):
    # Later: Store OAuth tokens in DB
    return {"status": "connected", "source": ds.source}

@app.get("/insights")
def get_insights(days: int = 30, k: int = 12, include_internal: bool = False):
    """
    Build insights from tickets stored in DB (all sources).
    Mirrors /insights/themes with defaults; kept for backwards compatibility.
    """
    return build_themes(days=days, k=k, include_internal=include_internal)

@app.get("/insights/themes")
def insights_themes(days: int = 30, k: int = 12, include_internal: bool = False):
    """
    Build themes from last <days> and return clusters + top lists.
    """
    result = build_themes(days=days, k=k, include_internal=include_internal)
    return result

@app.get("/insights/themes/v2")
def insights_themes_v2(
    days: int = Query(30, ge=1, le=365),
    k: int = Query(12, ge=1, le=100),
    source: str = Query("all"),
    kind: str = Query("all"),
    vertical: str = Query("all"),
    include_internal: bool = Query(False)
):
    """
    Returns themes with optional filtering by source (slack|zendesk|jira|all)
    and kind (issue|feature_request|unknown|all). Cached for ~2 minutes.
    """
    cache_key = f"themes:{days}:{k}:{source}:{kind}:{vertical}:{int(include_internal)}"
    cached = themes_cache.get(cache_key)
    if cached:
        return cached

    _kind = None if kind == "all" else kind
    _source = None if source == "all" else source
    _vertical = None if vertical == "all" else vertical
    data = build_themes_filtered(days=days, k=k, source=_source, kind=_kind, vertical=_vertical, include_internal=include_internal)
    themes_cache.set(cache_key, data)
    return data


@app.get("/insights/top10")
def insights_top10(days: int = 30, k: int = 12, include_internal: bool = False):
    """
    Convenience endpoint that returns only Top 10 Issues & Feature Requests.
    """
    result = build_themes(days=days, k=k, include_internal=include_internal)
    return {
        "run_id": result["run_id"],
        "top_issues": result["top_issues"],
        "top_features": result["top_features"]
    }

@app.get("/insights/theme_suggestions")
def insights_theme_suggestions(days: int = 30, k: int = 12, top_n: int = 5, include_internal: bool = False):
    """
    Suggest themes for PM focus with a simple priority score.
    """
    return suggest_themes(days=days, k=k, top_n=top_n, include_internal=include_internal)

@app.get("/export/top10.csv")
def export_top10_csv(days: int = 30, k: int = 12, source: str = "all", kind: str = "all", vertical: str = "all", include_internal: bool = False):
    _kind = None if kind == "all" else kind
    _source = None if source == "all" else source
    _vertical = None if vertical == "all" else vertical
    data = build_themes_filtered(days=days, k=k, source=_source, kind=_kind, vertical=_vertical, include_internal=include_internal)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["rank","type","title","source","product_vertical","url"])
    for i, t in enumerate(data["top_issues"], start=1):
        writer.writerow([i, "issue", t.get("title",""), t.get("source",""), t.get("product_vertical",""), t.get("url","")])
    for i, t in enumerate(data["top_features"], start=1):
        writer.writerow([i, "feature_request", t.get("title",""), t.get("source",""), t.get("product_vertical",""), t.get("url","")])
    contents = output.getvalue()
    return Response(contents, media_type="text/csv")

@app.get("/export/themes.csv")
def export_themes_csv(days: int = 30, k: int = 12, source: str = "all", kind: str = "all", vertical: str = "all", include_internal: bool = False):
    _kind = None if kind == "all" else kind
    _source = None if source == "all" else source
    _vertical = None if vertical == "all" else vertical
    data = build_themes_filtered(days=days, k=k, source=_source, kind=_kind, vertical=_vertical, include_internal=include_internal)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["theme_label","type","size","hint","ticket_id","ticket_title","ticket_source","product_vertical","ticket_url"])
    for th in data["themes"]:
        for t in th["tickets"]:
            writer.writerow([th["label"], th["type"], th["size"], th["hint"], t["id"], t["title"], t["source"], t.get("product_vertical",""), t["url"]])
    return Response(output.getvalue(), media_type="text/csv")

@app.post("/sync/slack")
def run_sync_slack():
    return {"result": sync_slack()}

@app.post("/maintenance/backfill_verticals")
def maintenance_backfill_verticals(days: int | None = None):
    """Run product-vertical classification across tickets. Pass days=N to limit scope."""
    res = backfill_verticals(days=days)
    return {"result": res}

@app.post("/maintenance/backfill_zendesk_internal")
def maintenance_backfill_zendesk_internal(days: int | None = None):
    """Backfill Ticket.is_internal for Zendesk tickets using configured rules."""
    res = backfill_zendesk_internal_flags(days=days)
    return {"result": res}

@app.get("/audit/zendesk_internal")
def audit_zendesk_internal_endpoint(days: int = 30, limit: int = 500):
    """Audit the internal/external classification for Zendesk tickets."""
    return audit_zendesk_internal(days=days, limit=limit)

@app.get("/audit/zendesk_internal.csv")
def audit_zendesk_internal_csv_endpoint(days: int = 30, limit: int = 1000):
    contents = audit_zendesk_internal_csv(days=days, limit=limit)
    from fastapi import Response
    return Response(contents, media_type="text/csv")

@app.get("/analytics/zendesk/label_frequencies")
def analytics_zendesk_label_frequencies(days: int = 90, include_internal: bool = False, min_count: int = 1, top: int | None = None):
    """Return frequency of Zendesk labels (tags) over the last N days."""
    return zendesk_label_frequencies(days=days, include_internal=include_internal, min_count=min_count, top=top)

@app.get("/export/zendesk/label_frequencies.csv")
def export_zendesk_label_frequencies_csv(days: int = 90, include_internal: bool = False, min_count: int = 1, top: int | None = None):
    from fastapi import Response
    data = zendesk_label_frequencies(days=days, include_internal=include_internal, min_count=min_count, top=top)
    # Compose CSV
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["label","count"]) 
    for item in data.get("items", []):
        writer.writerow([item.get("label",""), item.get("count",0)])
    return Response(output.getvalue(), media_type="text/csv")

@app.get("/calibrate/verticals")
def calibrate_verticals(days: int = 30, sources: str = "jira,zendesk"):
    """Compute precision vs coverage curves using rule-matched tickets as ground truth.
    sources: comma-separated list (e.g., jira,zendesk)
    """
    srcs = [s.strip() for s in (sources or "").split(",") if s.strip()]
    res = calibrate_precision_coverage(days=days, sources=srcs)
    return res

@app.get("/calibrate/verticals/by_product")
def calibrate_verticals_by_product(days: int = 30, threshold: float = 0.8, sources: str = "jira,zendesk"):
    """Per-vertical precision and recall (on labeled set) at a given threshold."""
    srcs = [s.strip() for s in (sources or "").split(",") if s.strip()]
    res = calibrate_by_vertical(days=days, sources=srcs, threshold=threshold)
    return res

@app.get("/review/sample.csv")
def review_sample_csv(days: int = 30, per_bin: int = 50, bins: str | None = None):
    """Export a stratified review CSV across confidence bins for manual labeling.
    bins example: 0.6-0.7,0.7-0.8,0.8-0.9,0.9-1.0
    """
    contents = generate_review_sample_csv(days=days, per_bin=per_bin, bins=bins)
    return Response(contents, media_type="text/csv")

@app.get("/review/sample")
def review_sample(days: int = 30, per_bin: int = 50, bins: str | None = None):
    return {"items": generate_review_sample_json(days=days, per_bin=per_bin, bins=bins)}

class ReviewItem(BaseModel):
    ticket_id: int
    vertical_slug: str | None = None
    vertical_name: str | None = None
    note: str | None = None

class ReviewPayload(BaseModel):
    reviewer: str | None = ""
    items: list[ReviewItem]

@app.post("/review/labels")
def review_submit_labels(payload: ReviewPayload):
    res = submit_labels([{
        "ticket_id": it.ticket_id,
        "vertical_slug": it.vertical_slug,
        "vertical_name": it.vertical_name,
        "note": it.note,
    } for it in payload.items], reviewer=payload.reviewer or "")
    return {"result": res}

class ChatRequest(BaseModel):
    question: str
    days: int | None = 30
    top_k: int | None = 5
    source: str | None = "all"   # all|slack|zendesk|jira
    kind: str | None = "all"      # all|issue|feature_request|unknown
    vertical: str | None = "all"  # all or slug/name
    include_internal: bool | None = False

@app.post("/chat/query")
def chat_query(payload: ChatRequest):
    out = answer_question(
        question=payload.question,
        days=payload.days or 30,
        top_k=payload.top_k or 5,
        source=payload.source,
        kind=payload.kind,
        vertical=payload.vertical,
        include_internal=bool(payload.include_internal),
    )
    return out

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
