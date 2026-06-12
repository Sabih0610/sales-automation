import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(override=True)
os.environ["DASHBOARD_API_KEY"] = "phase1-final-api-key"
os.environ["UNSUBSCRIBE_SECRET"] = "phase1-final-unsubscribe-secret"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"


def close_db_connection() -> None:
    from src.storage import db

    conn = getattr(db._local, "conn", None)
    if conn:
        conn.close()
        db._local.conn = None


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        os.environ["DB_PATH"] = os.path.join(tmp, "phase1_final.sqlite")

        try:
            from src.api import app, inbox_monitor_status, send_policy_status

            assert callable(send_policy_status)
            assert callable(inbox_monitor_status)

            with TestClient(app) as client:
                assert client.get("/api/health").status_code == 200
                assert client.get("/api/send-policy/status").status_code == 401
                assert client.get(
                    "/api/send-policy/status",
                    headers={"x-api-key": "phase1-final-api-key"},
                ).status_code == 200

                assert client.get("/api/jobs").status_code == 401
                assert client.get(
                    "/api/jobs",
                    headers={"x-api-key": "phase1-final-api-key"},
                ).status_code == 200
        finally:
            close_db_connection()

    print("OK - Phase 1 static checks passed")


if __name__ == "__main__":
    main()
