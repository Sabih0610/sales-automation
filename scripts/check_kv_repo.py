import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage import kv_repo

kv_repo.set("manual_test_key", "hello")
value = kv_repo.get("manual_test_key")

print("Value:", value)

assert value == "hello"

deleted = kv_repo.delete("manual_test_key")
assert deleted is True

value_after_delete = kv_repo.get("manual_test_key")
assert value_after_delete == ""

print("OK - kv_repo works")