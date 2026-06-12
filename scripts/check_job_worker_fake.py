import os
import sys
import tempfile
import time
from pathlib import Path
import logging

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


def wait_for(job_repo, job_id: str, statuses: set[str], timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = job_repo.get(job_id)
        if job and job["status"] in statuses:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {job_id} to reach {statuses}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DB_PATH"] = os.path.join(tmp, "phase1_job_worker.sqlite")

        from src.job_worker import (
            JobWorker,
            register_job_handler,
            unregister_job_handler,
        )
        from src.storage import job_repo

        logging.getLogger("src.job_worker").setLevel(logging.CRITICAL)

        def fake_success(job: dict, stop_event) -> None:
            for index in range(3):
                assert not stop_event.is_set()
                job_repo.update_progress(
                    job["id"],
                    done_delta=1,
                    result_item={
                        "lead_id": f"lead-{index}",
                        "status": "processed",
                    },
                )

        def fake_failure(job: dict, stop_event) -> None:
            assert not stop_event.is_set()
            job_repo.update_progress(
                job["id"],
                done_delta=1,
                failed_delta=1,
                result_item={"lead_id": "lead-failed", "status": "failed"},
            )
            raise RuntimeError("fake worker failure")

        register_job_handler("phase1_fake_success", fake_success)
        register_job_handler("phase1_fake_failure", fake_failure)

        worker = JobWorker(poll_interval_seconds=0.05)
        try:
            success_job = job_repo.create("phase1_fake_success", {}, total=3)
            failed_job = job_repo.create("phase1_fake_failure", {}, total=2)

            worker.start()

            success = wait_for(job_repo, success_job["id"], {"done"})
            assert success["done"] == 3
            assert len(success["result"]["items"]) == 3

            failed = wait_for(job_repo, failed_job["id"], {"failed"})
            assert failed["done"] == 1
            assert failed["failed"] == 1
            assert "fake worker failure" in failed["error"]
        finally:
            worker.stop()
            unregister_job_handler("phase1_fake_success")
            unregister_job_handler("phase1_fake_failure")
            close_db_connection(job_repo)

    print("OK - fake job worker checks passed")


if __name__ == "__main__":
    main()
