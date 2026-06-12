import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(override=True)


def close_db_connection(job_repo) -> None:
    conn = getattr(job_repo.db._local, "conn", None)
    if conn:
        conn.close()
        job_repo.db._local.conn = None


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DB_PATH"] = os.path.join(tmp, "phase1_jobs_repo.sqlite")

        from src.storage import job_repo

        try:
            created = job_repo.create(
                "phase1_repo_test",
                {"draft_ids": ["draft-1", "draft-2"]},
                total=2,
            )
            assert created["status"] == "queued"
            assert created["payload"]["draft_ids"] == ["draft-1", "draft-2"]

            loaded = job_repo.get(created["id"])
            assert loaded is not None
            assert loaded["total"] == 2

            job_repo.mark_running(created["id"])
            running = job_repo.get(created["id"])
            assert running["status"] == "running"

            job_repo.update_progress(
                created["id"],
                done_delta=1,
                skipped_delta=1,
                result_item={"draft_id": "draft-1", "status": "skipped"},
            )
            progressed = job_repo.get(created["id"])
            assert progressed["done"] == 1
            assert progressed["skipped"] == 1
            assert progressed["result"]["items"][0]["draft_id"] == "draft-1"

            job_repo.request_cancel(created["id"])
            cancelled = job_repo.get(created["id"])
            assert cancelled["cancel_requested"] is True

            done_job = job_repo.create("phase1_done_test", {}, total=0)
            job_repo.mark_running(done_job["id"])
            job_repo.mark_done(done_job["id"])
            assert job_repo.get(done_job["id"])["status"] == "done"

            failed_job = job_repo.create("phase1_failed_test", {}, total=0)
            job_repo.mark_running(failed_job["id"])
            job_repo.mark_failed(failed_job["id"], "expected failure")
            failed = job_repo.get(failed_job["id"])
            assert failed["status"] == "failed"
            assert failed["error"] == "expected failure"

            job_repo.delete_many([
                created["id"],
                done_job["id"],
                failed_job["id"],
            ])
        finally:
            close_db_connection(job_repo)

    print("OK - jobs repo works")


if __name__ == "__main__":
    main()
