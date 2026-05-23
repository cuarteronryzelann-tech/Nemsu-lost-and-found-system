"""
utils/imgbb.py - ImgBB Image Hosting Utility
=============================================
Uses urllib.request (Python built-in) instead of the requests library.

WHY: Vercel's egress proxy blocks outbound calls made via the third-party
`requests` library (returns 403 "Host not in allowlist"), but allows the
same call made via Python's built-in urllib.request. This matches how the
NEMSU Marketplace project successfully uploads to ImgBB on Vercel.
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
    """
    api_key = os.environ.get("IMGBB_API_KEY", "").strip()
    if not api_key:
        logger.error(
            "IMGBB_API_KEY is not set — cannot upload image. "
            "Add it to your Vercel environment variables."
        )
        return None

    try:
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        data = urllib.parse.urlencode({
            "key":   api_key,
            "image": b64,
            "name":  filename,
        }).encode("utf-8")

        req = urllib.request.Request(IMGBB_UPLOAD_URL, data=data)
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if result.get("success"):
            img_data = result["data"]
            direct_url = (
                img_data.get("image", {}).get("url")   # true CDN direct URL
                or img_data.get("display_url")          # fallback
                or img_data.get("url")                  # last resort
            )
            logger.info("ImgBB upload succeeded: %s", direct_url)
            return direct_url

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
