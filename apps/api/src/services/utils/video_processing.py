"""
Video processing helpers.

The main job here is "faststart": moving the MP4 `moov` atom (the index the
player needs before it can decode/seek) from the end of the file to the front.
Without it, a browser streaming a large MP4 over HTTP has to hunt for the index
in a multi-hundred-MB/GB file before it can start or seek, producing long
startup delays and stutter. `ffmpeg -c copy -movflags +faststart` rewrites the
container losslessly (no re-encode) to fix this.

Faststart is best effort. Full decode validation is mandatory for video
uploads: damaged input must not be published, even when a remux succeeds.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Only MP4-family containers have a movable `moov` atom. WebM/Ogg/MKV stream
# fine as-is and are left untouched.
_FASTSTART_EXTENSIONS = {".mp4", ".mov", ".m4v", ".m4a"}

# Read window used to detect whether `moov` already precedes `mdat`.
_ATOM_SCAN_BYTES = 2 * 1024 * 1024  # 2MB

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".ogv"}


def validate_video_decode(path: str) -> None:
    """Reject damaged media before publishing it to learners.

    A successful probe/remux does not imply decodable packets: ffmpeg normally
    logs damaged H.264/AAC frames and still exits zero. Decode the complete
    audio/video streams, and fail on either a decoder error or error output.
    """
    if Path(path).suffix.lower() not in _VIDEO_EXTENSIONS:
        return
    if not _ffmpeg_available():
        raise RuntimeError("Video validation is unavailable: ffmpeg is missing")
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-err_detect",
         "explode", "-threads", "2", "-i", path, "-map", "0:v:0",
         "-map", "0:a?", "-f", "null", "-"],
        capture_output=True, text=True, timeout=1800,
    )
    if result.returncode or result.stderr.strip():
        logger.warning("Video decode validation failed for %s: %s", path,
                       result.stderr[-1500:])
        raise ValueError("The video contains damaged or unsupported audio/video data")


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def is_faststart(path: str) -> bool:
    """
    Best-effort check for whether an MP4's `moov` atom is already near the
    front (i.e. before `mdat`). Reads only the first couple of MB. On any error
    we return False so the caller attempts a remux rather than skipping.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(_ATOM_SCAN_BYTES)
    except OSError:
        return False
    moov = head.find(b"moov")
    mdat = head.find(b"mdat")
    # moov seen before mdat (or mdat not in the head window yet) → faststart.
    return moov != -1 and (mdat == -1 or moov < mdat)


def ensure_faststart(path: str) -> bool:
    """
    Rewrite an MP4-family file in place so the `moov` atom is at the front.

    Returns True if the file is faststart afterwards (either already was, or we
    remuxed it), False if it was left as-is (unsupported type, ffmpeg missing,
    or remux failed). Never raises — callers treat this as best-effort.
    """
    ext = Path(path).suffix.lower()
    if ext not in _FASTSTART_EXTENSIONS:
        return False

    if not os.path.isfile(path):
        return False

    if is_faststart(path):
        return True

    if not _ffmpeg_available():
        logger.warning(
            "ffmpeg not available; serving %s without faststart (may stream slowly)",
            path,
        )
        return False

    tmp_path = f"{path}.faststart{ext}"
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel", "error",
                "-i", path,
                "-c", "copy",
                "-map", "0",
                "-movflags", "+faststart",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=60 * 30,  # 30 min ceiling for very large files
        )
        if result.returncode == 0 and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
            os.replace(tmp_path, path)
            logger.info("Applied faststart to %s", path)
            return True
        logger.warning(
            "faststart remux failed for %s (rc=%s): %s",
            path, result.returncode, (result.stderr or "").strip()[:500],
        )
    except subprocess.TimeoutExpired:
        logger.warning("faststart remux timed out for %s", path)
    except Exception as e:
        logger.warning("faststart remux error for %s: %s", path, e)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return False
