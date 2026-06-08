import os, sys
import msal
import requests
from dotenv import load_dotenv

load_dotenv()

TENANT_ID     = os.getenv("AZURE_TENANT_ID", "")
CLIENT_ID     = os.getenv("AZURE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
SENDER_EMAIL  = os.getenv("SENDER_EMAIL", "")
TEST_RECIPIENT = "sabih.aamir001@gmail.com"

print("=" * 60)
print("RC Sales Automation — Microsoft Graph Email Test")
print("=" * 60)
print(f"Tenant ID  : {TENANT_ID[:8]}...")
print(f"Client ID  : {CLIENT_ID[:8]}...")
print(f"Secret     : {'SET' if CLIENT_SECRET else 'MISSING'}")
print(f"Sender     : {SENDER_EMAIL}")
print(f"Recipient  : {TEST_RECIPIENT}")
print("=" * 60)

# Step 1: Check all values present
missing = []
if not TENANT_ID:    missing.append("AZURE_TENANT_ID")
if not CLIENT_ID:    missing.append("AZURE_CLIENT_ID")
if not CLIENT_SECRET: missing.append("AZURE_CLIENT_SECRET")
if not SENDER_EMAIL or SENDER_EMAIL == "your.email@royalcyber.com":
    missing.append("SENDER_EMAIL (still placeholder)")

if missing:
    print(f"\n✗ Missing in .env: {', '.join(missing)}")
    sys.exit(1)

print("\nStep 1: Credentials check ... OK")

# Step 2: Get access token
print("Step 2: Getting access token from Azure AD...")
try:
    app = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        print(f"\n✗ Token failed: {result.get('error_description')}")
        print(f"  Error code: {result.get('error')}")
        print("\n  Most likely cause: Mail.Send is still Delegated permission.")
        print("  Ask IT NOC to change it to Application permission + admin consent.")
        sys.exit(1)
    token = result["access_token"]
    print(f"  Token obtained. Expires in {result.get('expires_in')} seconds.")
    print("Step 2: Token ... OK")
except Exception as e:
    print(f"\n✗ Token error: {e}")
    sys.exit(1)

# Step 3: Send test email
print(f"\nStep 3: Sending test email to {TEST_RECIPIENT}...")
try:
    response = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "message": {
                "subject": "RC Sales Automation — Test Email",
                "body": {
                    "contentType": "Text",
                    "content": (
                        "This is a test email from the RC Sales Automation platform.\n\n"
                        "If you received this, Microsoft Graph API is working correctly.\n\n"
                        "Sent from: " + SENDER_EMAIL + "\n"
                        "Platform: Royal Cyber Sales Automation\n"
                        "API: Microsoft Graph v1.0\n"
                    ),
                },
                "toRecipients": [
                    {"emailAddress": {"address": TEST_RECIPIENT}}
                ],
            },
            "saveToSentItems": True,
        },
        timeout=15,
    )

    print(f"  HTTP Status: {response.status_code}")

    if response.status_code == 202:
        print("\n" + "=" * 60)
        print("✓ SUCCESS — Email sent!")
        print(f"  Check {TEST_RECIPIENT} inbox.")
        print(f"  Also check {SENDER_EMAIL} Sent folder in Outlook.")
        print("=" * 60)
    elif response.status_code == 403:
        print("\n✗ FORBIDDEN (403)")
        print("  Mail.Send permission is still Delegated, not Application.")
        print("  Tell IT NOC: change Mail.Send to Application permission")
        print("  and grant admin consent.")
        print(f"\n  Graph error: {response.text[:300]}")
    elif response.status_code == 401:
        print("\n✗ UNAUTHORIZED (401)")
        print("  Token was obtained but rejected by Graph API.")
        print("  Check that admin consent was granted for the app.")
        print(f"\n  Graph error: {response.text[:300]}")
    elif response.status_code == 404:
        print("\n✗ NOT FOUND (404)")
        print(f"  Mailbox not found: {SENDER_EMAIL}")
        print("  Check SENDER_EMAIL is a real Royal Cyber Outlook mailbox.")
        print(f"\n  Graph error: {response.text[:300]}")
    else:
        print(f"\n✗ Unexpected status: {response.status_code}")
        print(f"  Response: {response.text[:300]}")

except Exception as e:
    print(f"\n✗ Request error: {e}")
