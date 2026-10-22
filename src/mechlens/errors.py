from pathlib import Path


class MechLensError(Exception):
    """Base exception raised by the SDK."""


class MechLensConfigurationError(MechLensError):
    """The SDK is missing configuration required to contact MechLens."""


class MechLensWarning(UserWarning):
    """Something about a run will weaken its evidence in Cloud, but it can still be recorded."""


class MechLensUploadError(MechLensError):
    """An upload failed after the run was safely stored on disk.

    Attributes:
        local_path: The saved copy of the run.
        status_code: Cloud's HTTP status, or `None` if Cloud was never reached.
        retryable: Whether retrying the same run could succeed. `False` for an
            invalid key or a rejected run, which need fixing first.
    """

    def __init__(
        self,
        message: str,
        *,
        local_path: Path,
        status_code: int | None = None,
        retryable: bool = True,
    ):
        super().__init__(f"{message} Local copy: {local_path}")
        self.local_path = local_path
        self.status_code = status_code
        self.retryable = retryable

