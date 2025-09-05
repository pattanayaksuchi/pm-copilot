PM Copilot (Monorepo)

A lightweight product insights dashboard that clusters recent tickets from Slack, Zendesk, and Jira into themes, and surfaces Top 10 Issues and Feature Requests. Monorepo contains a FastAPI backend and a React frontend.

**Features**
- Theming: Clusters recent tickets into interpretable themes with a label and hint.
- Top 10 lists: Quick view of the most frequent Issues and Feature Requests.
- Filters: Slice by source (`slack`, `zendesk`, `jira`) and type (`issue`, `feature_request`, `unknown`).
- CSV export: Download Top 10 or full theme breakdowns as CSV.
- On-demand sync: Trigger per‑source or full sync from the API.
- Light footprint: Uses SQLite by default; no external infra required for dev.

**Overview**
- Backend: FastAPI service that syncs data sources, embeds + clusters tickets, builds themes, and exposes CSV exports.
- Frontend: Minimal React app to view themes, Top 10 lists, and export CSVs.
- Storage: SQLite by default (can switch to Postgres via `DATABASE_URL`).

**Architecture**
- Backend entry: `backend/main.py`
- Insights core: `backend/services/insights.py`
- Connectors: `backend/connectors/{slack,jira,zendesk}.py`
- Frontend app: `frontend/src/App.js`

**Quick Start**
1) Requirements
- Python 3.10+ and Node 18+
- Create and activate a Python venv (recommended)

2) Backend
- Install deps: `pip install -r requirements.txt`
- Copy env: `cp .env.example .env` and fill values as needed
- Run API (from repo root): `python -m uvicorn backend.main:app --reload`
  - API runs at `http://localhost:8000`

3) Frontend
- `cd frontend`
- Install deps: `npm install`
- Run dev server: `npm start`
  - App runs at `http://localhost:3000`

**Environment**
Use `.env.example` as a template:
- Toggle sources and schedule: `ENABLE_*`, `SYNC_DAILY_CRON_*`
- Source credentials: `ZENDESK_*`, `JIRA_*`, `SLACK_*`
- Optional DB: `DATABASE_URL` (Postgres), otherwise local SQLite is used

**API Endpoints (selected)**
- Health: `GET /`
- Sync: `POST /sync/run`, `POST /sync/jira`, `POST /sync/zendesk`, `POST /sync/slack`
- Themes (with filters): `GET /insights/themes/v2?days&k&source&kind`
- Top 10 (overview): `GET /insights/top10?days&k`
- Export CSVs: `GET /export/top10.csv?days&k&source&kind`, `GET /export/themes.csv?days&k&source&kind`

Notes:
- `source` is one of `all|slack|zendesk|jira`
- `kind` is one of `all|issue|feature_request|unknown`

**Frontend UI**
- Controls for days, clusters (`k`), source and type filters
- Buttons:
  - Refresh: loads themes and top lists via `/insights/themes/v2`
  - Load Top 10: loads only Top 10 via `/insights/top10`
  - Export Top 10 / Themes: downloads CSVs respecting current filters

**How To Use**
- Start services: run backend (`uvicorn backend.main:app --reload`) and frontend (`npm start` in `frontend/`).
- Choose time window: set `Days` (e.g., 30) to analyze recent activity.
- Adjust cluster count: set `K` to control number of themes (e.g., 8–20).
- Apply filters:
  - `Source`: All, Slack, Zendesk, or JIRA.
  - `Type`: All, Issue, Feature Request, or Unknown.
- Load data:
  - Use `Refresh` to load Themes + Top 10 with filters applied.
  - Use `Load Top 10` to refresh only the Top 10 lists.
- Explore themes:
  - Each theme shows a hint, type, and size; expand to see tickets with links.
- Export:
  - `Export Top 10 CSV` → columns: `rank,type,title,source,url`.
  - `Export Themes CSV` → columns: `theme_label,type,size,hint,ticket_id,ticket_title,ticket_source,ticket_url`.

**Syncing Data**
- Full sync: `POST /sync/run`
- Per‑source: `POST /sync/{zendesk|jira|slack}`
- Scheduler: configured via `SYNC_DAILY_CRON_HOUR` and `SYNC_DAILY_CRON_MINUTE`; enabled at app startup.

**Tips**
- Start small: lower `k` for broader themes; raise it for granularity.
- Filters recompute Top 10 based on filtered tickets in each theme.
- For Postgres, set `DATABASE_URL` and ensure the DB is reachable before running.

**Git Workflow (basics)**
- First push: add a remote and push `main`
- Daily flow: `git add -A && git commit -m "msg" && git push`
- Recommended: use feature branches and Pull Requests

**Troubleshooting**
- CORS in dev: Backend whitelists `http://localhost:3000`
- Tokenizers warning: disabled via `TOKENIZERS_PARALLELISM=false`
- Favicon 404 in logs: harmless (browser request)

---
This project is an MVP; expect fast iteration and evolving APIs.
