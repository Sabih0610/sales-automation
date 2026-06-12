import secrets
from pathlib import Path

env_path = Path(".env")
lines = []

if env_path.exists():
    lines = env_path.read_text(encoding="utf-8").splitlines()

existing = {}
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        key, _, value = line.partition("=")
        existing[key.strip()] = value.strip()

api_key = existing.get("DASHBOARD_API_KEY") or secrets.token_urlsafe(32)

existing["DASHBOARD_API_KEY"] = api_key

if "CORS_ALLOWED_ORIGINS" not in existing:
    existing["CORS_ALLOWED_ORIGINS"] = (
        "http://localhost:3000,"
        "http://localhost:5173,"
        "http://127.0.0.1:3000,"
        "http://127.0.0.1:5173"
    )

env_path.write_text(
    "\n".join(f"{key}={value}" for key, value in existing.items()) + "\n",
    encoding="utf-8",
)

print("DASHBOARD_API_KEY saved:")
print(api_key)
print("CORS_ALLOWED_ORIGINS saved")