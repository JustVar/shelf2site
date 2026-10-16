"""Notification API routes: list, mark read, dismiss, and subscription management."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Notification, NotificationSubscription, User
from ..notifications import get_recent_notifications, get_unread_count

router = APIRouter()


@router.get("/api/notifications")
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return recent notifications with unread count."""
    notifications = get_recent_notifications(db, limit=20)
    unread = get_unread_count(db)

    return JSONResponse(content={
        "unread_count": unread,
        "notifications": [
            {
                "id": n.id,
                "type": n.notification_type,
                "title": n.title,
                "message": n.message,
                "link": n.link or "",
                "is_read": n.is_read,
                "actor": n.actor.display_name if n.actor else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
    })


@router.post("/api/notifications/{notif_id}/read")
def mark_read(
    notif_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a single notification as read."""
    notif = db.query(Notification).filter(Notification.id == notif_id).first()
    if not notif:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    notif.is_read = True
    db.commit()
    return JSONResponse(content={"status": "ok"})


@router.post("/api/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark all notifications as read."""
    db.query(Notification).filter(
        Notification.is_read.is_(False)
    ).update({"is_read": True})
    db.commit()
    return JSONResponse(content={"status": "ok"})


@router.post("/api/notifications/dismiss-all")
def dismiss_all_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dismiss (clear) all notifications."""
    db.query(Notification).filter(
        Notification.dismissed.is_(False)
    ).update({"dismissed": True})
    db.commit()
    return JSONResponse(content={"status": "ok"})


@router.post("/api/notifications/{notif_id}/dismiss")
def dismiss_notification(
    notif_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dismiss (hide) a notification."""
    notif = db.query(Notification).filter(Notification.id == notif_id).first()
    if not notif:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    notif.dismissed = True
    db.commit()
    return JSONResponse(content={"status": "ok"})


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------

@router.get("/api/notifications/subscriptions")
def list_subscriptions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the current user's active notification subscriptions."""
    subs = (
        db.query(NotificationSubscription)
        .filter(
            NotificationSubscription.user_id == user.id,
            NotificationSubscription.is_active.is_(True),
        )
        .all()
    )
    return JSONResponse(content={
        "subscriptions": [
            {
                "id": s.id,
                "event_type": s.event_type,
                "resource_type": s.resource_type,
                "resource_id": s.resource_id,
                "deliver_slack": s.deliver_slack,
                "deliver_inapp": s.deliver_inapp,
                "deliver_email": getattr(s, "deliver_email", False),
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ]
    })


@router.post("/api/notifications/subscriptions")
async def create_subscription(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Subscribe to a notification event type or watch a specific record.

    Body:
        event_type (str|null): e.g. "provisioning_advance" — subscribe to all of this type
        resource_type (str|null): e.g. "provisioning" — used for record watches
        resource_id (int|null): specific record ID to watch
        deliver_slack (bool): default true
        deliver_inapp (bool): default true
    """
    body = await request.json()
    event_type = body.get("event_type") or None
    resource_type = body.get("resource_type") or None
    resource_id = body.get("resource_id") or None

    if not event_type and not (resource_type and resource_id):
        return JSONResponse(status_code=400, content={"error": "Provide event_type or resource_type+resource_id"})

    # Check for duplicate
    existing = db.query(NotificationSubscription).filter(
        NotificationSubscription.user_id == user.id,
        NotificationSubscription.event_type == event_type,
        NotificationSubscription.resource_type == resource_type,
        NotificationSubscription.resource_id == resource_id,
    ).first()

    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.deliver_slack = bool(body.get("deliver_slack", True))
            existing.deliver_inapp = bool(body.get("deliver_inapp", True))
            db.commit()
            return JSONResponse(content={"status": "reactivated", "id": existing.id})
        return JSONResponse(status_code=409, content={"error": "Already subscribed", "id": existing.id})

    sub = NotificationSubscription(
        user_id=user.id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        deliver_slack=bool(body.get("deliver_slack", True)),
        deliver_inapp=bool(body.get("deliver_inapp", True)),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return JSONResponse(content={"status": "subscribed", "id": sub.id})


@router.patch("/api/notifications/subscriptions/{sub_id}")
async def update_subscription(
    sub_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update delivery preferences for a subscription (must be your own).

    Body: { deliver_slack: bool, deliver_inapp: bool }
    """
    sub = db.query(NotificationSubscription).filter(
        NotificationSubscription.id == sub_id,
        NotificationSubscription.user_id == user.id,
    ).first()
    if not sub:
        return JSONResponse(status_code=404, content={"error": "Subscription not found"})

    body = await request.json()
    if "deliver_slack" in body:
        sub.deliver_slack = bool(body["deliver_slack"])
    if "deliver_inapp" in body:
        sub.deliver_inapp = bool(body["deliver_inapp"])
    if "deliver_email" in body:
        sub.deliver_email = bool(body["deliver_email"])
    db.commit()
    return JSONResponse(content={"status": "ok"})


@router.delete("/api/notifications/subscriptions/{sub_id}")
def delete_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unsubscribe from a notification subscription (must be your own)."""
    sub = db.query(NotificationSubscription).filter(
        NotificationSubscription.id == sub_id,
        NotificationSubscription.user_id == user.id,
    ).first()
    if not sub:
        return JSONResponse(status_code=404, content={"error": "Subscription not found"})
    sub.is_active = False
    db.commit()
    return JSONResponse(content={"status": "unsubscribed"})


@router.get("/api/notifications/watch/{resource_type}/{resource_id}")
def get_watch_status(
    resource_type: str,
    resource_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return whether the current user is watching a specific record."""
    sub = db.query(NotificationSubscription).filter(
        NotificationSubscription.user_id == user.id,
        NotificationSubscription.resource_type == resource_type,
        NotificationSubscription.resource_id == resource_id,
        NotificationSubscription.is_active.is_(True),
    ).first()
    return JSONResponse(content={"watching": sub is not None, "sub_id": sub.id if sub else None})


@router.post("/api/notifications/watch/{resource_type}/{resource_id}")
def toggle_watch(
    resource_type: str,
    resource_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Toggle watch on a specific resource (subscribe if not watching, unsubscribe if watching)."""
    sub = db.query(NotificationSubscription).filter(
        NotificationSubscription.user_id == user.id,
        NotificationSubscription.resource_type == resource_type,
        NotificationSubscription.resource_id == resource_id,
    ).first()

    if sub and sub.is_active:
        sub.is_active = False
        db.commit()
        return JSONResponse(content={"watching": False})
    elif sub:
        sub.is_active = True
        db.commit()
        return JSONResponse(content={"watching": True, "sub_id": sub.id})
    else:
        new_sub = NotificationSubscription(
            user_id=user.id,
            resource_type=resource_type,
            resource_id=resource_id,
            deliver_slack=True,
            deliver_inapp=True,
        )
        db.add(new_sub)
        db.commit()
        db.refresh(new_sub)
        return JSONResponse(content={"watching": True, "sub_id": new_sub.id})
