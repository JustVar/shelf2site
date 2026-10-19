"""Zendesk integration routes -- admin settings page and API endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth import require_system_admin, User
from ..config import settings
from ..localtime import register
from ..zendesk import get_zendesk_client, ZendeskError

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
BP = settings.ROOT_PATH.rstrip("/")
templates.env.globals["base_path"] = BP
register(templates.env)


@router.get("/admin/zendesk", response_class=HTMLResponse)
async def zendesk_settings_page(
    request: Request,
    user: User = Depends(require_system_admin),
):
    is_configured = bool(
        settings.ZENDESK_SUBDOMAIN
        and settings.ZENDESK_EMAIL
        and settings.ZENDESK_API_TOKEN
    )
    return templates.TemplateResponse(request, "admin_zendesk.html", {
        "request": request,
        "user": user,
        "is_configured": is_configured,
        "zendesk_subdomain": settings.ZENDESK_SUBDOMAIN or "(not set)",
        "zendesk_email": settings.ZENDESK_EMAIL or "(not set)",
        "zendesk_token_set": bool(settings.ZENDESK_API_TOKEN),
    })


@router.post("/api/zendesk/test")
async def test_zendesk_connection(
    user: User = Depends(require_system_admin),
):
    client = get_zendesk_client()
    if client is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Zendesk not configured. Set ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN in .env"},
        )
    try:
        result = await client.test_connection()
        user_info = result.get("user", {})
        return JSONResponse(content={
            "status": "connected",
            "zendesk_user": {
                "name": user_info.get("name"),
                "email": user_info.get("email"),
                "role": user_info.get("role"),
                "time_zone": user_info.get("time_zone"),
            },
        })
    except ZendeskError as e:
        return JSONResponse(
            status_code=e.status_code or 500,
            content={"error": f"Zendesk API error: {e.message}"},
        )
    finally:
        await client.close()


@router.get("/api/zendesk/organizations")
async def list_zendesk_organizations(
    page: int = 1,
    per_page: int = 25,
    user: User = Depends(require_system_admin),
):
    client = get_zendesk_client()
    if client is None:
        return JSONResponse(status_code=400, content={"error": "Zendesk not configured"})
    try:
        result = await client.list_organizations(page=page, per_page=per_page)
        return JSONResponse(content=result)
    except ZendeskError as e:
        return JSONResponse(status_code=e.status_code or 500, content={"error": e.message})
    finally:
        await client.close()


@router.get("/api/zendesk/tickets")
async def list_zendesk_tickets(
    page: int = 1,
    per_page: int = 25,
    user: User = Depends(require_system_admin),
):
    client = get_zendesk_client()
    if client is None:
        return JSONResponse(status_code=400, content={"error": "Zendesk not configured"})
    try:
        result = await client.list_tickets(page=page, per_page=per_page)
        return JSONResponse(content=result)
    except ZendeskError as e:
        return JSONResponse(status_code=e.status_code or 500, content={"error": e.message})
    finally:
        await client.close()


@router.get("/api/zendesk/ticket-fields")
async def list_zendesk_ticket_fields(
    user: User = Depends(require_system_admin),
):
    client = get_zendesk_client()
    if client is None:
        return JSONResponse(status_code=400, content={"error": "Zendesk not configured"})
    try:
        result = await client.list_ticket_fields()
        return JSONResponse(content=result)
    except ZendeskError as e:
        return JSONResponse(status_code=e.status_code or 500, content={"error": e.message})
    finally:
        await client.close()
