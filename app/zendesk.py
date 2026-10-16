"""Zendesk API client for Shelf2Site.

Handles authentication, request/response, error handling, and rate limit
retry with exponential backoff. Uses httpx for async HTTP requests.

Usage:
    from app.zendesk import get_zendesk_client

    client = get_zendesk_client()
    if client is None:
        # Zendesk not configured
        ...
    else:
        orgs = await client.list_organizations()
        tickets = await client.list_tickets(page=1, per_page=25)
        await client.close()
"""

import asyncio
import base64
import logging
from typing import Any, Optional

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class ZendeskError(Exception):
    def __init__(self, status_code: int, message: str, response_body: Any = None):
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"Zendesk API error {status_code}: {message}")


class ZendeskRateLimitError(ZendeskError):
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(429, f"Rate limited. Retry after {retry_after}s")


class ZendeskClient:
    """Async Zendesk API v2 client with Basic auth (email/token)."""

    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1.0

    def __init__(self, subdomain: str, email: str, api_token: str):
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        credentials = f"{email}/token:{api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self._headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers=self._headers,
        )

    async def close(self):
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        backoff = self.INITIAL_BACKOFF

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                resp = await self._client.request(
                    method, url, params=params, json=json_body,
                )

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    if attempt < self.MAX_RETRIES:
                        logger.warning(
                            "Zendesk rate limited. Waiting %ds (attempt %d/%d)",
                            retry_after, attempt + 1, self.MAX_RETRIES,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    raise ZendeskRateLimitError(retry_after)

                if resp.status_code >= 400:
                    try:
                        body = resp.json()
                    except Exception:
                        body = resp.text
                    raise ZendeskError(resp.status_code, str(body), body)

                if resp.status_code == 204:
                    return {}

                return resp.json()

            except httpx.RequestError as exc:
                if attempt < self.MAX_RETRIES:
                    logger.warning(
                        "Zendesk request error: %s. Retrying in %ss (attempt %d)",
                        exc, backoff, attempt + 1,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise ZendeskError(0, f"Connection error: {exc}")

        raise ZendeskError(0, "Max retries exceeded")

    # ----- Connectivity -----

    async def test_connection(self) -> dict:
        return await self._request("GET", "/users/me.json")

    # ----- Organizations -----

    async def list_organizations(self, page: int = 1, per_page: int = 100) -> dict:
        return await self._request(
            "GET", "/organizations.json",
            params={"page": page, "per_page": per_page},
        )

    async def get_organization(self, org_id: int) -> dict:
        return await self._request("GET", f"/organizations/{org_id}.json")

    # ----- Tickets -----

    async def list_tickets(
        self, page: int = 1, per_page: int = 25,
        sort_by: str = "updated_at", sort_order: str = "desc",
    ) -> dict:
        return await self._request(
            "GET", "/tickets.json",
            params={
                "page": page, "per_page": per_page,
                "sort_by": sort_by, "sort_order": sort_order,
            },
        )

    async def get_ticket(self, ticket_id: int) -> dict:
        return await self._request("GET", f"/tickets/{ticket_id}.json")

    async def search_tickets(self, query: str, page: int = 1) -> dict:
        return await self._request(
            "GET", "/search.json",
            params={"query": f"type:ticket {query}", "page": page},
        )

    # ----- Users -----

    async def list_users(self, page: int = 1, per_page: int = 100) -> dict:
        return await self._request(
            "GET", "/users.json",
            params={"page": page, "per_page": per_page},
        )

    # ----- Ticket Updates -----

    async def add_ticket_comment(
        self, ticket_id: int, comment: str, public: bool = False,
    ) -> dict:
        """Add a comment to a Zendesk ticket.

        Args:
            ticket_id: Zendesk ticket ID.
            comment: Comment body text.
            public: If True, visible to requester. If False, internal note.
        """
        return await self._request(
            "PUT",
            f"/tickets/{ticket_id}.json",
            json_body={
                "ticket": {
                    "comment": {
                        "body": comment,
                        "public": public,
                    }
                }
            },
        )

    async def update_ticket_status(
        self, ticket_id: int, status: str, comment: str = None,
    ) -> dict:
        """Update a Zendesk ticket's status, optionally with a comment.

        Args:
            ticket_id: Zendesk ticket ID.
            status: New status (new/open/pending/hold/solved/closed).
            comment: Optional comment to include with the status change.
        """
        ticket_body: dict = {"status": status}
        if comment:
            ticket_body["comment"] = {"body": comment, "public": False}
        return await self._request(
            "PUT",
            f"/tickets/{ticket_id}.json",
            json_body={"ticket": ticket_body},
        )

    # ----- Ticket Fields -----

    async def list_ticket_fields(self) -> dict:
        return await self._request("GET", "/ticket_fields.json")


def get_zendesk_client() -> Optional[ZendeskClient]:
    """Factory: returns a ZendeskClient if configured, else None."""
    if not all([
        settings.ZENDESK_SUBDOMAIN,
        settings.ZENDESK_EMAIL,
        settings.ZENDESK_API_TOKEN,
    ]):
        return None
    return ZendeskClient(
        subdomain=settings.ZENDESK_SUBDOMAIN,
        email=settings.ZENDESK_EMAIL,
        api_token=settings.ZENDESK_API_TOKEN,
    )
