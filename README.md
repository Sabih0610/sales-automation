# Royal Cyber Lead Pipeline

Royal Cyber Lead Pipeline is a Python and React workflow for sourcing leads from LinkedIn Sales Navigator, enriching them through either free lookup plus SMTP checks or ZoomInfo, segmenting warm and cold prospects, exporting lead files, and monitoring runs from a small dashboard.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill `LI_AT_COOKIE` in `.env` before running the scraper.

## Get The `li_at` Cookie

1. Sign in to LinkedIn or Sales Navigator in your browser.
2. Open Developer Tools, then go to Application or Storage, Cookies, `.linkedin.com`.
3. Copy the value of the `li_at` cookie into `.env`.

Use an account you own and follow your organization's policies and LinkedIn's terms.

## Run CLI

```bash
python main.py run --max 100
```

Example with filters:

```bash
python main.py run --titles "CTO,CIO,Head of Data" --industries "Computer Software" --geos "United States" --keywords "Microsoft Fabric" --max 1000
```

Check the last saved run:

```bash
python main.py status
```

## Run With Dashboard

Start the API:

```bash
python main.py serve
```

Start the dashboard in another terminal:

```bash
cd dashboard
npm run dev
```

Open the Vite URL shown in the terminal, usually `http://127.0.0.1:5173`.

## Enrichment Modes

| Mode | `.env` setting | Behavior |
| --- | --- | --- |
| FREE | `ZOOMINFO_ENABLED=false` | Uses Clearbit autocomplete to infer company domains, then generates email patterns and checks SMTP. |
| ZOOMINFO | `ZOOMINFO_ENABLED=true` plus `ZOOMINFO_CLIENT_ID` and `ZOOMINFO_PRIVATE_KEY` | Uses ZoomInfo contact search and company enrichment for email, phone, domain, and intent score. |

## Output Files

When `OUTPUT_FORMAT=xlsx`, exports one workbook named `leads_<timestamp>.xlsx` with `Warm`, `Cold`, and `No_Email` sheets. When `OUTPUT_FORMAT=csv`, exports three files: `leads_warm_<timestamp>.csv`, `leads_cold_<timestamp>.csv`, and `leads_no_email_<timestamp>.csv`.

## Project Structure

```text
lead_pipeline/
|-- src/
|   |-- __init__.py
|   |-- models.py
|   |-- config.py
|   |-- storage.py
|   |-- orchestrator.py
|   |-- api.py
|   `-- agents/
|       |-- __init__.py
|       |-- base.py
|       |-- scraper_agent.py
|       |-- enrichment_agent.py
|       |-- segment_agent.py
|       `-- export_agent.py
|-- dashboard/
|-- output/
|-- main.py
|-- requirements.txt
|-- .env.example
|-- pyproject.toml
`-- README.md
```
