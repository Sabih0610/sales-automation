# auth_setup.py — run this ONCE to authorize the sender account
import msal, os, webbrowser
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")

app = msal.ConfidentialClientApplication(
    client_id=CLIENT_ID,
    client_credential=CLIENT_SECRET,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
)

# Step 1: get the login URL
flow = app.initiate_auth_code_flow(
    scopes=["https://graph.microsoft.com/Mail.Send"],
    redirect_uri="http://localhost:8080",
    login_hint=SENDER_EMAIL,
)

print("=" * 60)
print("Opening browser for sign-in...")
print("Sign in with:", SENDER_EMAIL)
print("=" * 60)
webbrowser.open(flow["auth_uri"])

# Step 2: paste the redirect URL after sign-in
print("\nAfter signing in, your browser will redirect to localhost:8080")
print("Copy the FULL URL from the browser address bar and paste it here:")
redirect_response = input("\nPaste URL: ").strip()

# Step 3: complete the flow
result = app.acquire_token_by_auth_code_flow(flow, {"url": redirect_response})

if "access_token" in result:
    print("\n✓ Authorization successful!")
    print("The app is now authorized to send emails as:", SENDER_EMAIL)
    print("You do NOT need to do this again unless credentials change.")
else:
    print("\n✗ Authorization failed:", result.get("error_description"))