from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from ._version import __version__
from .errors import MechLensUploadError

# Statuses where sending the same run again cannot succeed.
_NOT_RETRYABLE = {
    400: "Cloud could not read the run.",
    401: "Check MECHLENS_API_KEY: the key is missing, invalid, or revoked.",
    403: "This key cannot upload to the workspace.",
    409: "A different run with this ID already exists. Record the run again to get a new ID.",
    413: "The run is larger than Cloud accepts. Log fewer or shorter examples.",
    422: "Cloud rejected the run's contents. Fix the run and record it again.",
}


def _server_detail(response: httpx.Response) -> str:
    """Cloud's explanation of a failed request, from FastAPI JSON or a plain-text body."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.text.strip()[:500]
    if isinstance(detail, list):
        # Request validation errors: [{"loc": [...], "msg": "..."}, ...]
        return "; ".join(
            f"{'.'.join(str(part) for part in item.get('loc', []))}: {item.get('msg', '')}"
            if isinstance(item, dict)
            else str(item)
            for item in detail
        )
    return str(detail) if detail else response.text.strip()[:500]


@dataclass(frozen=True)
class UploadReceipt:
    """Confirmation that Cloud stored a run.

    Attributes:
        run_id: The run's ID, the same as the local record's.
        url: Where to open the run in MechLens Cloud.
    """

    run_id: str
    url: str


class CloudClient:
    """Small synchronous client for the MechLens ingestion API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def upload_run(self, data: Mapping[str, Any], *, local_path) -> UploadReceipt:
        """Send one finished run to Cloud.

        Raises:
            MechLensUploadError: Cloud could not be reached or rejected the run. Its
                `status_code` and `retryable` attributes say whether to retry.
        """
        run_id = str(data["id"])
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(
                    "/api/sdk/runs",
                    json=data,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Idempotency-Key": run_id,
                        "User-Agent": f"mechlens-python/{__version__}",
                    },
                )
                response.raise_for_status()
                payload = response.json()
            returned_id = payload.get("run_id")
            url = payload.get("url")
            if returned_id != run_id or not isinstance(url, str) or not url:
                raise ValueError("response is missing the expected run_id or url")
            return UploadReceipt(run_id=returned_id, url=url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = _server_detail(exc.response)
            hint = _NOT_RETRYABLE.get(status, "Call run.retry_upload() to try again.")
            raise MechLensUploadError(
                f"Cloud rejected the upload ({status}): {detail or exc.response.reason_phrase}. {hint}",
                local_path=local_path,
                status_code=status,
                retryable=status not in _NOT_RETRYABLE,
            ) from exc
        except httpx.TransportError as exc:
            raise MechLensUploadError(
                f"Could not reach MechLens at {self.base_url}: {exc}. Check MECHLENS_API_URL and your "
                "connection, then call run.retry_upload().",
                local_path=local_path,
            ) from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise MechLensUploadError(f"Could not upload run: {exc}.", local_path=local_path) from exc

