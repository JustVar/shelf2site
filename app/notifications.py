"""Notification system: Slack webhooks + in-app notification store + email.

Usage:
    from .notifications import notify

    # Send a notification (stores in DB + sends to Slack if configured)
    await notify(
        db, "provisioning_advance",
        title="Stage Advanced",
        message="Edge Box SN-001 moved to 'Configured' by Parker",
        link="/provisioning",
        actor_id=user.id,
    )
"""

import logging
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

try:
    import aiosmtplib as _aiosmtplib
except ImportError:
    _aiosmtplib = None  # type: ignore

import httpx
from sqlalchemy.orm import Session

from sqlalchemy import and_, or_

from .config import settings
from .models import Notification, NotificationSubscription, User

logger = logging.getLogger(__name__)

# Notification type → Slack emoji mapping
SLACK_EMOJI = {
    "provisioning_advance": ":arrow_forward:",
    "provisioning_complete": ":white_check_mark:",
    "provisioning_revert": ":rewind:",
    "provisioning_overdue": ":warning:",
    "warranty_expiring": ":clock3:",
    "trial_overdue": ":hourglass:",
    "device_disposed": ":wastebasket:",
    "device_approved": ":heavy_plus_sign:",
    "general": ":bell:",
}


async def lookup_slack_user_by_email(email: str) -> Optional[str]:
    """Look up a Slack user ID by email via the Slack Web API.

    Requires SLACK_BOT_TOKEN with users:read.email scope.
    Returns the Slack user ID (e.g. "U0123456") or None on failure.
    """
    if not settings.SLACK_BOT_TOKEN or not email:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://slack.com/api/users.lookupByEmail",
                params={"email": email},
                headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            )
            data = resp.json()
            if data.get("ok") and data.get("user"):
                return data["user"]["id"]
            logger.debug("Slack user lookup failed for %s: %s", email, data.get("error"))
    except Exception:
        logger.exception("Error looking up Slack user by email")
    return None


async def send_slack_dm(slack_user_id: str, text: str) -> bool:
    """Send a direct message to a Slack user via the bot token.

    Steps:
    1. Open (or retrieve) the DM channel via conversations.open
    2. Post the message via chat.postMessage

    Requires SLACK_BOT_TOKEN with chat:write and im:write scopes.
    """
    if not settings.SLACK_BOT_TOKEN or not slack_user_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Step 1: open DM channel
            open_resp = await client.post(
                "https://slack.com/api/conversations.open",
                json={"users": slack_user_id},
                headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            )
            open_data = open_resp.json()
            if not open_data.get("ok"):
                logger.warning("conversations.open failed: %s", open_data.get("error"))
                return False
            channel_id = open_data["channel"]["id"]

            # Step 2: post message
            msg_resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json={"channel": channel_id, "text": text},
                headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            )
            msg_data = msg_resp.json()
            if msg_data.get("ok"):
                return True
            logger.warning("chat.postMessage failed: %s", msg_data.get("error"))
    except Exception:
        logger.exception("Error sending Slack DM to %s", slack_user_id)
    return False


async def send_email(to_email: str, subject: str, body_html: str) -> bool:
    """Send an HTML email via SMTP. Returns True on success.

    Requires SMTP_HOST in .env and aiosmtplib installed.
    Returns False silently if either is missing.
    """
    if _aiosmtplib is None or not settings.SMTP_HOST or not to_email:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html"))
        await _aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_TLS,
        )
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


async def send_slack(text: str, blocks: Optional[list] = None, test_mode: bool = False) -> bool:
    """Post a message to the configured Slack webhook. Returns True on success.

    When test_mode=True, routes to SLACK_TEST_WEBHOOK_URL (private channel).
    If that is not configured, the message is suppressed.
    """
    url = settings.SLACK_TEST_WEBHOOK_URL if test_mode else settings.SLACK_WEBHOOK_URL
    if not url:
        return False

    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            logger.warning("Slack webhook returned %s: %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("Failed to send Slack notification")
    return False


async def notify(
    db: Session,
    notification_type: str,
    title: str,
    message: str,
    link: str = "",
    actor_id: Optional[int] = None,
    slack: bool = True,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
) -> Notification:
    """Create an in-app notification, send to Slack channel, and DM subscribers.

    Args:
        db: Database session
        notification_type: Category key (e.g. 'provisioning_advance')
        title: Short title for the notification
        message: Full message text
        link: Optional URL path to link to (e.g. '/provisioning')
        actor_id: User who triggered the event (nullable for system events)
        slack: Whether to also send to the general Slack channel (default True)
        resource_type: Resource category for subscription matching (e.g. 'provisioning')
        resource_id: Specific record ID for subscription matching

    Returns:
        The created Notification record
    """
    # Store in database
    notif = Notification(
        notification_type=notification_type,
        title=title,
        message=message,
        link=link,
        actor_id=actor_id,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)

    # Build the full URL for links (used in both Slack channel and DMs)
    full_url = f"http://192.0.2.174{link}" if link else ""

    # During E2E test runs, route to the private test channel instead of the general channel.
    # The flag file is created by the test script before any tests run (and SSH'd to the NUC).
    is_test_mode = os.path.exists("/tmp/.asset_tracker_test_mode")

    # --- General Slack channel notification ---
    if slack:
        emoji = SLACK_EMOJI.get(notification_type, ":bell:")
        slack_text = f"{emoji} *{title}*\n{message}"
        if full_url:
            slack_text += f"\n<{full_url}|View in Asset Tracker>"
        await send_slack(slack_text, test_mode=is_test_mode)

    # --- Per-user delivery (Slack DMs + email, based on each subscriber's preferences) ---
    # Run even if SLACK_BOT_TOKEN is absent — email delivery works independently.
    if not is_test_mode:
        await _deliver_to_subscribers(db, notification_type, title, message, full_url,
                                      resource_type, resource_id)

    return notif


async def _deliver_to_subscribers(
    db: Session,
    notification_type: str,
    title: str,
    message: str,
    full_url: str,
    resource_type: Optional[str],
    resource_id: Optional[int],
) -> None:
    """Find subscribers for this event and send Slack DMs."""
    filters = [NotificationSubscription.is_active.is_(True)]
    conditions = []

    # Global event type subscription (no resource filter)
    conditions.append(
        and_(
            NotificationSubscription.event_type == notification_type,
            NotificationSubscription.resource_id.is_(None),
        )
    )

    # Record-specific watch subscription
    if resource_type and resource_id:
        conditions.append(
            and_(
                NotificationSubscription.resource_type == resource_type,
                NotificationSubscription.resource_id == resource_id,
            )
        )

    filters.append(or_(*conditions))

    subscriptions = (
        db.query(NotificationSubscription)
        .filter(*filters)
        .all()
    )

    dm_text = f"*{title}*\n{message}"
    if full_url:
        dm_text += f"\n<{full_url}|View in Asset Tracker>"

    for sub in subscriptions:
        if not sub.deliver_slack:
            continue
        user = db.query(User).filter(User.id == sub.user_id).first()
        if not user:
            continue

        slack_uid = user.slack_user_id
        # Auto-match by email if not yet resolved
        if not slack_uid and user.slack_auto_match and user.email:
            slack_uid = await lookup_slack_user_by_email(user.email)
            if slack_uid:
                user.slack_user_id = slack_uid
                db.commit()

        if slack_uid:
            await send_slack_dm(slack_uid, dm_text)

        # --- Email delivery ---
        if sub.deliver_email and user.email:
            email_subject = f"[Asset Tracker] {title}"
            link_html = (
                "<p><a href='" + full_url + "'>View in Asset Tracker &rarr;</a></p>"
                if full_url else ""
            )
            email_body = (
                "<p style='font-family:sans-serif;'>" + message + "</p>"
                + link_html
                + "<hr style='border:none;border-top:1px solid #eee;margin:1.5rem 0;'>"
                + "<p style='font-size:0.8em;color:#999;'>Asset Tracker &mdash; Company</p>"
            )
            await send_email(user.email, email_subject, email_body)


def get_unread_count(db: Session) -> int:
    """Get count of unread notifications."""
    return db.query(Notification).filter(
        Notification.is_read.is_(False),
        Notification.dismissed.is_(False),
    ).count()


def get_recent_notifications(db: Session, limit: int = 20) -> list[Notification]:
    """Get recent notifications for the notification panel."""
    return (
        db.query(Notification)
        .filter(Notification.dismissed.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
