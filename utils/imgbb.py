"""
utils/imgbb.py - ImgBB Image Hosting Utility
=============================================
Uploads images to ImgBB and returns a permanent direct-embed URL.

Setup:
  1. Get a free API key at https://imgbb.com/
  2. Set IMGBB_API_KEY in your Vercel environment variables.

Key fixes vs original:
  - API key is read lazily (inside the function) so Vercel env vars are
    always available at call time, not just at cold-start import time.
  - Returns data["data"]["image"]["url"] — the true direct image URL that
    works cross-origin without hotlink restrictions.
  - display_url and url are kept as ordered fallbacks.
  - Logs the full ImgBB error response so failures are visible in Vercel logs.
"""

import os
import base64
import logging

import requests

logger = logging.getLogger(__name__)

IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"


def _get_api_key() -> str:
    """Read key lazily so Vercel injects it before we check."""
    return os.environ.get("IMGBB_API_KEY", "").strip()


def upload_to_imgbb(file_bytes: bytes, filename: str = "image") -> str | None:
    """
    Upload raw image bytes to ImgBB.

    Returns the permanent direct-embed image URL on success, None on failure.
    """
    api_key = _get_api_key()
    if not api_key:
        logger.error(
            "IMGBB_API_KEY is not set — cannot upload image. "
            "Add it to your Vercel environment variables."
        )
        return None

    try:
        encoded = base64.b64encode(file_bytes).decode("utf-8")
        resp = requests.post(
            IMGBB_UPLOAD_URL,
            data={
                "key":   api_key,
                "image": encoded,
                "name":  filename,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("success"):
            img_data = data["data"]
            # image.url  → direct CDN link, no hotlink restrictions
            # display_url → also direct but may be blocked by referrer checks
            # url         → viewer page (last resort)
            direct_url = (
                img_data.get("image", {}).get("url")
                or img_data.get("display_url")
                or img_data.get("url")
            )
            logger.info("ImgBB upload succeeded: %s", direct_url)
            return direct_url

        logger.error("ImgBB upload failed (success=false): %s", data)
        return None

    except requests.HTTPError as exc:
        logger.error(
            "ImgBB HTTP error %s: %s",
            exc.response.status_code if exc.response else "?",
            exc.response.text[:300] if exc.response else str(exc),
        )
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
