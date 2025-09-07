PM Copilot (Monorepo)

A lightweight product insights dashboard that clusters recent tickets from Slack, Zendesk, and Jira into themes, and surfaces Top 10 Issues and Feature Requests. Monorepo contains a FastAPI backend and a React frontend.

**Features**
- Theming: Clusters recent tickets into interpretable themes with a label and hint.
- Top 10 lists: Quick view of the most frequent Issues and Feature Requests.
- Filters: Slice by source (`slack`, `zendesk`, `jira`) and type (`issue`, `feature_request`, `unknown`).
- CSV export: Download Top 10 or full theme breakdowns as CSV.
- On-demand sync: Trigger per‑source or full sync from the API.
- Light footprint: Uses SQLite by default; no external infra required for dev.
- Product verticals (new): Auto-categorizes each ticket/message into one of 18 Nium product verticals using a rules-first keyword classifier. Results are stored and included in CSV exports. Deterministic rules supported for JIRA/Zendesk (project keys, labels/tags) to increase precision. Configure in `backend/nlp/product_verticals.py`.

**Overview**
- Backend: FastAPI service that syncs data sources, embeds + clusters tickets, builds themes, and exposes CSV exports.
- Frontend: Minimal React app to view themes, Top 10 lists, and export CSVs.
- Storage: SQLite by default (can switch to Postgres via `DATABASE_URL`).

**Architecture**
- Backend entry: `backend/main.py`
- Insights core: `backend/services/insights.py`
- Connectors: `backend/connectors/{slack,jira,zendesk}.py`
- Frontend app: `frontend/src/App.js`
- Product verticals: `backend/nlp/product_verticals.py` with seed taxonomy and classifier

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
- Themes (with filters): `GET /insights/themes/v2?days&k&source&kind&vertical`
- Top 10 (overview): `GET /insights/top10?days&k`
- Theme Suggestions: `GET /insights/theme_suggestions?days&k&top_n`
- Export CSVs: `GET /export/top10.csv?days&k&source&kind&vertical`, `GET /export/themes.csv?days&k&source&kind&vertical`
  - CSVs now include a `product_vertical` column per ticket where classified (confidence ≥ 0.65)
  - All insights endpoints accept `include_internal=false|true` (default false) to include/exclude internal Zendesk tickets.
 - Chat search: `POST /chat/query` with body `{ question, days, top_k, source, kind, vertical, include_internal }`
 - Internal audit (Zendesk): `GET /audit/zendesk_internal?days&limit`, CSV: `GET /audit/zendesk_internal.csv?days&limit`
 - Label analytics (Zendesk): `GET /analytics/zendesk/label_frequencies?days&include_internal&min_count&top`, CSV: `GET /export/zendesk/label_frequencies.csv?...`

Notes:
- `source` is one of `all|slack|zendesk|jira`
- `kind` is one of `all|issue|feature_request|unknown`

**Frontend UI**
- Controls for days, clusters (`k`), source and type filters; plus product vertical filter
- Toggle: "Include internal" checkbox (off by default) to focus on external/customer tickets.
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
  - Hit `GET /insights/theme_suggestions` (or add a simple UI call) to see prioritized PM suggestions with rationale.
- Export:
  - `Export Top 10 CSV` → columns: `rank,type,title,source,product_vertical,url`.
  - `Export Themes CSV` → columns: `theme_label,type,size,hint,ticket_id,ticket_title,ticket_source,product_vertical,ticket_url`.

**Syncing Data**
- Full sync: `POST /sync/run`
- Per‑source: `POST /sync/{zendesk|jira|slack}`
- Scheduler: configured via `SYNC_DAILY_CRON_HOUR` and `SYNC_DAILY_CRON_MINUTE`; enabled at app startup.

**Tips**
- Start small: lower `k` for broader themes; raise it for granularity.
- Filters recompute Top 10 based on filtered tickets in each theme.
- For Postgres, set `DATABASE_URL` and ensure the DB is reachable before running.
- Tuning verticals: Edit `backend/nlp/product_verticals.py` to refine keywords per vertical and add your actual JIRA project keys/labels and Zendesk tags per vertical. Classifier writes results to the `ticket_product_verticals` table.

**Maintenance**
- Backfill product verticals on all tickets or the last N days: `POST /maintenance/backfill_verticals` with optional `?days=N`.
 - Backfill Zendesk internal flags (`Ticket.is_internal`) using the current rules: `POST /maintenance/backfill_zendesk_internal` with optional `?days=N`.

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

**Zendesk Internal Classification**
- Insights endpoints accept `include_internal=false|true` (default false) to include or exclude internal Zendesk tickets in clustering and exports.
- Maintenance: `POST /maintenance/backfill_zendesk_internal?days=N` computes `Ticket.is_internal` for Zendesk tickets using configured rules.
- Env config:
  - `INTERNAL_EMAIL_DOMAINS`: comma-separated internal domains to exclude (e.g., `company.com,corp.company.com`).
  - `ZENDESK_ALLOWED_REQUESTER_ROLES`: requesters to include (default: `end-user`).
 - Notes: Classification relies on requester/submitter role and email domain, and sharing type (inbound shared tickets treated as internal). Tags no longer force internal.

**Environment extras**
- `EMBEDDING_DEVICE`: set to `cpu` (default) or `cuda` to select the device for sentence embeddings.
