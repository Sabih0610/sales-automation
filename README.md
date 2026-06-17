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

## Desktop Wrapper

The Electron wrapper can run in two modes:

- Development desktop mode loads the Vite dashboard at `http://127.0.0.1:5173`.
- Production desktop mode loads the built files from `dashboard/dist/index.html`.

In both modes, Electron starts the local FastAPI backend automatically if
`http://127.0.0.1:8000/api/health` is not already responding. If a backend is
already running on port `8000`, Electron reuses it and leaves it running when
the desktop app closes. If Electron starts the backend, it stops only that
backend process when the desktop app closes. Backend output is written to
`desktop/logs/backend.log` in development desktop mode and to
`%LOCALAPPDATA%\RoyalCyberLeadPipeline\logs\backend.log` in production
desktop mode.

Production desktop mode starts the packaged backend executable at
`dist/royal-cyber-backend/royal-cyber-backend.exe`. Development desktop mode
keeps using `python main.py serve`.

Start the backend manually only if you want to run it outside Electron:

```bash
python main.py serve
```

### Build Backend Exe

Install build-only packaging dependencies:

```bash
python -m pip install -r requirements-build.txt
```

Build the backend executable:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_backend_exe.ps1
```

Or from the desktop package:

```bash
cd desktop
npm run build:backend
```

The output is:

```text
dist/royal-cyber-backend/royal-cyber-backend.exe
```

The build includes backend code plus `migrations/`, `knowledge_base/`,
`campaigns/`, and `.env.example`. Real `.env` files are not bundled. In
production desktop mode the backend reads user configuration from app-data
`.env` when present, then falls back to a local project `.env` during
development.

Chrome/Sales Navigator scraping continues to use installed Google Chrome or the
configured `CHROME_PATH`; this build does not bundle a browser.

### Development Desktop Mode

Start the dashboard in one terminal:

```bash
cd dashboard
npm run dev
```

Start Electron in another terminal:

```bash
cd desktop
npm install
npm run dev
```

Development desktop mode still uses Vite for fast frontend iteration.

### Production Desktop Mode

Build the dashboard:

```bash
cd dashboard
npm run build
```

Run Electron against the built dashboard files:

```bash
cd desktop
npm install
npm start
```

You can also build the dashboard from the desktop package:

```bash
cd desktop
npm run build:dashboard
npm start
```

Or build and launch in one step:

```bash
cd desktop
npm run prod
```

Production desktop mode does not require the Vite dev server. The built
dashboard uses `http://127.0.0.1:8000` for API requests and
`ws://127.0.0.1:8000` for WebSocket updates. Build the backend executable before
running production desktop mode. To point development desktop mode at a
different dashboard URL, set `RCLP_DASHBOARD_URL` before running `npm run dev`.

### Desktop App Data

Production desktop mode stores runtime data outside the app folder at:

```text
%LOCALAPPDATA%\RoyalCyberLeadPipeline\
```

Electron passes these backend paths in production desktop mode:

```text
APP_DATA_DIR=%LOCALAPPDATA%\RoyalCyberLeadPipeline
DB_PATH=%LOCALAPPDATA%\RoyalCyberLeadPipeline\pipeline.db
OUTPUT_DIR=%LOCALAPPDATA%\RoyalCyberLeadPipeline\output
LOG_DIR=%LOCALAPPDATA%\RoyalCyberLeadPipeline\logs
CHROME_PROFILE_DIR=%LOCALAPPDATA%\RoyalCyberLeadPipeline\chrome-scraper-profile
DEBUG_DIR=%LOCALAPPDATA%\RoyalCyberLeadPipeline\debug
KNOWLEDGE_BASE_DIR=%LOCALAPPDATA%\RoyalCyberLeadPipeline\knowledge_base
```

The app-data folder may also contain a user `.env` file and uploaded knowledge
base files. If the app-data database does not exist and a project-root
`pipeline.db` exists, the backend copies it once into app-data and never
overwrites an existing app-data database.

To back up desktop data, stop the desktop app and copy `pipeline.db*` plus the
`output\` folder from `%LOCALAPPDATA%\RoyalCyberLeadPipeline\`. To reset local
desktop data, stop the app and delete `%LOCALAPPDATA%\RoyalCyberLeadPipeline\`.
Only do this if you no longer need the local database, exports, logs, Chrome
scraper login profile, or app-data `.env`.

## Scraping Notes

The scraper supports two flows:

1. LinkedIn Sales Navigator DOM scraping.
2. Generic website/business-directory scraping by copying page text and using OpenAI extraction.

Do not restrict runs to LinkedIn URLs only. Generic URLs are intentionally supported.

For Chrome/CDP scraping, the app looks for Chrome automatically. If Chrome is installed somewhere unusual, set:

```text
CHROME_PATH=C:\Path\To\chrome.exe
```

When a run opens Chrome, sign in or complete CAPTCHA manually if needed. In
development the scraper keeps using a separate local Chrome profile named
`chrome-scraper-profile` under your user folder. In production desktop mode the
profile is stored in
`%LOCALAPPDATA%\RoyalCyberLeadPipeline\chrome-scraper-profile`.

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
- `APP_DATA_DIR`: optional desktop app-data root override.
- `LOG_DIR`: backend log directory.
- `CHROME_PROFILE_DIR`: Chrome scraper profile directory.
- `DEBUG_DIR`: scraper/debug artifact directory.
- `KNOWLEDGE_BASE_DIR`: uploaded knowledge base file directory.
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

The app uses local SQLite. In development the default database is:

```text
pipeline.db
```

In production desktop mode the default database is:

```text
%LOCALAPPDATA%\RoyalCyberLeadPipeline\pipeline.db
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

In development exports default to `output\`. In production desktop mode they
default to `%LOCALAPPDATA%\RoyalCyberLeadPipeline\output\`.

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
|-- desktop/
|   |-- main.js
|   |-- package.json
|   `-- scripts/
|-- migrations/
|-- scripts/
|-- main.py
|-- requirements.txt
|-- .env.example
`-- README.md
```


## Production Deployment Checklist

Before deploying:

1. Set production mode:

```text
APP_ENV=production
```

2. Set a strong backend API key:

```text
DASHBOARD_API_KEY=<long-random-secret>
```

3. Set the same frontend key in `dashboard/.env`:

```text
VITE_API_KEY=<same-long-random-secret>
```

4. Set exact allowed dashboard origins. Do not use `*` in production:

```text
CORS_ALLOWED_ORIGINS=https://your-dashboard-domain.com
```

5. Set public URL for unsubscribe links:

```text
PUBLIC_BASE_URL=https://your-api-domain.com
```

6. Configure Microsoft Graph only when email sending is needed:

```text
AZURE_TENANT_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
SENDER_EMAIL=
```

7. Keep scheduler enabled for automatic scheduled sending:

```text
SCHEDULER_ENABLED=true
```

8. Enable reply monitor only after Graph mailbox permissions are ready:

```text
REPLY_MONITOR_ENABLED=true
```

9. Run final backend checks:

```bash
python -m py_compile src/api.py src/storage.py src/api_helpers.py src/routers/campaigns.py
python -c "from src.api import app; print('api app ok')"
```

10. Run final dashboard build:

```bash
cd dashboard
npm run build
```

## Database Backup

Create a safe SQLite backup while the app is stopped or running:

```bash
python scripts/backup_sqlite.py
```

By default, backups are written to:

```text
./backups
```

You can change this with:

```text
DB_BACKUP_DIR=./backups
```

SQLite production settings:

```text
SQLITE_TIMEOUT_SECONDS=30
```

The app enables WAL mode, normal synchronous mode, foreign keys, and busy timeout on SQLite connections.
