"""OCR processor for extracting device information from label photos.

Uses Tesseract OCR to extract:
- Serial numbers
- Model numbers
- MAC addresses
- Part numbers
- Manufacturer names
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ExtractedData:
    """Data extracted from device label photo via OCR."""
    serial: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    mac_address: Optional[str] = None
    part_number: Optional[str] = None
    raw_text: str = ""


def extract_from_image(image_path: Path) -> ExtractedData:
    """Extract device information from an image using OCR.

    Args:
        image_path: Path to image file

    Returns:
        ExtractedData object with extracted fields
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.error("pytesseract or Pillow not installed")
        return ExtractedData(raw_text="Error: OCR dependencies not installed")

    try:
        # Load and preprocess image
        image = Image.open(image_path)

        # Convert to grayscale for better OCR
        if image.mode != 'L':
            image = image.convert('L')

        # Run OCR
        text = pytesseract.image_to_string(image)

        logger.debug(f"OCR extracted text: {text}")

        # Extract structured data from text
        extracted = ExtractedData(raw_text=text)

        extracted.serial = _extract_serial(text)
        extracted.model = _extract_model(text)
        extracted.mac_address = _extract_mac(text)
        extracted.part_number = _extract_part_number(text)
        extracted.manufacturer = _extract_manufacturer(text)

        return extracted

    except Exception as e:
        logger.error(f"OCR processing failed: {e}", exc_info=True)
        return ExtractedData(raw_text=f"Error: {str(e)}")


def _extract_serial(text: str) -> Optional[str]:
    """Extract serial number from OCR text.

    Looks for patterns like:
    - S/N: ABC123456789
    - Serial: ABC123456789
    - Serial Number: ABC123456789
    - SN: ABC123456789
    """
    patterns = [
        r'(?:S/?N|Serial(?:\s+Number)?)\s*[:\-]?\s*([A-Z0-9\-]{6,30})',
        r'(?:Serial|SN)\s*[:\-]?\s*([A-Z0-9\-]{6,30})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            serial = match.group(1).strip()
            # Clean up common OCR errors
            serial = serial.replace(' ', '').replace('|', '').replace('I', '1').replace('O', '0')
            if len(serial) >= 6:
                return serial

    return None


def _extract_model(text: str) -> Optional[str]:
    """Extract model number from OCR text.

    Looks for patterns like:
    - Model: ABC-123
    - Model No: ABC-123
    - Model Number: ABC-123
    """
    patterns = [
        r'Model(?:\s+(?:No|Number))?\s*[:\-]?\s*([A-Z0-9\-]{3,30})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            model = match.group(1).strip()
            return model

    return None


def _extract_mac(text: str) -> Optional[str]:
    """Extract MAC address from OCR text.

    Looks for standard MAC address patterns:
    - AA:BB:CC:DD:EE:FF
    - AA-BB-CC-DD-EE-FF
    - AABBCCDDEEFF
    """
    # Standard MAC with colons or dashes
    patterns = [
        r'(?:MAC|MAC\s+Address)\s*[:\-]?\s*([0-9A-F]{2}[:\-][0-9A-F]{2}[:\-][0-9A-F]{2}[:\-][0-9A-F]{2}[:\-][0-9A-F]{2}[:\-][0-9A-F]{2})',
        r'([0-9A-F]{2}[:\-][0-9A-F]{2}[:\-][0-9A-F]{2}[:\-][0-9A-F]{2}[:\-][0-9A-F]{2}[:\-][0-9A-F]{2})',
        r'([0-9A-F]{12})',  # Without separators
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            mac = match.group(1).upper()
            # Normalize to colon-separated format
            if len(mac) == 12:  # No separators
                mac = ':'.join([mac[i:i+2] for i in range(0, 12, 2)])
            elif '-' in mac:  # Dash-separated
                mac = mac.replace('-', ':')
            return mac

    return None


def _extract_part_number(text: str) -> Optional[str]:
    """Extract part number from OCR text.

    Looks for patterns like:
    - P/N: ABC-123
    - Part No: ABC-123
    - Part Number: ABC-123
    """
    patterns = [
        r'(?:P/?N|Part(?:\s+(?:No|Number))?)\s*[:\-]?\s*([A-Z0-9\-]{3,30})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            part = match.group(1).strip()
            return part

    return None


def _extract_manufacturer(text: str) -> Optional[str]:
    """Extract manufacturer name from OCR text.

    Looks for common manufacturer names in the text.
    """
    manufacturers = [
        'Synology', 'QNAP', 'Dell', 'HP', 'Lenovo', 'Apple', 'Microsoft',
        'Cisco', 'Netgear', 'TP-Link', 'Ubiquiti', 'UniFi',
        'Axis', 'Hikvision', 'Dahua', 'Hanwha', 'Verkada',
        'Samsung', 'LG', 'Sony', 'Canon', 'Epson',
        'Intel', 'AMD', 'NVIDIA', 'Western Digital', 'Seagate',
    ]

    text_upper = text.upper()
    for mfr in manufacturers:
        if mfr.upper() in text_upper:
            return mfr

    return None


def process_photo_for_intake(image_path: Path) -> dict:
    """Process an intake photo and return extracted fields as dict.

    Args:
        image_path: Path to uploaded photo

    Returns:
        Dictionary with extracted fields ready for form population
    """
    extracted = extract_from_image(image_path)

    result = {}
    if extracted.serial:
        result['serial'] = extracted.serial
    if extracted.model:
        result['model'] = extracted.model
    if extracted.manufacturer:
        result['manufacturer'] = extracted.manufacturer
    if extracted.mac_address:
        result['mac_address'] = extracted.mac_address
    if extracted.part_number:
        result['part_number'] = extracted.part_number

    # Include raw text for debugging
    result['_ocr_raw_text'] = extracted.raw_text[:500]  # First 500 chars

    return result
