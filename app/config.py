"""Application configuration loaded from environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the repo root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class Settings:
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://inventory_user:password@localhost:5432/hardware_inventory",
    )

    # Credentials vault
    CREDENTIAL_ENCRYPTION_KEY: str = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")

    # Session (signed cookies)
    SESSION_SECRET_KEY: str = os.getenv(
        "SESSION_SECRET_KEY",
        "CHANGE-ME-generate-with-python-c-import-secrets-secrets-token-hex-32",
    )

    # Scanner
    SCANNER_MODE: str = os.getenv("SCANNER_MODE", "local")  # "local" or "remote"
    SCAN_SUBNETS: list[str] = [
        s.strip()
        for s in os.getenv("SCAN_SUBNETS", "192.0.2.0/24").split(",")
    ]
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "120"))
    SCANNER_ID: str = os.getenv("SCANNER_ID", "lab-nuc")

    # Remote agent
    CENTRAL_API_URL: str = os.getenv("CENTRAL_API_URL", "")
    SCANNER_API_KEY: str = os.getenv("SCANNER_API_KEY", "")

    # Root path prefix (for reverse proxy sub-path deployment, e.g. "/inventory")
    ROOT_PATH: str = os.getenv("ROOT_PATH", "")

    # Set True when serving behind HTTPS (Cloudflare Tunnel, cloud VM).
    # Marks session cookie as Secure — browsers will NOT send it over plain HTTP.
    # Keep False for LAN-only HTTP deployment and for E2E tests.
    HTTPS_ONLY: bool = os.getenv("HTTPS_ONLY", "false").lower() == "true"

    # Slack webhook (optional, for team channel alerts)
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
    # Separate webhook for E2E test notifications (private channel, only Justin)
    SLACK_TEST_WEBHOOK_URL: str = os.getenv("SLACK_TEST_WEBHOOK_URL", "")
    # Slack bot token for per-user DMs (xoxb-...)
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_ADMIN_WEBHOOK_URL: str = os.getenv("SLACK_ADMIN_WEBHOOK_URL", "")

    # Intune (Microsoft Graph API)
    INTUNE_TENANT_ID: str = os.getenv("INTUNE_TENANT_ID", "")
    INTUNE_CLIENT_ID: str = os.getenv("INTUNE_CLIENT_ID", "")
    INTUNE_CLIENT_SECRET: str = os.getenv("INTUNE_CLIENT_SECRET", "")
    INTUNE_AUTO_SYNC: bool = os.getenv("INTUNE_AUTO_SYNC", "false").lower() == "true"

    # Photo uploads (intake label photos)
    PHOTO_UPLOAD_DIR: str = os.getenv("PHOTO_UPLOAD_DIR", "data/photos")

    # Zendesk Integration
    ZENDESK_SUBDOMAIN: str = os.getenv("ZENDESK_SUBDOMAIN", "")
    ZENDESK_EMAIL: str = os.getenv("ZENDESK_EMAIL", "")
    ZENDESK_API_TOKEN: str = os.getenv("ZENDESK_API_TOKEN", "")

    # Email / SMTP (for notification email delivery channel)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "Asset Tracker <noreply@example.com>")
    SMTP_TLS: bool = os.getenv("SMTP_TLS", "true").lower() == "true"

    # Spreadsheet import
    SPREADSHEET_PATH: str = os.getenv(
        "SPREADSHEET_PATH",
        str(Path(__file__).resolve().parent.parent
            / "data" / "Inventory_Tracker_Export.xlsx"),
    )


settings = Settings()
