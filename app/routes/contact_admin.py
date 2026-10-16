"""Contact Admin — posts user message to #shelf2site-admin Slack channel."""
import os
import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..auth import get_current_user, User
from ..config import settings

router = APIRouter()


@router.post("/api/contact-admin")
async def contact_admin(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not settings.SLACK_ADMIN_WEBHOOK_URL:
        return JSONResponse(
            {"status": "error", "message": "Admin notifications not configured."},
            status_code=500,
        )

    body = await request.json()
    message = (body.get("message") or "").strip()
    page = (body.get("page") or "Unknown page").strip()

    if not message:
        return JSONResponse(
            {"status": "error", "message": "Message cannot be empty."},
            status_code=400,
        )

    user_display = user.display_name or user.email or user.username
    slack_payload = {
        "attachments": [
            {
                "color": "#e67e22",
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "\U0001f510 Admin Contact Request"},
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*User:*\n{user_display}"},
                            {"type": "mrkdwn", "text": f"*Role:*\n{user.role}"},
                            {"type": "mrkdwn", "text": f"*Email:*\n{user.email}"},
                            {"type": "mrkdwn", "text": f"*Page:*\n{page}"},
                        ],
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*Message:*\n{message}"},
                    },
                ],
            }
        ]
    }

    # During E2E tests, suppress Slack delivery to avoid spamming the admin channel.
    if os.path.exists("/tmp/.asset_tracker_test_mode"):
        return JSONResponse({"status": "ok"})

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.SLACK_ADMIN_WEBHOOK_URL, json=slack_payload)
            if resp.status_code == 200:
                return JSONResponse({"status": "ok"})
            return JSONResponse(
                {"status": "error", "message": "Slack delivery failed."},
                status_code=500,
            )
    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500,
        )
