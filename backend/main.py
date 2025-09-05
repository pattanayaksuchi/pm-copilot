import os
import io
import csv
from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from sync import sync_all, sync_jira, sync_zendesk, sync_slack
from services.insights import build_themes, build_themes_filtered
from services.cache import themes_cache
from pydantic import BaseModel
import uvicorn


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
def get_insights(days: int = 30, k: int = 12):
    """
    Build insights from tickets stored in DB (all sources).
    Mirrors /insights/themes with defaults; kept for backwards compatibility.
    """
    return build_themes(days=days, k=k)

@app.get("/insights/themes")
def insights_themes(days: int = 30, k: int = 12):
    """
    Build themes from last <days> and return clusters + top lists.
    """
    result = build_themes(days=days, k=k)
    return result

@app.get("/insights/themes/v2")
def insights_themes_v2(
    days: int = Query(30, ge=1, le=365),
    k: int = Query(12, ge=1, le=100),
    source: str = Query("all"),
    kind: str = Query("all")
):
    """
    Returns themes with optional filtering by source (slack|zendesk|jira|all)
    and kind (issue|feature_request|unknown|all). Cached for ~2 minutes.
    """
    cache_key = f"themes:{days}:{k}:{source}:{kind}"
    cached = themes_cache.get(cache_key)
    if cached:
        return cached

    _kind = None if kind == "all" else kind
    _source = None if source == "all" else source
    data = build_themes_filtered(days=days, k=k, source=_source, kind=_kind)
    themes_cache.set(cache_key, data)
    return data


@app.get("/insights/top10")
def insights_top10(days: int = 30, k: int = 12):
    """
    Convenience endpoint that returns only Top 10 Issues & Feature Requests.
    """
    result = build_themes(days=days, k=k)
    return {
        "run_id": result["run_id"],
        "top_issues": result["top_issues"],
        "top_features": result["top_features"]
    }

@app.get("/export/top10.csv")
def export_top10_csv(days: int = 30, k: int = 12, source: str = "all", kind: str = "all"):
    _kind = None if kind == "all" else kind
    _source = None if source == "all" else source
    data = build_themes_filtered(days=days, k=k, source=_source, kind=_kind)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["rank","type","title","source","url"])
    for i, t in enumerate(data["top_issues"], start=1):
        writer.writerow([i, "issue", t.get("title",""), t.get("source",""), t.get("url","")])
    for i, t in enumerate(data["top_features"], start=1):
        writer.writerow([i, "feature_request", t.get("title",""), t.get("source",""), t.get("url","")])
    contents = output.getvalue()
    return Response(contents, media_type="text/csv")

@app.get("/export/themes.csv")
def export_themes_csv(days: int = 30, k: int = 12, source: str = "all", kind: str = "all"):
    _kind = None if kind == "all" else kind
    _source = None if source == "all" else source
    data = build_themes_filtered(days=days, k=k, source=_source, kind=_kind)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["theme_label","type","size","hint","ticket_id","ticket_title","ticket_source","ticket_url"])
    for th in data["themes"]:
        for t in th["tickets"]:
            writer.writerow([th["label"], th["type"], th["size"], th["hint"], t["id"], t["title"], t["source"], t["url"]])
    return Response(output.getvalue(), media_type="text/csv")

@app.post("/sync/slack")
def run_sync_slack():
    return {"result": sync_slack()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
