import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage import send_log_repo

TEST_LEAD_ID = "__manual_send_log_test__"
TEST_CAMPAIGN = "__manual_test_campaign__"
TEST_EMAIL = "Manual.Test@Example.com"

before_total = send_log_repo.count_today()
before_domain = send_log_repo.count_today_for_domain("example.com")

send_log_repo.record(
    TEST_LEAD_ID,
    TEST_CAMPAIGN,
    TEST_EMAIL,
    1,
)

after_total = send_log_repo.count_today()
after_domain = send_log_repo.count_today_for_domain("example.com")
first_date = send_log_repo.first_send_date()

print("Before total:", before_total)
print("After total:", after_total)
print("Before example.com:", before_domain)
print("After example.com:", after_domain)
print("First send date:", first_date)

assert after_total >= before_total + 1
assert after_domain >= before_domain + 1
assert first_date is not None

send_log_repo.delete_for_lead(TEST_LEAD_ID)

print("OK - send_log_repo works")
