"""The contract's error envelope (§2.3) and a small helper to emit it.

Every non-2xx response in the interface contract uses ``{"error": {code, message,
detail}}``. Centralising the shape here means a route raises or returns an error the
same way everywhere, and the ``code`` values stay the closed set the contract lists.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from recoup.api.schemas import ErrorBody, ErrorOut

__all__ = ["error_response"]


def error_response(
    status_code: int, code: str, message: str, detail: str | None = None
) -> JSONResponse:
    """A ``JSONResponse`` carrying the contract's error envelope."""
    body = ErrorOut(error=ErrorBody(code=code, message=message, detail=detail))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))
