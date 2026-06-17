import asyncio
import sys

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import argparse
import json
import logging
import os
import sys

from src.runtime_paths import configure_runtime_environment


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _filters(args: argparse.Namespace) -> dict:
    return {
        "titles": _csv(args.titles),
        "industries": _csv(args.industries),
        "geos": _csv(args.geos),
        "company_sizes": [],
        "keywords": args.keywords,
        "start_url": args.start_url,
    }


def _find_resumable_run(filters: dict, run_repo, statuses) -> object | None:
    for run in run_repo.list_all():
        if run.filters != filters:
            continue
        if run.status not in statuses:
            continue
        checkpoint = run_repo.get_checkpoint(run.id)
        if checkpoint:
            print(
                "Resuming existing run "
                f"{run.id} from page {checkpoint['last_page']} "
                f"({checkpoint['leads_collected']} leads already collected)"
            )
            return run
    return None


def run_pipeline(args: argparse.Namespace) -> int:
    from src.agents.enrichment_agent import EnrichmentAgent
    from src.agents.export_agent import ExportAgent
    from src.agents.scraper_agent import ScraperAgent
    from src.agents.segment_agent import SegmentAgent
    from src.config import settings
    from src.models import AgentEvent, EventType, PipelineRun, RunStatus, datetime
    from src.storage import event_repo, lead_repo, run_repo

    settings.max_leads = args.max_leads
    filters = _filters(args)
    resumable_statuses = {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.FAILED}
    run = _find_resumable_run(filters, run_repo, resumable_statuses)
    if run is None:
        run = PipelineRun(filters=filters, enrichment_mode=settings.enrichment_mode)
    else:
        run.enrichment_mode = settings.enrichment_mode
        run.error = ""
        run.completed_at = None

    def persist_event(event: AgentEvent) -> None:
        event_repo.save(event)
        run_repo.save(run)

    def wire(agent):
        agent.on_event(persist_event)
        return agent

    run.status = RunStatus.RUNNING
    run_repo.save(run)
    event_repo.save(AgentEvent(EventType.PIPELINE_STARTED, "CLI", run.id))

    try:
        leads = wire(ScraperAgent(run, filters)).execute()
        lead_repo.save_batch(run.id, leads)
        run_repo.save(run)

        leads = wire(EnrichmentAgent(run, leads)).execute()
        lead_repo.save_batch(run.id, leads)
        run_repo.save(run)

        leads = wire(SegmentAgent(run, leads)).execute()
        lead_repo.save_batch(run.id, leads)
        run_repo.save(run)

        output_files = wire(ExportAgent(run, leads)).execute()
        lead_repo.save_batch(run.id, leads)

        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.utcnow()
        run_repo.save(run)
        event_repo.save(
            AgentEvent(
                EventType.PIPELINE_COMPLETED,
                "CLI",
                run.id,
                payload={"files": output_files, **run.summary()},
            )
        )

        print(json.dumps({"files": output_files, **run.summary()}, indent=2, default=str))
        return 0
    except KeyboardInterrupt:
        run.status = RunStatus.FAILED
        run.error = "Interrupted by user"
        run.completed_at = datetime.utcnow()
        run_repo.save(run)
        event_repo.save(
            AgentEvent(EventType.PIPELINE_FAILED, "CLI", run.id, error=run.error)
        )
        print("\nPipeline interrupted. Checkpoint saved for resume.")
        print(json.dumps(run.summary(), indent=2, default=str))
        return 130
    except Exception as exc:
        run.status = RunStatus.FAILED
        run.error = str(exc)
        run.completed_at = datetime.utcnow()
        run_repo.save(run)
        event_repo.save(AgentEvent(EventType.PIPELINE_FAILED, "CLI", run.id, error=str(exc)))
        print(json.dumps(run.summary(), indent=2, default=str))
        return 1


def serve_api(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("src.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def show_status(_args: argparse.Namespace) -> int:
    from src.storage import run_repo

    runs = run_repo.list_all()
    if not runs:
        print(json.dumps({"status": "idle"}, indent=2))
        return 0
    print(json.dumps(runs[0].summary(), indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Royal Cyber lead pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run the pipeline synchronously")
    run.add_argument("--titles", default="CTO,CIO,Head of Data")
    run.add_argument("--industries", default="")
    run.add_argument("--geos", default="")
    run.add_argument("--keywords", default="Microsoft Fabric")
    run.add_argument(
        "--url",
        dest="start_url",
        default="",
        help="URL to scrape (any search results page)",
    )
    run.add_argument("--max", dest="max_leads", type=int, default=1000)
    run.set_defaults(func=run_pipeline)

    serve = subparsers.add_parser("serve", help="Start the FastAPI server")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=serve_api)

    status = subparsers.add_parser("status", help="Print the last run from SQLite")
    status.set_defaults(func=show_status)

    return parser


def main() -> int:
    runtime_paths = configure_runtime_environment()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if runtime_paths.use_app_data or os.getenv("LOG_DIR", "").strip():
        runtime_paths.log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.FileHandler(
                runtime_paths.log_dir / "backend.log",
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
