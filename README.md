# Royal Cyber Lead Pipeline

Royal Cyber Lead Pipeline is a local Python and React application for collecting leads from LinkedIn Sales Navigator or generic business-directory/search pages, segmenting prospects, preparing outreach drafts, tracking campaign activity, and exporting lead files.

The backend is FastAPI with a local SQLite database. The dashboard is a Vite/React app.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- Google Chrome or Chromium
- A LinkedIn/Sales Navigator account if scraping Sales Navigator
- An OpenAI API key for generic website/business-directory extraction and AI draft generation
- Optional: Microsoft Azure app credentials for Microsoft Graph email sending
- Optional: ZoomInfo API credentials for ZoomInfo enrichment

## Quick Start

From the project root:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

Install dashboard dependencies and create its env file:

```bash
cd dashboard
npm install
copy .env.example .env
cd ..
```

Create a dashboard/API key and put the same value in both env files:

```text
.env
DASHBOARD_API_KEY=change-this-to-a-long-random-value

dashboard/.env
VITE_API_KEY=change-this-to-a-long-random-value
```

Set any required service keys in `.env`, especially:

```text
OPENAI_API_KEY=...
```

## Run The App

Start the API from the project root:

```bash
python main.py serve --reload
```

Start the dashboard in another terminal:

```bash
cd dashboard
npm run dev
```

Open the Vite URL shown in the terminal, usually:

```text
http://127.0.0.1:5173
```

The API runs on `http://localhost:8000` by default.

## Scraping Notes

The scraper supports two flows:

1. LinkedIn Sales Navigator DOM scraping.
2. Generic website/business-directory scraping by copying page text and using OpenAI extraction.

Do not restrict runs to LinkedIn URLs only. Generic URLs are intentionally supported.

For Chrome/CDP scraping, the app looks for Chrome automatically. If Chrome is installed somewhere unusual, set:

```text
CHROME_PATH=C:\Path\To\chrome.exe
```

When a run opens Chrome, sign in or complete CAPTCHA manually if needed. The scraper uses a separate local Chrome profile directory named `chrome-scraper-profile`.

## CLI Usage

Run the pipeline directly:

```bash
python main.py run --url "https://example.com/directory" --max 100
```

Example with filters:

```bash
python main.py run --titles "CTO,CIO,Head of Data" --industries "Computer Software" --geos "United States" --keywords "Microsoft Fabric" --max 1000
```

Check the last saved run:

```bash
python main.py status
```

## Environment Files

Backend settings live in `.env`:

- `DASHBOARD_API_KEY`: required for dashboard/API access. Must match `dashboard/.env` `VITE_API_KEY`.
- `CORS_ALLOWED_ORIGINS`: allowed dashboard origins, usually `http://localhost:5173,http://127.0.0.1:5173`.
- `OPENAI_API_KEY`: required for OpenAI-powered extraction and draft generation.
- `CHROME_PATH`: optional explicit Chrome executable path.
- `OUTPUT_FORMAT`: `xlsx` or `csv`.
- `OUTPUT_DIR`: export directory.
- `DB_PATH`: local SQLite database path.
- `ZOOMINFO_*`: optional ZoomInfo credentials.
- `AZURE_*` and `SENDER_EMAIL`: optional Microsoft Graph sending credentials.
- `REPLY_MONITOR_ENABLED`: set `true` only after Microsoft Graph is configured.
- `SCHEDULER_ENABLED`: set `false` to disable the background scheduler in development.

Dashboard settings live in `dashboard/.env`:

- `VITE_API_KEY`: same value as backend `DASHBOARD_API_KEY`.
- `VITE_API_BASE`: optional API base URL override. Leave blank for local default.
- `VITE_WS_BASE`: optional WebSocket base URL override. Leave blank for local default.

Never commit real `.env` files. They are ignored by Git.

## Database And Migrations

The app uses local SQLite. By default the database is:

```text
pipeline.db
```

Migrations live in `migrations/` and are applied automatically when `src/storage.py` opens the database.

To reset local state during development, stop the app and remove `pipeline.db`, `pipeline.db-shm`, and `pipeline.db-wal`. Do not delete these files if you need the existing runs/leads.

## Campaign Data

Campaigns, lead universes, sequences, drafts, send logs, and run history are stored in SQLite. Old JSON campaign seed files are deprecated and imported only once when present.

New campaigns should be created through the dashboard/API.

## Enrichment Modes

| Mode | `.env` setting | Behavior |
| --- | --- | --- |
| FREE | `ZOOMINFO_ENABLED=false` | Uses domain/email inference and SMTP checks where available. |
| ZOOMINFO | `ZOOMINFO_ENABLED=true` plus `ZOOMINFO_CLIENT_ID` and `ZOOMINFO_PRIVATE_KEY` | Uses ZoomInfo credentials for enrichment. |

## Email Sending

Microsoft Graph email sending requires:

```text
AZURE_TENANT_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
SENDER_EMAIL=
```

Leave these blank if you only want scraping, segmentation, draft review, and exports.

## Output Files

When `OUTPUT_FORMAT=xlsx`, exports one workbook named `leads_<timestamp>.xlsx` with `Warm`, `Cold`, and `No_Email` sheets.

When `OUTPUT_FORMAT=csv`, exports three files:

- `leads_warm_<timestamp>.csv`
- `leads_cold_<timestamp>.csv`
- `leads_no_email_<timestamp>.csv`

Generated output, logs, local databases, debug files, virtual environments, and `node_modules` are ignored by Git.

## Useful Checks

Backend syntax/import check:

```bash
python -m py_compile src/orchestrator.py src/agents/base.py src/agents/scraper_agent.py src/api.py
python -c "from src.api import app; print('api app ok')"
```

Dashboard build:

```bash
cd dashboard
npm run build
```

## Project Structure

```text
sales automation/
|-- src/
|   |-- agents/
|   |-- personalisation/
|   |-- routers/
|   |-- api.py
|   |-- config.py
|   |-- models.py
|   |-- orchestrator.py
|   `-- storage.py
|-- dashboard/
|   |-- src/
|   |-- package.json
|   `-- vite.config.js
|-- migrations/
|-- scripts/
|-- main.py
|-- requirements.txt
|-- .env.example
`-- README.md
```
