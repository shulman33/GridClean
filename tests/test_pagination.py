"""Unit tests for opaque cursor pagination."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.pagination import decode_cursor, encode_cursor


def test_cursor_round_trip():
    period = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
    assert decode_cursor(encode_cursor(period)) == period


def test_cursor_is_opaque():
    # Should not be a plain readable timestamp.
    token = encode_cursor(datetime(2026, 6, 1, 6, 0, tzinfo=UTC))
    assert "2026" not in token


def test_invalid_cursor_raises_400():
    with pytest.raises(HTTPException) as exc:
        decode_cursor("not-a-valid-cursor!!")
    assert exc.value.status_code == 400
