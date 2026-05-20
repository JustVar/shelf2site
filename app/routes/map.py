"""Edge box live map route — MapLibre GL with vector tiles."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..auth import require_map_access
from ..config import settings
from ..database import get_db
from ..models import EdgeBox, User

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

# Status → marker color mapping
STATUS_COLORS = {
    "Production": "green",
    "Customer Lab": "orange",
    "Company Lab": "blue",
    "Company Inventory": "blue",
    "Demo Kit": "purple",
}


@router.get("/")
def map_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_map_access)
):
    """Render the edge box map page (editor+ only)."""
    # Get edge boxes that have coordinates AND are visible on map
    mapped_boxes = (
        db.query(EdgeBox)
        .filter(
            EdgeBox.geo_lat.isnot(None),
            EdgeBox.geo_lng.isnot(None),
            EdgeBox.show_on_map.is_(True)
        )
        .all()
    )

    # Get edge boxes missing coordinates (only show visible ones)
    unmapped_boxes = (
        db.query(EdgeBox)
        .filter(
            EdgeBox.deployment_type.in_(["customer", "pilot"]),
            (EdgeBox.geo_lat.is_(None)) | (EdgeBox.geo_lng.is_(None)),
            EdgeBox.show_on_map.is_(True)
        )
        .all()
    )

    return templates.TemplateResponse("map.html", {
        "request": request,
        "user": user,
        "mapped_count": len(mapped_boxes),
        "unmapped_count": len(unmapped_boxes),
        "unmapped_boxes": unmapped_boxes,
    })


@router.get("/data")
def map_data(
    db: Session = Depends(get_db),
    user: User = Depends(require_map_access)
):
    """JSON API: return edge box markers for MapLibre (editor+ only, filtered by show_on_map)."""
    boxes = (
        db.query(EdgeBox)
        .filter(
            EdgeBox.geo_lat.isnot(None),
            EdgeBox.geo_lng.isnot(None),
            EdgeBox.show_on_map.is_(True)
        )
        .all()
    )

    markers = []
    for box in boxes:
        color = STATUS_COLORS.get(box.status, "gray")
        markers.append({
            "id": box.id,
            "lat": box.geo_lat,
            "lng": box.geo_lng,
            "color": color,
            "popup": {
                "org": box.org or "Unknown",
                "customer": box.customer or "",
                "site": box.site_name or "",
                "serial": box.serial or "N/A",
                "part_number": box.part_number or "",
                "status": box.status or "Unknown",
                "deployment": box.deployment_type or "",
                "last_updated": box.last_updated.isoformat() if box.last_updated else "",
            },
        })

    return JSONResponse(content={"markers": markers})
