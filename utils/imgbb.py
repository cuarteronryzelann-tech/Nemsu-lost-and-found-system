"""
utils/imgbb.py - ImgBB Image Hosting Utility
=============================================
Uploads images to ImgBB and returns a permanent URL.
This replaces local file storage, fixing broken images on Render/Vercel
where the filesystem resets on every deploy or restart.

Setup:
  1. Get a free API key at https://imgbb.com/
  2. Set IMGBB_API_KEY in your environment variables (Render dashboard, .env, etc.)

If IMGBB_API_KEY is not set, upload_to_imgbb() returns None and the caller
falls back to the old local-file path (no crash, just no ImgBB).
"""

import os
import base64
import requests
import logging

logger = logging.getLogger(__name__)

IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "")
IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"


def upload_to_imgbb(file_bytes: bytes, filename: str = "image") -> str | None:
    """
    Upload raw image bytes to ImgBB.

    Args:
        file_bytes: Raw bytes of the image file.
        filename:   Optional name hint (used for ImgBB's name field).

    Returns:
        The permanent display URL (str) on success, or None on failure.
    """
    if not IMGBB_API_KEY:
        logger.warning("IMGBB_API_KEY not set — skipping ImgBB upload.")
        return None

    try:
        encoded = base64.b64encode(file_bytes).decode("utf-8")
        resp = requests.post(
            IMGBB_UPLOAD_URL,
            data={
                "key":   IMGBB_API_KEY,
                "image": encoded,
                "name":  filename,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            # Use data.data.image.url — the true direct image URL.
            # display_url is also direct, but ImgBB's hotlink protection can
            # block it when the request comes from an external domain (Vercel).
            # image.url is always embeddable without referrer restrictions.
            img_data = data["data"]
            return (
                img_data.get("image", {}).get("url")   # preferred: direct embed URL
                or img_data.get("display_url")          # fallback
                or img_data.get("url")                  # last resort (viewer page)
            )
        logger.error("ImgBB upload failed: %s", data)
        return None
    except Exception as exc:
        logger.error("ImgBB upload exception: %s", exc)
        return None


def upload_file_to_imgbb(file) -> str | None:
    """
    Upload a Werkzeug FileStorage object to ImgBB.

    Args:
        file: werkzeug.datastructures.FileStorage (from request.files).

    Returns:
        Permanent image URL on success, None on failure.
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
