from pathlib import Path
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from ..auth import get_current_user, User
from ..config import settings
from ..localtime import register
from ..database import get_db
from ..models import Item, ItemLocation
from .c2c import _pilots_due_back

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)

CATEGORY_COLORS = {
    "access_control":  "#AA6633",
    "camera":          "#6655FF",
    "computer":        "#4488FF",
    "cpu":             "#CD853F",
    "motherboard":     "#4682B4",
    "gpu":             "#FF4488",
    "ram":             "#DEB887",
    "storage_drive":   "#E8A838",
    "psu":             "#8FBC8F",
    "cpu_cooler":      "#87CEEB",
    "case_fan":        "#B0C4DE",
    "pci":             "#7B68EE",
    "product_cabling": "#A0A0A0",
    "consumables":     "#90EE90",
    "edge_box":        "#378ADD",
    "ups":             "#20B2AA",
    "mobile_device":   "#FF8800",
    "monitor":         "#FFD700",
    "network":         "#00BBFF",
    "office_equipment":"#88DD00",
    "pc_accessories":  "#D2691E",
    "camera_c2c":      "#1D9E75",
    "cloud_box":       "#7B68EE",
}

# fl-restyle palette for opted-in pages (dashboard today; propagation pages
# import this as they opt in). Non-opted pages keep CATEGORY_COLORS above.
FL_CATEGORY_COLORS = {
    **CATEGORY_COLORS,
    "camera":        "#A492D6",
    "computer":      "#0075FF",
    "gpu":           "#FF6B6B",
    "storage_drive": "#FFB547",
    "edge_box":      "#2CD9FF",
    "camera_c2c":    "#01B574",
    "cloud_box":     "#7FA3CE",
}

ALL_CATEGORIES = list(CATEGORY_COLORS.keys())

PRODUCT_CATEGORIES = ["edge_box", "cloud_box", "camera_c2c"]

# Display name overrides for categories that don't format well with .title()
CATEGORY_DISPLAY_NAMES = {
    "edge_box":        "Edge Box",
    "cloud_box":       "Cloud Box",
    "camera_c2c":      "Camera 2 Cloud",
    "camera":          "Camera",
    "gpu":             "GPU",
    "cpu":             "CPU",
    "psu":             "PSU",
    "ups":             "UPS",
    "ram":             "RAM",
    "pci":             "PCI",
    "storage_drive":   "Storage Drive",
    "computer":        "Computer",
    "monitor":         "Monitor",
    "network":         "Network",
    "motherboard":     "Motherboard",
    "cpu_cooler":      "CPU Cooler",
    "case_fan":        "Case Fan",
    "mobile_device":   "Mobile Device",
    "access_control":  "Access Control",
    "pc_accessories":  "PC Accessories",
    "office_equipment":"Office Equipment",
    "product_cabling": "Product Cabling",
    "consumables":     "Consumables",
}

def category_display(cat: str) -> str:
    """Return human-readable category name."""
    return CATEGORY_DISPLAY_NAMES.get(str(cat), str(cat).replace("_", " ").title())


def _get_category_stats(db):
    """Legacy stub — returns empty list until inventory is rebuilt for item_schema."""
    return []


@router.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    # --- Total items ---
    total_items = db.query(func.count(Item.id)).scalar() or 0

    # --- Deployed counts per product category ---
    def deployed_count(category):
        return (
            db.query(func.count(Item.id))
            .filter(Item.item_category == category, Item.item_status == 'Deployed')
            .scalar() or 0
        )

    def ready_count(category):
        return (
            db.query(func.count(Item.id))
            .filter(Item.item_category == category, Item.item_status == 'Ready to Deploy')
            .scalar() or 0
        )

    deployed = {cat: deployed_count(cat) for cat in PRODUCT_CATEGORIES}
    ready = {cat: ready_count(cat) for cat in PRODUCT_CATEGORIES}

    # --- Status panels (Pending, Unassigned, Un-deployable per product) ---
    def status_counts(category):
        rows = (
            db.query(Item.item_status, func.count(Item.id))
            .filter(Item.item_category == category)
            .group_by(Item.item_status)
            .all()
        )
        counts = {str(s): c for s, c in rows if s}
        return {
            "pending":       counts.get("Pending", 0),
            "unassigned":    counts.get("Unassigned", 0),
            "un_deployable": counts.get("Un-deployable", 0),
        }

    product_status = {cat: status_counts(cat) for cat in PRODUCT_CATEGORIES}

    # --- Category counts for composition bar ---
    raw_counts = (
        db.query(Item.item_category, func.count(Item.id))
        .group_by(Item.item_category)
        .all()
    )
    counts_map = {str(cat): cnt for cat, cnt in raw_counts if cat}
    total_for_pct = sum(counts_map.values()) or 1
    category_counts = [
        {
            "name":    cat,
            "display": category_display(cat),
            "count":   counts_map.get(cat, 0),
            "pct":     round(counts_map.get(cat, 0) / total_for_pct * 100, 1),
            "color":   FL_CATEGORY_COLORS.get(cat, "#888888"),
        }
        for cat in ALL_CATEGORIES
        if counts_map.get(cat, 0) > 0
    ]

    # --- Recent activity ---
    recent_items = (
        db.query(Item)
        .order_by(Item.last_updated.desc())
        .limit(10)
        .all()
    )
    recent_activity = [
        {
            "id":           item.id,
            "name":         item.item_name or item.item_sn or f"Item {item.id}",
            "category":     str(item.item_category) if item.item_category else None,
            "category_display": category_display(item.item_category) if item.item_category else "—",
            "status":       str(item.item_status) if item.item_status else "—",
            "last_updated": item.last_updated,
            "is_new":       item.created_at == item.last_updated,
            "color":        FL_CATEGORY_COLORS.get(str(item.item_category), "#888888"),
        }
        for item in recent_items
    ]

    pilots = _pilots_due_back(db)

    return templates.TemplateResponse("dashboard.html", {
        "request":          request,
        "user":             user,
        "total_items":      total_items,
        "deployed":         deployed,
        "ready":            ready,
        "product_categories": PRODUCT_CATEGORIES,
        "product_status":   product_status,
        "category_counts":  category_counts,
        "recent_activity":  recent_activity,
        "pilots_overdue":   pilots["counts"]["overdue"],
        "pilots_due_soon":  pilots["counts"]["due_soon"],
        "page":             "dashboard",
    })
