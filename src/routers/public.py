from fastapi import APIRouter

from src.api_helpers import *


router = APIRouter()


@router.get("/u/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str):
    payload = parse_token(token)
    if not payload:
        return HTMLResponse("<html><body><p>Invalid link</p></body></html>")
    email = html.escape(payload["email"])
    escaped_token = html.escape(token, quote=True)
    return HTMLResponse(
        "<html><body>"
        "<h1>Email preferences</h1>"
        f"<p>Click below to unsubscribe {email}.</p>"
        f'<form method="post" action="/u/{escaped_token}/confirm">'
        f"<button type=\"submit\">Unsubscribe {email}</button>"
        "</form>"
        "</body></html>"
    )

@router.post("/u/{token}/confirm", response_class=HTMLResponse)
def confirm_unsubscribe(token: str):
    payload = _apply_unsubscribe_token(token)
    if not payload:
        return HTMLResponse("<html><body><p>Invalid link</p></body></html>")
    return HTMLResponse(
        "<html><body><p>You have been unsubscribed.</p></body></html>"
    )

@router.post("/u/{token}/one-click")
def one_click_unsubscribe(token: str):
    _apply_unsubscribe_token(token)
    return Response(status_code=200)
