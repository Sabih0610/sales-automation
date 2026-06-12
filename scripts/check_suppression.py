import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage import suppression_repo

emails = [f"person{i}@example.com" for i in range(1200)]

suppression_repo.add("person5@example.com", "manual")
suppression_repo.add("person999@example.com", "manual")

found = suppression_repo.bulk_check(emails)

print("Suppressed found:", found)

assert "person5@example.com" in found
assert "person999@example.com" in found
assert "person7@example.com" not in found

print("OK - suppression bulk_check works")