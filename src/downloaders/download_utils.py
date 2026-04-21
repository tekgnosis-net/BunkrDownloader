"""Utilities for handling file downloads with progress tracking."""

from __future__ import annotations

import logging
import math
import shutil
from concurrent.futures import Future, ThreadPoolExecutor
from enum import IntEnum
from pathlib import Path
from typing import Callable

import requests
from requests import Response
from requests.exceptions import ChunkedEncodingError, RequestException

from src.config import DOWNLOAD_HEADERS, LARGE_FILE_CHUNK_SIZE, THRESHOLDS
from src.managers.progress_manager import ProgressManager

DEFAULT_UNKNOWN_SIZE_BASELINE = 50 * 1024 * 1024


class DownloadOutcome(IntEnum):
    """Result of a single :func:`save_file_with_progress` invocation.

    Replaces the historical ``True = failed / False = succeeded`` bool return
    that was trivially easy to misread. ``RETRYABLE_FAILURE`` covers transient
    network errors and late-stage IO problems (chunk decode, final rename);
    ``TERMINAL_FAILURE`` is reserved for errors the caller should not retry.
    The value is adapted back to a ``bool`` at :meth:`MediaDownloader.attempt_download`
    for now so upstream retry wiring is unchanged in PR1.
    """

    SUCCESS = 0
    RETRYABLE_FAILURE = 1
    TERMINAL_FAILURE = 2


def get_chunk_size(file_size: int) -> int:
    """Determine the optimal chunk size based on the file size."""
    for threshold, chunk_size in THRESHOLDS:
        if file_size < threshold:
            return chunk_size

    # Return a default chunk size for files larger than the largest threshold
    return LARGE_FILE_CHUNK_SIZE


def _normalise_length(value: object) -> int | None:
    """Convert a possible integer-like value into a positive int."""

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _extract_response_length(response: Response) -> int | None:
    """Pull a positive content length from response metadata when available."""

    header_length = _normalise_length(response.headers.get("Content-Length"))
    if header_length:
        return header_length

    raw_remaining = _normalise_length(getattr(response.raw, "length_remaining", None))
    if raw_remaining:
        return raw_remaining

    return None


def _head_content_length(
    download_url: str,
    *,
    timeout: float = 5.0,
    headers: dict[str, str] | None = None,
) -> int | None:
    """Best-effort HEAD request used to infer missing content lengths.

    The effective ``headers`` must match those used by the streaming GET
    (user-agent, referer) — some CDNs serve different responses based on
    those, so probing with module-global defaults while the download uses
    a per-job override would give inconsistent lengths.
    """

    effective_headers = headers if headers is not None else DOWNLOAD_HEADERS
    try:
        head_resp = requests.head(
            download_url,
            headers=effective_headers,
            timeout=timeout,
            allow_redirects=True,
        )
        head_resp.raise_for_status()
    except RequestException:
        return None

    return _normalise_length(head_resp.headers.get("Content-Length"))


def _resolve_content_length(
    response: Response,
    download_url: str | None,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int | None, Future[int | None] | None, ThreadPoolExecutor | None]:
    """Determine an expected content length and return any async fallback."""

    length = _extract_response_length(response)
    if length or not download_url:
        return length, None, None

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_head_content_length, download_url, headers=headers)
    return None, future, executor


def _log_once(progress_manager: ProgressManager, message: str) -> None:
    """Emit a log message if the progress manager supports logging."""

    update_log: Callable[..., None] | None = getattr(progress_manager, "update_log", None)
    if callable(update_log):
        update_log(event="Download progress", details=message)


class _ProgressEstimator:  # pylint: disable=too-few-public-methods
    """Track a rolling progress estimate when file size is unknown."""

    __slots__ = ("baseline", "estimate")

    def __init__(self, baseline: float) -> None:
        self.baseline = baseline if baseline > 0 else float(DEFAULT_UNKNOWN_SIZE_BASELINE)
        self.estimate = 0.0

    def update(self, downloaded_bytes: int) -> float:
        """Return the next completion percentage for the streamed download."""
        if downloaded_bytes <= 0:
            return self.estimate

        if self.baseline <= 0:
            self.baseline = float(downloaded_bytes) or 1.0

        linear_progress = (downloaded_bytes / self.baseline) * 100
        log_scaled_progress = math.log10(downloaded_bytes + 1) * 20.0
        self.estimate = min(99.0, max(self.estimate, linear_progress, log_scaled_progress))
        return self.estimate


def _emit_progress(
    progress_manager: ProgressManager,
    task: int,
    *,
    file_size: int | None,
    estimator: _ProgressEstimator | None,
    total_downloaded: int,
) -> _ProgressEstimator | None:  # pylint: disable=too-many-arguments
    """Update the task progress, returning the (possibly new) estimator."""

    if file_size:
        progress_manager.update_task(
            task,
            completed=min(100.0, (total_downloaded / file_size) * 100),
        )
        return estimator

    estimator = estimator or _ProgressEstimator(float(DEFAULT_UNKNOWN_SIZE_BASELINE))
    progress_manager.update_task(
        task,
        completed=estimator.update(total_downloaded),
    )
    return estimator

# pylint: disable=too-many-arguments
def _finalise_download(
    *,
    file_size: int | None,
    total_downloaded: int,
    temp_path: Path,
    final_path: str,
    progress_manager: ProgressManager,
    task: int,
) -> DownloadOutcome:
    """Rename the in-flight file if possible and report completion.

    On any terminal-path failure (short read or rename error), mark the task
    ``visible=False`` before returning so the progress row does not sit
    frozen at its last-known percentage — a user-visible symptom of the old
    99% stall.
    """

    if file_size:
        if total_downloaded != file_size:
            _log_once(
                progress_manager,
                f"Short read for {final_path}: {total_downloaded}/{file_size} bytes; will retry.",
            )
            progress_manager.update_task(task, completed=0, visible=False)
            return DownloadOutcome.RETRYABLE_FAILURE
        try:
            shutil.move(temp_path, final_path)
        except OSError as os_err:
            _log_once(progress_manager, f"Could not finalise {final_path}: {os_err}")
            progress_manager.update_task(task, completed=0, visible=False)
            return DownloadOutcome.RETRYABLE_FAILURE
        progress_manager.update_task(task, completed=100)
        return DownloadOutcome.SUCCESS

    try:
        shutil.move(temp_path, final_path)
    except OSError as os_err:
        _log_once(progress_manager, f"Could not finalise {final_path}: {os_err}")
        progress_manager.update_task(task, completed=0, visible=False)
        return DownloadOutcome.RETRYABLE_FAILURE
    progress_manager.update_task(task, completed=100)
    return DownloadOutcome.SUCCESS
# pylint: enable=too-many-arguments


def save_file_with_progress(  # pylint: disable=too-many-locals,too-many-arguments
    response: Response,
    download_path: str,
    task: int,
    progress_manager: ProgressManager,
    *,
    download_url: str | None = None,
    download_headers: dict[str, str] | None = None,
) -> DownloadOutcome:
    """Save the file from the response to the specified path.

    Adds a `.temp` extension for in-flight downloads and attempts to infer the
    content length so live progress can be reported accurately. When the server
    omits the header, a best-effort estimate is used so the UI still reflects
    activity while streaming. The optional ``download_headers`` are forwarded
    to the HEAD probe so the content-length backfill uses the same user-agent
    and referer as the streaming GET — otherwise per-job ``NetworkContext``
    overrides would be silently ignored for unknown-length files.
    """
    file_size, head_future, head_executor = _resolve_content_length(
        response, download_url, headers=download_headers,
    )
    if file_size is None:
        logging.warning("Content length unavailable for %s", download_path)
        _log_once(
            progress_manager,
            "Server did not provide a content length. Progress will be estimated.",
        )

    # Initialize a temporary download path with the .temp extension
    temp_download_path = Path(download_path).with_suffix(".temp")
    chunk_size = get_chunk_size(file_size or 0)
    total_downloaded = 0
    estimator = (
        _ProgressEstimator(float(DEFAULT_UNKNOWN_SIZE_BASELINE))
        if file_size is None
        else None
    )

    try:
        with temp_download_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk is not None:
                    file.write(chunk)
                    total_downloaded += len(chunk)
                    estimator = _emit_progress(
                        progress_manager,
                        task,
                        file_size=file_size,
                        estimator=estimator,
                        total_downloaded=total_downloaded,
                    )
                    if head_future and file_size is None and head_future.done():
                        head_length = head_future.result()
                        head_future = None

                        if head_length:
                            file_size = head_length
                            estimator = None
                            progress_manager.update_task(
                                task,
                                completed=min(
                                    100.0,
                                    (total_downloaded / file_size) * 100,
                                ),
                            )

    # Handle partial downloads caused by network interruptions. The task would
    # otherwise sit frozen at its last estimate — hide it and log so retry
    # bookkeeping can reactivate it on the next attempt.
    except ChunkedEncodingError:
        _log_once(
            progress_manager,
            f"Partial transfer for {download_path}; the stream ended mid-chunk.",
        )
        progress_manager.update_task(task, completed=0, visible=False)
        return DownloadOutcome.RETRYABLE_FAILURE

    finally:
        if head_executor:
            head_executor.shutdown(wait=False, cancel_futures=True)

    # Late HEAD result: if the content-length probe resolved after the loop
    # exited, promote the estimator into a real percentage one last time so
    # _finalise_download can compare bytes correctly.
    if head_future is not None and file_size is None:
        try:
            head_length = head_future.result(timeout=0.1)
        except Exception:  # pylint: disable=broad-exception-caught
            head_length = None
        if head_length:
            file_size = head_length

    return _finalise_download(
        file_size=file_size,
        total_downloaded=total_downloaded,
        temp_path=temp_download_path,
        final_path=download_path,
        progress_manager=progress_manager,
        task=task,
    )
