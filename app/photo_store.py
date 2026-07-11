"""Unit-photo storage: validation, EXIF handling, thumbnails (shipment-photos slice).

Every accepted image is RE-ENCODED through Pillow before it touches disk:
  * EXIF orientation is applied (ImageOps.exif_transpose) so rotation is
    baked into the pixels;
  * the re-encode drops ALL metadata including GPS — dossier PDFs leave
    the building, so location EXIF must never survive the upload;
  * a thumbnail is generated server-side next to the original.

HEIC is rejected with a clear error: pillow-heif is not in the image and
requirements changes need a container rebuild (spec: "accepted if cheap,
else a clear error" — it is not cheap).

Files live under PHOTO_UPLOAD_DIR/unit/ — the same bind-mounted tree the
intake photos use, already covered by the nightly files backup.
"""
import io
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from .config import settings

ACCEPTED_TYPES = {"image/jpeg", "image/png", "image/webp"}
HEIC_TYPES = {"image/heic", "image/heif"}
THUMB_EDGE = 480          # longest edge of the thumbnail
JPEG_QUALITY = 88


class PhotoValidationError(ValueError):
    """User-facing upload rejection (maps to a 400)."""


def unit_photo_root() -> Path:
    return Path(settings.PHOTO_UPLOAD_DIR) / "unit"


def _exif_taken_at(img: Image.Image) -> datetime | None:
    """DateTimeOriginal (0x9003) before the re-encode drops it."""
    try:
        raw = (img.getexif().get_ifd(0x8769) or {}).get(0x9003)
        if raw:
            return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def save_unit_photo(content: bytes, content_type: str, original_name: str) -> dict:
    """Validate + re-encode + thumbnail one upload.

    Returns {file_path, thumb_path (both relative to PHOTO_UPLOAD_DIR),
    taken_at (datetime|None), file_size}. Raises PhotoValidationError with
    a user-facing message on rejection.
    """
    max_bytes = settings.UNIT_PHOTO_MAX_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise PhotoValidationError(
            f"Photo is {len(content) / 1024 / 1024:.1f} MB — the limit is "
            f"{settings.UNIT_PHOTO_MAX_MB} MB. Export a smaller copy and retry.")
    ctype = (content_type or "").lower()
    if ctype in HEIC_TYPES or (original_name or "").lower().endswith((".heic", ".heif")):
        raise PhotoValidationError(
            "HEIC photos aren't supported yet — set the phone camera to JPEG "
            "(Settings → Camera → Formats → Most Compatible) or export as JPEG.")
    if ctype not in ACCEPTED_TYPES:
        raise PhotoValidationError(
            f"Unsupported file type '{content_type}'. Use JPEG, PNG or WebP.")

    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        raise PhotoValidationError("That file could not be read as an image.")

    taken_at = _exif_taken_at(img)
    img = ImageOps.exif_transpose(img)   # bake orientation into pixels
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    root = unit_photo_root()
    (root / "thumbs").mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex
    file_rel = f"unit/{stem}.jpg"
    thumb_rel = f"unit/thumbs/{stem}.jpg"

    # Re-encode WITHOUT exif → GPS and every other tag is gone.
    img.save(Path(settings.PHOTO_UPLOAD_DIR) / file_rel, "JPEG",
             quality=JPEG_QUALITY, optimize=True)

    thumb = img.copy()
    thumb.thumbnail((THUMB_EDGE, THUMB_EDGE))
    thumb.save(Path(settings.PHOTO_UPLOAD_DIR) / thumb_rel, "JPEG",
               quality=80, optimize=True)

    size = (Path(settings.PHOTO_UPLOAD_DIR) / file_rel).stat().st_size
    return {"file_path": file_rel, "thumb_path": thumb_rel,
            "taken_at": taken_at, "file_size": size}
