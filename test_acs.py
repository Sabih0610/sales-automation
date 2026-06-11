import os
from azure.communication.email import EmailClient
from dotenv import load_dotenv

load_dotenv()

client = EmailClient.from_connection_string(os.getenv("ACS_CONNECTION_STRING"))

message = {
    "senderAddress": os.getenv("ACS_SENDER_EMAIL"),
    "recipients": {
        "to": [{"address": "sabih.aamir@royalcyber.com", "displayName": "Sabih Test"}]
    },
    "content": {
        "subject": "ACS Test - RC Sales Automation",
        "plainText": "This email was sent via Azure Communication Services. If you see this in inbox (not spam) — ACS is working correctly.",
    },
    "replyTo": [{"address": os.getenv("ACS_REPLY_TO_EMAIL")}],
}

poller = client.begin_send(message)
result = poller.result()
print("Status:", result["status"])
print("Message ID:", result["id"])