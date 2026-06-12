import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.send_policy import SendPolicy, next_send_delay_seconds
from src.storage import send_log_repo


TEST_LEAD_PREFIX = "__manual_send_policy_test__"
TEST_CAMPAIGN = "__manual_policy_campaign__"
TEST_DOMAIN = "manual-policy-test.invalid"


def cleanup():
    send_log_repo.delete_for_lead_prefix(TEST_LEAD_PREFIX)


cleanup()

# Make the policy test deterministic and not dependent on current time.
os.environ["SEND_WINDOW_START"] = "00:00"
os.environ["SEND_WINDOW_END"] = "23:59"
os.environ["SKIP_WEEKENDS"] = "false"
os.environ["SEND_RAMP_OVERRIDE"] = "9999"
os.environ["PER_DOMAIN_DAILY_CAP"] = "4"
os.environ["SEND_JITTER_MIN"] = "1"
os.environ["SEND_JITTER_MAX"] = "2"

policy = SendPolicy()

status = policy.status()
print("Status:", status)

assert status["todays_cap"] == 9999
assert status["per_domain_cap"] == 4
assert status["window"]["open_now"] is True

allowed, reason = policy.check(f"first@{TEST_DOMAIN}")
print("Before domain cap:", allowed, reason)
assert allowed is True

for i in range(4):
    send_log_repo.record(
        f"{TEST_LEAD_PREFIX}{i}",
        TEST_CAMPAIGN,
        f"person{i}@{TEST_DOMAIN}",
        1,
    )

allowed, reason = policy.check(f"person5@{TEST_DOMAIN}")
print("After domain cap:", allowed, reason)
assert allowed is False
assert reason == f"Per-domain cap for {TEST_DOMAIN}"

# Free providers are exempt from per-domain cap.
for i in range(6):
    send_log_repo.record(
        f"{TEST_LEAD_PREFIX}_gmail_{i}",
        TEST_CAMPAIGN,
        f"free{i}@gmail.com",
        1,
    )

allowed, reason = policy.check("another@gmail.com")
print("Free provider check:", allowed, reason)
assert allowed is True

# Daily cap test.
current_sent = send_log_repo.count_today()
os.environ["SEND_RAMP_OVERRIDE"] = str(current_sent)

policy = SendPolicy()
allowed, reason = policy.check("daily-cap@example-cap-test.invalid")
print("Daily cap check:", allowed, reason)
assert allowed is False
assert reason.startswith("Daily cap reached")

delay = next_send_delay_seconds()
print("Delay:", delay)
assert 1 <= delay <= 2

cleanup()

print("OK - send policy works")
