"""Opaque cursor pagination (keyset, not offset).

Cursors encode the sort key of the last row returned so the next page can
continue from `period < cursor` — stable under inserts and free of deep-scan
cost, unlike OFFSET. See docs/SPEC.md §5.
"""

import base64
import binascii
from datetime import datetime

from fastapi import HTTPException


def encode_cursor(period: datetime) -> str:
    """Encode a period timestamp into an opaque base64 cursor."""
    raw = period.isoformat().encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> datetime:
    """Decode an opaque cursor back into a period timestamp."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        return datetime.fromisoformat(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor.") from exc
