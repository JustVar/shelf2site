"""API routes for the guided tour system.

Endpoints:
  GET  /api/tours           — tours for current page with user progress
  GET  /api/tours/all       — all tours with progress (help menu)
  GET  /api/tours/{tour_id} — single tour definition
  POST /api/tours/progress  — mark tour completed/dismissed
  DELETE /api/tours/progress/{tour_id} — reset progress (retake)

Tours are filtered by user role/permissions. Each tour has an optional
`required_access` field (a User model property name). If set, the tour
is only visible to users where that property returns True.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user, User
from ..database import get_db
from ..models import UserTourProgress
from ..tours import get_tours_for_page, get_tour_by_id, get_all_tours

router = APIRouter()


def _user_can_see_tour(user: User, tour: dict) -> bool:
    """Check if a user has access to a tour based on its required_access field."""
    access = tour.get("required_access")
    if not access:
        return True
    return getattr(user, access, False)


@router.get("/api/tours")
def list_tours_for_page(
    page: str = Query(..., description="Current page path after root path"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tours = [t for t in get_tours_for_page(page) if _user_can_see_tour(user, t)]
    tour_ids = [t["id"] for t in tours]

    progress_records = (
        db.query(UserTourProgress)
        .filter(
            UserTourProgress.user_id == user.id,
            UserTourProgress.tour_id.in_(tour_ids),
        )
        .all()
    ) if tour_ids else []

    progress_map = {
        p.tour_id: {
            "completed": True,
            "dismissed": p.dismissed,
            "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        }
        for p in progress_records
    }

    result = []
    for tour in tours:
        tour_data = dict(tour)
        tour_data["progress"] = progress_map.get(
            tour["id"],
            {"completed": False, "dismissed": False, "completed_at": None},
        )
        result.append(tour_data)

    return JSONResponse(content={"tours": result})


@router.get("/api/tours/all")
def list_all_tours(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    all_tours = [t for t in get_all_tours() if _user_can_see_tour(user, t)]
    tour_ids = [t["id"] for t in all_tours]

    progress_records = (
        db.query(UserTourProgress)
        .filter(
            UserTourProgress.user_id == user.id,
            UserTourProgress.tour_id.in_(tour_ids),
        )
        .all()
    ) if tour_ids else []

    progress_map = {
        p.tour_id: {"completed": True, "dismissed": p.dismissed}
        for p in progress_records
    }

    for tour in all_tours:
        tour["progress"] = progress_map.get(
            tour["id"],
            {"completed": False, "dismissed": False},
        )

    return JSONResponse(content={"tours": all_tours})


@router.get("/api/tours/{tour_id}")
def get_single_tour(
    tour_id: str,
    user: User = Depends(get_current_user),
):
    tour = get_tour_by_id(tour_id)
    if not tour:
        return JSONResponse(status_code=404, content={"error": f"Tour not found: {tour_id}"})
    if not _user_can_see_tour(user, tour):
        return JSONResponse(status_code=403, content={
            "error": "Tour unavailable",
            "message": "This tour requires additional permissions that your account doesn't have.",
        })
    return JSONResponse(content=tour)


@router.post("/api/tours/progress")
async def update_tour_progress(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    tour_id = body.get("tour_id")
    dismissed = body.get("dismissed", False)

    if not tour_id:
        return JSONResponse(status_code=400, content={"error": "tour_id is required"})

    existing = (
        db.query(UserTourProgress)
        .filter(
            UserTourProgress.user_id == user.id,
            UserTourProgress.tour_id == tour_id,
        )
        .first()
    )

    if existing:
        existing.completed_at = datetime.utcnow()
        existing.dismissed = dismissed
    else:
        db.add(UserTourProgress(
            user_id=user.id,
            tour_id=tour_id,
            dismissed=dismissed,
        ))

    db.commit()
    return JSONResponse(content={"ok": True, "tour_id": tour_id, "dismissed": dismissed})


@router.delete("/api/tours/progress/{tour_id}")
def reset_tour_progress(
    tour_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = (
        db.query(UserTourProgress)
        .filter(
            UserTourProgress.user_id == user.id,
            UserTourProgress.tour_id == tour_id,
        )
        .delete()
    )
    db.commit()
    return JSONResponse(content={"ok": True, "deleted": deleted})
