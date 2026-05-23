"""
utils/imgbb.py - ImgBB Image Hosting Utility
=============================================
Matches the pattern used in NEMSU Marketplace (working on Vercel).

Uses urllib.request (Python built-in) — NOT the requests library.
Vercel's egress proxy blocks `requests` but allows urllib.request.
"""

import os
import base64
import json
import logging
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)

IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"


def upload_to_imgbb(file_bytes: bytes, filename: str = "image") -> str | None:
    """
    Upload raw image bytes to ImgBB using urllib (Vercel-compatible).
    Returns the permanent direct image URL on success, None on failure.
    Matches marketplace _upload_to_imgbb() exactly.
    """
    api_key = os.environ.get("IMGBB_API_KEY", "").strip()
    if not api_key:
        logger.error("IMGBB_API_KEY is not set — cannot upload image.")
        return None

    try:
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        data = urllib.parse.urlencode({
            "key":   api_key,
            "image": b64,
            "name":  filename,
        }).encode("utf-8")

        req = urllib.request.Request(IMGBB_UPLOAD_URL, data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if result.get("success"):
            # Use display_url — same as marketplace (stable, permanent CDN link)
            url = result["data"].get("display_url") or result["data"].get("url")
            logger.info("ImgBB upload succeeded: %s", url)
            return url

        logger.error("ImgBB upload failed: %s", result)
        return None

    except urllib.error.HTTPError as exc:
        logger.error("ImgBB HTTP error %s: %s", exc.code, exc.reason)
        return None
    except Exception as exc:
        logger.error("ImgBB upload exception: %s", exc)
        return None


def upload_file_to_imgbb(file) -> str | None:
    """
    Upload a Werkzeug FileStorage object to ImgBB.
    Returns permanent image URL on success, None on failure.
    """
    try:
        file.seek(0)
        file_bytes = file.read()
        file.seek(0)
        filename = file.filename or "upload"
        return upload_to_imgbb(file_bytes, filename)
    except Exception as exc:
        logger.error("upload_file_to_imgbb error: %s", exc)
        return None
