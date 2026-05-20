"""Procurement and vendor analytics routes."""

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pathlib import Path
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_financial, User
from ..config import settings
from ..database import get_db
from ..models import (
    TABLE_MODELS, TABLE_DISPLAY_NAMES,
    DeviceWarranty, WarrantyClaim, VendorTrial, DeviceDisposition,
    get_display_name, get_serial,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP


@router.get("/admin/procurement")
def procurement_analytics(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_financial),
):
    """Render procurement and vendor analytics page (requires financial permission)."""

    # Initialize counters
    total_cost = Decimal('0')
    device_count = 0
    ytd_cost = Decimal('0')
    ytd_device_count = 0
    vendor_totals = {}  # {vendor: {'cost': Decimal, 'count': int, 'most_recent': date}}
    category_totals = {}  # {category: {'cost': Decimal, 'count': int}}
    recent_purchases_list = []

    # Current year for YTD calculation
    current_year = date.today().year
    thirty_days_ago = date.today() - timedelta(days=30)

    # Iterate through all inventory tables
    for table_name, model in TABLE_MODELS.items():
        if not hasattr(model, 'vendor') or not hasattr(model, 'purchase_price'):
            continue

        # Query devices with procurement data
        devices = (
            db.query(model)
            .filter(
                model.vendor.isnot(None),
                model.purchase_price.isnot(None),
                model.purchase_price > 0
            )
            .all()
        )

        display_name = TABLE_DISPLAY_NAMES.get(table_name, table_name)

        for device in devices:
            price = Decimal(str(device.purchase_price or 0))
            vendor = device.vendor
            purchase_date = device.purchase_date

            # Total cost
            total_cost += price
            device_count += 1

            # YTD cost
            if purchase_date and purchase_date.year == current_year:
                ytd_cost += price
                ytd_device_count += 1

            # Vendor totals
            if vendor:
                if vendor not in vendor_totals:
                    vendor_totals[vendor] = {'cost': Decimal('0'), 'count': 0, 'most_recent': None}
                vendor_totals[vendor]['cost'] += price
                vendor_totals[vendor]['count'] += 1
                if purchase_date:
                    if vendor_totals[vendor]['most_recent'] is None or purchase_date > vendor_totals[vendor]['most_recent']:
                        vendor_totals[vendor]['most_recent'] = purchase_date

            # Category totals
            if display_name not in category_totals:
                category_totals[display_name] = {'cost': Decimal('0'), 'count': 0}
            category_totals[display_name]['cost'] += price
            category_totals[display_name]['count'] += 1

            # Recent purchases (last 30 days)
            if purchase_date and purchase_date >= thirty_days_ago:
                device_name = getattr(device, 'model', None) or getattr(device, 'serial', 'Unknown')
                method_display = _get_procurement_method_display(device.procurement_method)
                recent_purchases_list.append({
                    'purchase_date': purchase_date.strftime('%Y-%m-%d'),
                    'device_name': device_name,
                    'category': display_name,
                    'vendor': vendor,
                    'cost': float(price),
                    'method_display': method_display,
                    'purchase_order': device.purchase_order,
                })

    # Calculate vendor costs list
    vendor_costs = []
    for vendor, data in vendor_totals.items():
        avg_cost = float(data['cost']) / data['count'] if data['count'] > 0 else 0
        percentage = (float(data['cost']) / float(total_cost) * 100) if total_cost > 0 else 0
        most_recent_str = data['most_recent'].strftime('%Y-%m-%d') if data['most_recent'] else 'Unknown'

        vendor_costs.append({
            'vendor': vendor,
            'total_cost': float(data['cost']),
            'device_count': data['count'],
            'avg_cost': avg_cost,
            'percentage': percentage,
            'most_recent': most_recent_str,
        })

    # Sort by total cost descending
    vendor_costs.sort(key=lambda x: x['total_cost'], reverse=True)

    # Calculate category costs list
    category_costs = []
    for category, data in category_totals.items():
        avg_cost = float(data['cost']) / data['count'] if data['count'] > 0 else 0
        percentage = (float(data['cost']) / float(total_cost) * 100) if total_cost > 0 else 0

        category_costs.append({
            'category': category,
            'total_cost': float(data['cost']),
            'device_count': data['count'],
            'avg_cost': avg_cost,
            'percentage': percentage,
        })

    # Sort by total cost descending
    category_costs.sort(key=lambda x: x['total_cost'], reverse=True)

    # Sort recent purchases by date descending
    recent_purchases_list.sort(key=lambda x: x['purchase_date'], reverse=True)

    # Calculate vendor performance metrics
    vendor_performance = _calculate_vendor_performance(db, vendor_totals)

    # Calculate averages
    avg_unit_cost = float(total_cost) / device_count if device_count > 0 else 0
    avg_vendor_cost = float(total_cost) / len(vendor_totals) if vendor_totals else 0
    avg_vendor_cost_display = f"${avg_vendor_cost:,.2f}"

    return templates.TemplateResponse("admin_procurement.html", {
        "request": request,
        "user": user,
        "total_cost": float(total_cost),
        "device_count": device_count,
        "ytd_cost": float(ytd_cost),
        "ytd_device_count": ytd_device_count,
        "avg_unit_cost": avg_unit_cost,
        "vendor_count": len(vendor_totals),
        "avg_vendor_cost_display": avg_vendor_cost_display,
        "vendor_costs": vendor_costs,
        "category_costs": category_costs,
        "recent_purchases": recent_purchases_list[:20],  # Limit to 20 most recent
        "vendor_performance": vendor_performance,
    })


def _calculate_vendor_performance(db: Session, vendor_totals: dict) -> list:
    """Calculate vendor performance metrics based on warranty claims, trials, and device status."""
    vendor_performance = []

    for vendor in vendor_totals.keys():
        # Count total devices from vendor
        total_devices = vendor_totals[vendor]['count']

        # Count warranty claims for this vendor
        warranty_claims = 0
        for table_name, model in TABLE_MODELS.items():
            if hasattr(model, 'vendor'):
                devices_with_claims = (
                    db.query(model)
                    .join(WarrantyClaim, WarrantyClaim.device_id == model.id)
                    .filter(
                        model.vendor == vendor,
                        WarrantyClaim.target_table == table_name
                    )
                    .count()
                )
                warranty_claims += devices_with_claims

        # Calculate claim rate
        claim_rate = (warranty_claims / total_devices * 100) if total_devices > 0 else 0

        # Count trial outcomes for this vendor
        trial_purchased = db.query(VendorTrial).filter(
            VendorTrial.vendor == vendor,
            VendorTrial.trial_status == 'approved_purchase'
        ).count()

        trial_returned = db.query(VendorTrial).filter(
            VendorTrial.vendor == vendor,
            VendorTrial.trial_status == 'returned'
        ).count()

        # Calculate quality score (0-100)
        # Formula: Start at 100, deduct for high claim rate, add for successful trials
        quality_score = 100

        # Deduct for warranty claims (up to -30 points)
        quality_score -= min(claim_rate * 1.5, 30)

        # Add for successful trials (up to +10 points)
        if trial_purchased + trial_returned > 0:
            trial_success_rate = trial_purchased / (trial_purchased + trial_returned)
            quality_score += trial_success_rate * 10

        # Ensure score stays within 0-100
        quality_score = max(0, min(100, quality_score))

        vendor_performance.append({
            'vendor': vendor,
            'total_devices': total_devices,
            'warranty_claims': warranty_claims,
            'claim_rate': claim_rate,
            'trial_purchased': trial_purchased,
            'trial_returned': trial_returned,
            'quality_score': int(quality_score),
        })

    # Sort by quality score descending
    vendor_performance.sort(key=lambda x: x['quality_score'], reverse=True)

    return vendor_performance


def _get_procurement_method_display(method: str) -> str:
    """Convert procurement method code to display name."""
    method_map = {
        'direct_purchase': 'Direct Purchase',
        'rental': 'Rental/Lease',
        'donation': 'Donation',
        'transfer': 'Transfer',
        'trial': 'Trial',
        'warranty_replacement': 'Warranty',
    }
    return method_map.get(method, method or 'Unknown')


@router.get("/admin/procurement/export")
def export_procurement(
    request: Request,
    format: str = "xlsx",
    db: Session = Depends(get_db),
    user: User = Depends(require_financial),
):
    """Export procurement data to Excel or CSV (requires financial permission)."""
    rows = []

    for table_name, model in TABLE_MODELS.items():
        if not hasattr(model, 'vendor') or not hasattr(model, 'purchase_price'):
            continue

        devices = (
            db.query(model)
            .filter(
                model.vendor.isnot(None),
                model.purchase_price.isnot(None),
                model.purchase_price > 0,
            )
            .all()
        )

        display_name = TABLE_DISPLAY_NAMES.get(table_name, table_name)

        for device in devices:
            device_name = getattr(device, 'model', None) or getattr(device, 'serial', 'Unknown')
            rows.append({
                "Category": display_name,
                "Vendor": device.vendor or "",
                "Device": device_name,
                "Purchase Date": device.purchase_date.strftime('%Y-%m-%d') if device.purchase_date else "",
                "Price": float(device.purchase_price or 0),
                "PO Number": getattr(device, 'purchase_order', '') or "",
                "Invoice": getattr(device, 'invoice_number', '') or "",
                "Method": _get_procurement_method_display(getattr(device, 'procurement_method', '')),
            })

    # Sort by purchase date descending
    rows.sort(key=lambda r: r["Purchase Date"], reverse=True)

    if not rows:
        rows = [{"Category": "", "Vendor": "", "Device": "", "Purchase Date": "",
                 "Price": 0, "PO Number": "", "Invoice": "", "Method": ""}]

    if format == "csv":
        return _export_procurement_csv(rows)
    return _export_procurement_excel(rows)


def _export_procurement_csv(rows: list[dict]) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="procurement_{timestamp}.csv"'},
    )


def _export_procurement_excel(rows: list[dict]) -> StreamingResponse:
    wb = Workbook()
    ws = wb.active
    ws.title = "Procurement"

    headers = list(rows[0].keys())
    header_fill = PatternFill(start_color="157ca4", end_color="157ca4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font

    for row_idx, row_data in enumerate(rows, 2):
        for col_idx, header in enumerate(headers, 1):
            value = row_data[header]
            if header == "Price" and isinstance(value, (int, float)):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.number_format = '$#,##0.00'
            else:
                ws.cell(row=row_idx, column=col_idx, value=value)

    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if cell.value and len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:
                pass
        ws.column_dimensions[column_letter].width = min(max_length + 2, 50)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="procurement_{timestamp}.xlsx"'},
    )


# ---------------------------------------------------------------------------
# Vendor Detail Page
# ---------------------------------------------------------------------------

def _quality_rating(score: int) -> str:
    """Convert quality score to rating label."""
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    return "Needs Review"


@router.get("/admin/vendors/{vendor_name}")
def vendor_detail(
    vendor_name: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_financial),
):
    """Vendor detail page: all devices, warranties, trials, and performance for a vendor."""
    from urllib.parse import unquote
    vendor_name = unquote(vendor_name)

    # Collect all devices from this vendor across all tables
    devices = []
    total_cost = Decimal("0")
    for table_name, model in TABLE_MODELS.items():
        if not hasattr(model, "vendor"):
            continue
        matches = db.query(model).filter(model.vendor == vendor_name).all()
        display = TABLE_DISPLAY_NAMES.get(table_name, table_name)
        for d in matches:
            price = Decimal(str(d.purchase_price or 0)) if hasattr(d, "purchase_price") else Decimal("0")
            total_cost += price
            devices.append({
                "id": d.id,
                "table": table_name,
                "category": display,
                "name": get_display_name(d),
                "serial": get_serial(d),
                "status": getattr(d, "status", "-"),
                "price": float(price),
                "purchase_date": (d.purchase_date.strftime("%Y-%m-%d") if hasattr(d, "purchase_date") and d.purchase_date else "-"),
            })

    # Warranties for this vendor
    warranties = db.query(DeviceWarranty).filter(DeviceWarranty.vendor == vendor_name).all()
    active_warranties = sum(1 for w in warranties if w.warranty_end and w.warranty_end >= date.today())
    expired_warranties = len(warranties) - active_warranties

    # Warranty claims
    warranty_ids = [w.id for w in warranties]
    claims = db.query(WarrantyClaim).filter(WarrantyClaim.warranty_id.in_(warranty_ids)).all() if warranty_ids else []
    claim_rate = (len(claims) / len(devices) * 100) if devices else 0

    # Trials
    trials = db.query(VendorTrial).filter(VendorTrial.vendor == vendor_name).all()
    trial_purchased = sum(1 for t in trials if t.trial_status == "approved_purchase")
    trial_returned = sum(1 for t in trials if t.trial_status == "returned")
    trial_active = sum(1 for t in trials if t.trial_status == "active")

    # Quality score (same formula as procurement analytics)
    quality_score = 100
    quality_score -= min(claim_rate * 1.5, 30)
    if trial_purchased + trial_returned > 0:
        quality_score += (trial_purchased / (trial_purchased + trial_returned)) * 10
    quality_score = max(0, min(100, int(quality_score)))

    return templates.TemplateResponse("vendor_detail.html", {
        "request": request,
        "user": user,
        "vendor_name": vendor_name,
        "devices": devices,
        "device_count": len(devices),
        "total_cost": float(total_cost),
        "active_warranties": active_warranties,
        "expired_warranties": expired_warranties,
        "warranty_count": len(warranties),
        "claim_count": len(claims),
        "claim_rate": claim_rate,
        "trials": trials,
        "trial_purchased": trial_purchased,
        "trial_returned": trial_returned,
        "trial_active": trial_active,
        "quality_score": quality_score,
        "quality_rating": _quality_rating(quality_score),
    })
