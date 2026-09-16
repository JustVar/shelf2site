"""Deployment map: customer unit tracking (redesign, decisions locked 2026-07-09).

Data model:
- The unit universe is the UNION of unified-inventory items (item_schema.items
  joined to their geo-located, show_on_map locations) and legacy
  public.edge_boxes rows that carry their own coordinates. Legacy rows whose
  serial matches an edge-box item are skipped so migrated units never render
  twice.
- Deal type is derived at query time, never stored: the latest
  device_provisioning row that links a unit to a customer order supplies
  customer_orders.order_type (sale -> purchased, plus pilot / try_and_buy /
  demo). Legacy edge boxes without order linkage fall back to a
  deployment_type inference and are marked inferred; everything else is
  unassigned. "Try & Buy" here always means order_type try_and_buy (our
  hardware loaned out) - never the vendor_trials feature.
- Visibility flows through app.map_visibility: unit/site/customer curation
  rows plus the sensitive-order rule. That helper is the only filter; do not
  add show_on_map conditions anywhere else in this file.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import log_event
from ..auth import get_current_user, require_map_access, require_editor
from ..config import settings
from ..database import get_db
from ..map_visibility import load_hidden, norm_key, unit_visible
from ..models import (
    CustomerOrder,
    DeviceProvisioning,
    EdgeBox,
    Item,
    Site,
    MapVisibility,
    User,
)
from .c2c import _pilots_due_back

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP

# ── Single vocabulary for the three color modes ─────────────────────────────
DEAL_CLASSES = {"sale": "purchased", "pilot": "pilot", "try_and_buy": "try_and_buy", "demo": "demo"}
DEAL_COLORS = {
    "purchased": "#01B574",
    "pilot": "#FFB547",
    "try_and_buy": "#2C9FD9",
    "demo": "#A492D6",
    "unassigned": "#97A3B6",
}
DEAL_LABELS = {
    "purchased": "Purchased",
    "pilot": "Pilot",
    "try_and_buy": "Try & Buy",
    "demo": "Demo",
    "unassigned": "Unassigned",
}
UNIT_LABELS = {"edge_box": "Edge Unit", "cloud_box": "Cloud Box", "camera_c2c": "C2C Camera"}
UNIT_COLORS = {"edge_box": "#2CD9FF", "cloud_box": "#7FA3CE", "camera_c2c": "#01B574"}
PRODUCT_CATEGORIES = list(UNIT_LABELS.keys())

# One status color map for unified item statuses AND legacy edge-box strings -
# the old page carried four disagreeing vocabularies (server colors, filter
# checkbox values, legend labels, css classes); this dict is now the only one.
STATUS_COLORS = {
    "Deployed": "#01B574",
    "Production": "#01B574",
    "Ready to Deploy": "#2CD9FF",
    "Pending": "#FFB547",
    "Customer Lab": "#FFB547",
    "Un-deployable": "#FF6B6B",
    "Checked Out": "#A492D6",
    "Demo Kit": "#A492D6",
    "Company Lab": "#2C9FD9",
    "Company Inventory": "#2C9FD9",
    "Decommissioned": "#97A3B6",
    "Unassigned": "#97A3B6",
}
STATUS_FALLBACK = "#97A3B6"

# Legacy deployment_type inference (used only when no order linkage exists).
DEPLOYMENT_INFERENCE = {"pilot": "pilot", "customer": "purchased", "demo": "demo"}


def _slug(value):
    return "".join(ch if ch.isalnum() else "_" for ch in (value or "unknown").lower())


def _deal_maps(db):
    """Latest order linkage per unit: item_id -> row, edge_box id -> row."""
    rows = (
        db.query(
            DeviceProvisioning.id,
            DeviceProvisioning.item_id,
            DeviceProvisioning.device_table,
            DeviceProvisioning.device_id,
            DeviceProvisioning.returned_date,
            DeviceProvisioning.created_at,
            CustomerOrder.order_type,
            CustomerOrder.is_sensitive,
            CustomerOrder.customer_name,
            CustomerOrder.expected_return,
        )
        .join(CustomerOrder, CustomerOrder.id == DeviceProvisioning.customer_order_id)
        .order_by(DeviceProvisioning.id)
        .all()
    )
    by_item, by_edge = {}, {}
    for r in rows:
        if r.item_id is not None:
            by_item[r.item_id] = r  # ordered by dp.id: latest row wins
        elif r.device_table == "edge_boxes":
            by_edge[r.device_id] = r
    return by_item, by_edge


def _classify(link, deployment_type=None):
    """(deal_class, provenance, link_row). Provenance: order|inferred|none."""
    if link is not None:
        cls = DEAL_CLASSES.get(link.order_type)
        if cls:
            return cls, "order", link
    inferred = DEPLOYMENT_INFERENCE.get(deployment_type or "")
    if inferred:
        return inferred, "inferred", None
    return "unassigned", "none", None


def _due_back(link):
    """Loan due-back date for a still-out unit, else None."""
    if link is None or link.order_type == "sale":
        return None
    if link.returned_date is not None:
        return None
    return link.expected_return


def _feature(unit_key, kind, lng, lat, name, serial, category, status, deal, provenance,
             customer, site, city, deployed, due_back, view_url):
    due_soon = bool(due_back and (due_back - date.today()).days <= 30)
    # Item units on the customer map are at a customer site by construction;
    # a non-Deployed status there is the place/status smell triage surfaces.
    data_check = ""
    if kind == "item" and status != "Deployed":
        data_check = f"At a customer site but status is {status or 'unset'}"
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {
            "id": unit_key,
            "kind": kind,
            "name": name or "",
            "serial": serial or "",
            "category": category,
            "unitLabel": UNIT_LABELS.get(category, category or "Unit"),
            "status": status or "",
            "deal": deal,
            "dealLabel": DEAL_LABELS[deal],
            "provenance": provenance,
            "customer": customer or "",
            "site": site or "",
            "city": city or "",
            "deployed": deployed.isoformat() if deployed else "",
            "dueBack": due_back.isoformat() if due_back else "",
            "dueSoon": due_soon,
            "viewUrl": view_url or "",
            "dataCheck": data_check,
            "dealColor": DEAL_COLORS[deal],
            "utColor": UNIT_COLORS.get(category, STATUS_FALLBACK),
            "statusColor": STATUS_COLORS.get(status or "", STATUS_FALLBACK),
            "stSlug": _slug(status),
        },
    }


def _collect_units(db, user):
    """The visible unit universe with deal context. Returns (features, extras)."""
    hidden = load_hidden(db)
    can_sensitive = user.has_sensitive_customers_access
    by_item, by_edge = _deal_maps(db)
    features = []

    # Legacy rows load first so migrated items can (a) suppress their twin
    # via the serial dedup and (b) inherit the twin's order linkage. The
    # dedup set is built BEFORE any visibility check: hiding a migrated
    # item must never resurrect its legacy twin.
    legacy = (
        db.query(EdgeBox)
        .filter(
            EdgeBox.geo_lat.isnot(None),
            EdgeBox.geo_lng.isnot(None),
            EdgeBox.show_on_map.is_(True),
        )
        .all()
    )
    eb_by_serial = {}
    for eb in legacy:
        sn = (eb.serial or "").strip().lower()
        if sn:
            eb_by_serial[sn] = eb

    items = (
        db.query(Item, Site)
        .join(Site, Site.id == Item.location_id)
        .filter(
            Item.item_category.in_(PRODUCT_CATEGORIES),
            Site.site_type == "customer_site",  # office units drop off the map
            Site.geo_lat.isnot(None),
            Site.geo_lng.isnot(None),
            Site.show_on_map.is_(True),
        )
        .all()
    )
    item_serials = set()
    for item, loc in items:
        sn = (item.item_sn or "").strip().lower()
        if item.item_category == "edge_box" and sn:
            item_serials.add(sn)

    for item, place in items:
        sn = (item.item_sn or "").strip().lower()
        link = by_item.get(item.id)
        if link is None and sn and sn in eb_by_serial:
            # Migrated unit: its provisioning rows still point at the
            # legacy edge_boxes id - inherit that order linkage.
            link = by_edge.get(eb_by_serial[sn].id)
        deal, provenance, _l = _classify(link)
        customer = (link.customer_name if link else None) or place.customer
        site = place.name
        if not unit_visible(hidden, f"item:{item.id}", customer, site,
                            bool(link and link.is_sensitive), can_sensitive):
            continue
        features.append(_feature(
            f"item:{item.id}", "item", place.geo_lng, place.geo_lat,
            item.item_name, item.item_sn, item.item_category,
            str(item.item_status) if item.item_status else "",
            deal, provenance, customer, site, place.city,
            item.dispatched_date, _due_back(link),
            f"{BP}/items/{item.id}",
        ))

    for eb in legacy:
        sn = (eb.serial or "").strip().lower()
        if sn and sn in item_serials:
            continue  # migrated: the item-schema twin owns this unit
        link = by_edge.get(eb.id)
        deal, provenance, _l = _classify(link, eb.deployment_type)
        customer = (link.customer_name if link else None) or eb.customer
        if not unit_visible(hidden, f"edge_box:{eb.id}", customer, eb.site_name,
                            bool(link and link.is_sensitive), can_sensitive):
            continue
        features.append(_feature(
            f"edge_box:{eb.id}", "edge_box", eb.geo_lng, eb.geo_lat,
            eb.org or eb.serial, eb.serial, "edge_box",
            eb.status or "", deal, provenance, customer, eb.site_name, None,
            None, _due_back(link), None,
        ))

    return features, hidden, by_item, by_edge


def _needs_location(db, by_item, by_edge, hidden, can_sensitive):
    """Mappable units lacking coordinates. Editor-facing: the payload gates
    this behind is_editor_or_above, and the same visibility rules apply so
    curated-away or sensitive units never leak through the rail card.
    Scope: deployed or order-linked units (the card exists to surface
    deployed-but-unmapped units, not internal shelf stock)."""
    out = []
    # Deployed-or-order-linked units that cannot pin: no place, or a
    # customer-site place missing coordinates. Left join keeps the place-less
    # case (an inner join excludes it structurally).
    items = (
        db.query(Item, Site)
        .outerjoin(Site, Site.id == Item.location_id)
        .filter(
            Item.item_category.in_(PRODUCT_CATEGORIES),
            (Item.location_id.is_(None))
            | ((Site.site_type == "customer_site")
               & ((Site.geo_lat.is_(None)) | (Site.geo_lng.is_(None)))),
        )
        .all()
    )
    for it, place in items:
        link = by_item.get(it.id)
        if link is None and str(it.item_status or "") != "Deployed":
            continue
        if place is not None and place.site_type != "customer_site":
            continue  # office stock is not a needs-location case
        if not unit_visible(hidden, f"item:{it.id}",
                            link.customer_name if link else None, None,
                            bool(link and link.is_sensitive), can_sensitive):
            continue
        out.append({
            "kind": "item", "id": it.id,
            "label": it.item_name or f"Item #{it.id}",
            "serial": it.item_sn or "",
            "hasLocation": it.location_id is not None,  # False = no place at all
            "viewUrl": f"{BP}/items/{it.id}",
        })
    legacy = (
        db.query(EdgeBox)
        .filter(
            EdgeBox.deployment_type.in_(["customer", "pilot", "demo"]),
            (EdgeBox.geo_lat.is_(None)) | (EdgeBox.geo_lng.is_(None)),
            EdgeBox.show_on_map.is_(True),
        )
        .all()
    )
    for eb in legacy:
        link = by_edge.get(eb.id)
        if not unit_visible(hidden, f"edge_box:{eb.id}",
                            (link.customer_name if link else None) or eb.customer,
                            eb.site_name, bool(link and link.is_sensitive), can_sensitive):
            continue
        out.append({
            "kind": "edge_box", "id": eb.id,
            "label": eb.org or eb.serial or f"Edge box #{eb.id}",
            "serial": eb.serial or "",
            "hasLocation": True,
            "viewUrl": "",
        })
    return out


@router.get("/", response_class=HTMLResponse)
def map_page(request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_map_access)):
    return templates.TemplateResponse("map.html", {
        "request": request,
        "user": user,
        "can_edit": user.is_editor_or_above,
        "is_kiosk": user.role == "map_kiosk",
    })


@router.get("/data")
def map_data(request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_map_access)):
    features, hidden, by_item, by_edge = _collect_units(db, user)
    today = date.today()
    props = [f["properties"] for f in features]

    deal_counts = {k: 0 for k in DEAL_COLORS}
    unit_counts = {k: 0 for k in UNIT_COLORS}
    status_counts = {}
    customers, sites = set(), set()
    cust_units = {}
    new30 = 0
    cutoff = datetime.utcnow() - timedelta(days=30)
    for p in props:
        deal_counts[p["deal"]] += 1
        if p["category"] in unit_counts:
            unit_counts[p["category"]] += 1
        if p["status"]:
            status_counts[p["status"]] = status_counts.get(p["status"], 0) + 1
        if p["customer"]:
            ck = norm_key(p["customer"])
            customers.add(ck)
            if ck not in cust_units:
                cust_units[ck] = {"label": p["customer"], "n": 0}
            cust_units[ck]["n"] += 1
        if p["site"]:
            sites.add(norm_key(p["site"]))
    # new-in-30-days: order-linked units whose provisioning row was created
    # inside the window (the only per-unit acquisition timestamp we have)
    linked = {f"item:{k}": v for k, v in by_item.items()}
    linked.update({f"edge_box:{k}": v for k, v in by_edge.items()})
    for p in props:
        link = linked.get(p["id"])
        if link is not None and link.created_at and link.created_at >= cutoff:
            new30 += 1

    pilots = _pilots_due_back(db)
    due_30 = 0
    for o in pilots["orders"]:
        er = o.get("expected_return")
        if o.get("order_type") == "pilot" and er and (er - today).days <= 30:
            due_30 += 1  # includes already-overdue pilots: still due back
    tnb_month = sum(
        1 for o in pilots["orders"]
        if o.get("order_type") == "try_and_buy"
        and o.get("expected_return")
        and o["expected_return"].year == today.year
        and o["expected_return"].month == today.month
    )

    total = len(props)
    metrics = {
        "total": total,
        "customers": len(customers),
        "sites": len(sites),
        "purchased": deal_counts["purchased"],
        "purchased_pct": round(deal_counts["purchased"] * 100 / total) if total else 0,
        "pilots": deal_counts["pilot"],
        "pilots_due_30": due_30,
        "try_and_buy": deal_counts["try_and_buy"],
        "tnb_due_month": tnb_month,
        "demo": deal_counts["demo"],
        "unassigned": deal_counts["unassigned"],
        "new_30": new30,
    }
    top_customers = [
        [v["label"], v["n"]]
        for v in sorted(cust_units.values(), key=lambda v: -v["n"])[:5]
    ]
    can_edit = bool(user.is_editor_or_above)
    hidden_sets = load_hidden(db)
    needs = _needs_location(db, by_item, by_edge, hidden_sets,
                            user.has_sensitive_customers_access) if can_edit else []

    payload = {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "metrics": metrics,
            "dealCounts": deal_counts,
            "unitCounts": unit_counts,
            "statusCounts": status_counts,
            "topCustomers": top_customers,
            "needsLocation": {  # editor-only: [] otherwise
                "count": len(needs),
                "fixable": [u for u in needs if u["hasLocation"]][:50],
                "fixableCount": sum(1 for u in needs if u["hasLocation"]),
                "placeless": [u for u in needs if not u["hasLocation"]][:50],
                "placelessCount": sum(1 for u in needs if not u["hasLocation"]),
            },
            "colors": {"deal": DEAL_COLORS, "unit": UNIT_COLORS, "status": STATUS_COLORS},
            "labels": {"deal": DEAL_LABELS, "unit": UNIT_LABELS},
            "canEdit": bool(user.is_editor_or_above),
        },
    }
    if user.is_editor_or_above:
        payload["meta"]["hidden"] = [
            {"level": r.level, "key": r.key, "label": r.label or r.key}
            for r in db.query(MapVisibility).order_by(MapVisibility.level, MapVisibility.key)
        ]
    return JSONResponse(payload)


@router.post("/visibility")
async def map_visibility_toggle(request: Request, db: Session = Depends(get_db),
                                user: User = Depends(require_editor)):
    body = await request.json()
    level = (body.get("level") or "").strip()
    key = (body.get("key") or "").strip()
    label = (body.get("label") or "").strip() or None
    hide = bool(body.get("hidden", True))
    if level not in ("customer", "site", "unit") or not key:
        return JSONResponse(status_code=400, content={"error": "level must be customer|site|unit and key is required"})
    if level in ("customer", "site"):
        key = norm_key(key)
    key = key[:512]
    if label:
        label = label[:512]
    existing = db.query(MapVisibility).filter(
        MapVisibility.level == level, MapVisibility.key == key).first()
    changed = False
    if hide and existing is None:
        db.add(MapVisibility(level=level, key=key, label=label, hidden_by=user.username))
        changed = True
    elif not hide and existing is not None:
        db.delete(existing)
        changed = True
    if changed:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # concurrent hide of the same key: already done
        log_event(db, "map_visibility", request=request, user_id=user.id,
                  target_table="map_visibility", action="hide" if hide else "unhide",
                  details=f"{level} {label or key} {'hidden from' if hide else 'restored to'} the map")
    return JSONResponse({"status": "ok", "level": level, "key": key, "hidden": hide})


@router.post("/set-location")
async def map_set_location(request: Request, db: Session = Depends(get_db),
                           user: User = Depends(require_editor)):
    """Minimal fix-location flow: the old needs-location list was display
    only (no route anywhere wrote coordinates), so the Fix link needs this."""
    body = await request.json()
    kind = body.get("kind")
    try:
        unit_id = int(body.get("id"))
        lat = float(body.get("lat"))
        lng = float(body.get("lng"))
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "id, lat and lng are required"})
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return JSONResponse(status_code=400, content={"error": "coordinates out of range"})
    # Fix-only semantics: this endpoint fills MISSING coordinates. It never
    # overwrites existing ones (no other coordinate editor exists yet, so an
    # overwrite would be irreversible) and never flips an explicit
    # show_on_map=False on legacy rows (that boolean is the privacy control).
    if kind == "edge_box":
        eb = db.query(EdgeBox).filter(EdgeBox.id == unit_id).first()
        if not eb:
            return JSONResponse(status_code=404, content={"error": "edge box not found"})
        if eb.geo_lat is not None and eb.geo_lng is not None:
            return JSONResponse(status_code=400, content={"error": "this unit already has coordinates"})
        eb.geo_lat, eb.geo_lng = lat, lng
        target = eb.serial or f"edge box {unit_id}"
    elif kind == "item":
        item = db.query(Item).filter(Item.id == unit_id).first()
        if not item:
            return JSONResponse(status_code=404, content={"error": "item not found"})
        if str(item.item_category or "") not in PRODUCT_CATEGORIES:
            return JSONResponse(status_code=400, content={"error": "only product units appear on the map"})
        if item.location_id is None:
            return JSONResponse(status_code=400, content={
                "error": "assign the item to a place first; coordinates live on the place"})
        place = db.query(Site).filter(Site.id == item.location_id).first()
        if place.geo_lat is not None and place.geo_lng is not None:
            return JSONResponse(status_code=400, content={
                "error": "this place already has coordinates (shared by all units there)"})
        place.geo_lat, place.geo_lng = lat, lng
        place.show_on_map = True  # first geocode implies mapping intent
        target = item.item_sn or f"item {unit_id}"
    else:
        return JSONResponse(status_code=400, content={"error": "kind must be item or edge_box"})
    db.commit()
    log_event(db, "map_set_location", request=request, user_id=user.id,
              target_table=kind, target_id=unit_id, action="update",
              details=f"map coordinates set for {target}: {lat}, {lng}")
    return JSONResponse({"status": "ok"})
