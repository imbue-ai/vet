from __future__ import annotations

import pytest


@pytest.fixture()
def make_mock_response():
    """Factory fixture that creates mock urllib response objects."""

    def _make(data: bytes):
        return type(
            "Response",
            (),
            {
                "read": lambda self: data,
                "__enter__": lambda self: self,
                "__exit__": lambda *a: None,
            },
        )()

    return _make
