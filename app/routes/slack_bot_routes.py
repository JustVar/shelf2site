"""Notification Channels admin page — Slack bot + email/SMTP config, tests."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import require_system_admin
from ..config import settings
from ..localtime import register
from ..database import get_db
from ..models import User
from ..notifications import lookup_slack_user_by_email, send_email, send_slack_dm
from sqlalchemy.orm import Session

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


@router.get("/admin/slack-bot", response_class=RedirectResponse)
def slack_bot_redirect():
    """Backward-compat redirect — old URL → unified notifications page."""
    return RedirectResponse(url=f"{BP}/admin/notifications", status_code=301)


@router.get("/admin/notifications", response_class=HTMLResponse)
def notifications_admin_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Unified notification channels configuration page (Slack bot + SMTP email)."""
    bot_configured = bool(settings.SLACK_BOT_TOKEN)
    webhook_configured = bool(settings.SLACK_WEBHOOK_URL)
    test_webhook_configured = bool(settings.SLACK_TEST_WEBHOOK_URL)
    smtp_configured = bool(settings.SMTP_HOST)
    smtp_auth_configured = bool(settings.SMTP_USER and settings.SMTP_PASSWORD)

    return templates.TemplateResponse(request, "admin_notifications.html", {
        "request": request,
        "user": user,
        "bot_configured": bot_configured,
        "webhook_configured": webhook_configured,
        "test_webhook_configured": test_webhook_configured,
        "smtp_configured": smtp_configured,
        "smtp_auth_configured": smtp_auth_configured,
        "smtp_host": settings.SMTP_HOST or "",
        "smtp_port": settings.SMTP_PORT,
        "user_email": user.email or "",
        "user_slack_id": user.slack_user_id or "",
    })


@router.post("/api/slack-bot/test")
async def test_slack_bot(
    request: Request,
    user: User = Depends(require_system_admin),
):
    """Test the Slack bot token by calling auth.test."""
    if not settings.SLACK_BOT_TOKEN:
        return JSONResponse(status_code=400, content={"error": "SLACK_BOT_TOKEN is not configured in .env"})

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            )
            data = resp.json()
            if data.get("ok"):
                return JSONResponse(content={
                    "status": "ok",
                    "bot_name": data.get("user", "unknown"),
                    "team": data.get("team", "unknown"),
                })
            return JSONResponse(status_code=400, content={"error": data.get("error", "auth.test failed")})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/api/slack-bot/test-dm")
async def test_slack_dm(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_system_admin),
):
    """Send a test Slack DM to the currently logged-in admin."""
    if not settings.SLACK_BOT_TOKEN:
        return JSONResponse(status_code=400, content={"error": "SLACK_BOT_TOKEN is not configured"})

    slack_uid = user.slack_user_id
    if not slack_uid and user.email:
        slack_uid = await lookup_slack_user_by_email(user.email)
        if slack_uid:
            user.slack_user_id = slack_uid
            db.commit()

    if not slack_uid:
        email_hint = f" (email on account: {user.email})" if user.email else " — no email set on your account"
        return JSONResponse(status_code=404, content={
            "error": f"Could not find your Slack user ID{email_hint}. Make sure your app email matches your Slack workspace email."
        })

    ok = await send_slack_dm(
        slack_uid,
        ":bell: *Test Notification* — Your Slack DM integration is working correctly. "
        "You will receive provisioning alerts here when you subscribe."
    )
    if ok:
        return JSONResponse(content={"status": "sent", "slack_user_id": slack_uid})
    return JSONResponse(status_code=500, content={"error": "Failed to send DM — check bot scopes (chat:write, im:write)"})


@router.post("/api/notifications/test-email")
async def test_notification_email(
    request: Request,
    user: User = Depends(require_system_admin),
):
    """Send a test email to the currently logged-in admin's email address."""
    if not settings.SMTP_HOST:
        return JSONResponse(status_code=400, content={"error": "SMTP_HOST is not configured in .env"})

    if not user.email:
        return JSONResponse(status_code=400, content={
            "error": "No email set on your account. Add your email in User Management first."
        })

    body_html = (
        "<p style='font-family:sans-serif;'>"
        "&#x1F514; <strong>Test Notification</strong> &mdash; "
        "Your email notification integration is working correctly. "
        "You will receive provisioning alerts here when you subscribe with email delivery enabled."
        "</p>"
        "<hr style='border:none;border-top:1px solid #eee;margin:1.5rem 0;'>"
        "<p style='font-size:0.8em;color:#999;'>Shelf2Site</p>"
    )

    ok = await send_email(user.email, "[Shelf2Site] Test Notification", body_html)
    if ok:
        return JSONResponse(content={"status": "sent", "to": user.email})
    return JSONResponse(status_code=500, content={
        "error": f"Failed to send email to {user.email} — check SMTP settings in .env"
    })
