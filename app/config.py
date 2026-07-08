"""Application configuration loaded from environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the repo root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class Settings:
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Define it in the .env file "
            "(see .env.template) before starting the app."
        )

    # Credentials vault
    CREDENTIAL_ENCRYPTION_KEY: str = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")

    # Session (signed cookies)
    SESSION_SECRET_KEY: str = os.getenv(
        "SESSION_SECRET_KEY",
        "CHANGE-ME-generate-with-python-c-import-secrets-secrets-token-hex-32",
    )

    # Root path prefix (for reverse proxy sub-path deployment, e.g. "/inventory")
    ROOT_PATH: str = os.getenv("ROOT_PATH", "")

    # Base URL the app is reached at (used to build absolute links in notifications)
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://192.0.2.10:8100/assettracker")

    # Set True when serving behind HTTPS (Cloudflare Tunnel, cloud VM).
    # Marks session cookie as Secure — browsers will NOT send it over plain HTTP.
    # Keep False for LAN-only HTTP deployment and for E2E tests.
    HTTPS_ONLY: bool = os.getenv("HTTPS_ONLY", "false").lower() == "true"

    # Password expiry policy - 6-month rotation with a 7-day warning. Reuses the existing
    # must_change_password forced-change flow; display/enforcement only.
    # Password expiry DISABLED per NIST Rev 4 (no mandatory periodic rotation). 0 = disabled;
    # set this > 0 to re-enable the rotation. The forced-change machinery (admin reset) is unaffected.
    PASSWORD_MAX_AGE_DAYS: int = int(os.getenv("PASSWORD_MAX_AGE_DAYS", "0"))
    PASSWORD_WARN_DAYS: int = int(os.getenv("PASSWORD_WARN_DAYS", "7"))
    # NIST policy: length + an offline breached/common-password blocklist (no composition rules).
    PASSWORD_MIN_LENGTH: int = int(os.getenv("PASSWORD_MIN_LENGTH", "15"))
    PASSWORD_BLOCKLIST_PATH: str = os.getenv("PASSWORD_BLOCKLIST_PATH", "data/security/password-blocklist.txt")

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
    # Cert report uploads (SMART reports, QA sheets, per box)
    CERT_UPLOAD_DIR: str = os.getenv("CERT_UPLOAD_DIR", "data/cert-reports")
    # Install cert uploads (single post-install PDF, per deployment)
    INSTALL_CERT_UPLOAD_DIR: str = os.getenv("INSTALL_CERT_UPLOAD_DIR", "data/install-cert-reports")
    # C2C cert source files + generated composite (5b/5c); bytes on disk, metadata in DB
    C2C_CERT_UPLOAD_DIR: str = os.getenv("C2C_CERT_UPLOAD_DIR", "data/c2c-cert-reports")

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
