"""Utilities for handling file downloads with progress tracking."""

from __future__ import annotations

import logging
import math
import shutil
from pathlib import Path
from typing import Callable

import requests
from requests import Response
from requests.exceptions import ChunkedEncodingError, RequestException

from src.config import DOWNLOAD_HEADERS, LARGE_FILE_CHUNK_SIZE, THRESHOLDS
from src.managers.progress_manager import ProgressManager

DEFAULT_UNKNOWN_SIZE_BASELINE = 50 * 1024 * 1024


def get_chunk_size(file_size: int) -> int:
    """Determine the optimal chunk size based on the file size."""
    for threshold, chunk_size in THRESHOLDS:
        if file_size < threshold:
            return chunk_size

    # Return a default chunk size for files larger than the largest threshold
    return LARGE_FILE_CHUNK_SIZE


def _resolve_content_length(response: Response, download_url: str | None) -> int | None:
    """Extract a positive content length from the response or fallback to HEAD."""

    def _normalise(value: object) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    header_length = _normalise(response.headers.get("Content-Length"))
    if header_length:
        return header_length

    raw_remaining = _normalise(getattr(response.raw, "length_remaining", None))
    if raw_remaining:
        return raw_remaining

    if not download_url:
        return None

    try:
        head_resp = requests.head(
            download_url,
            headers=DOWNLOAD_HEADERS,
            timeout=15,
            allow_redirects=True,
        )
        head_resp.raise_for_status()
    except RequestException:
        return None

    return _normalise(head_resp.headers.get("Content-Length"))


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


def save_file_with_progress(
    response: Response,
    download_path: str,
    task: int,
    progress_manager: ProgressManager,
    *,
    download_url: str | None = None,
) -> bool:
    """Save the file from the response to the specified path.

    Adds a `.temp` extension for in-flight downloads and attempts to infer the
    content length so live progress can be reported accurately. When the server
    omits the header, a best-effort estimate is used so the UI still reflects
    activity while streaming.
    """
    file_size = _resolve_content_length(response, download_url)
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
                    if file_size:
                        progress_manager.update_task(
                            task,
                            completed=min(100.0, (total_downloaded / file_size) * 100),
                        )
                    else:
                        estimator = estimator or _ProgressEstimator(
                            float(len(chunk)) or 1.0
                        )
                        progress_manager.update_task(
                            task,
                            completed=estimator.update(total_downloaded),
                        )

    # Handle partial downloads caused by network interruptions
    except ChunkedEncodingError:
        return True

    # Rename temp file to final filename if fully downloaded
    if file_size and total_downloaded == file_size:
        shutil.move(temp_download_path, download_path)
        progress_manager.update_task(task, completed=100)
        return False

    # Keep partial file and return True if incomplete
    if not file_size:
        try:
            shutil.move(temp_download_path, download_path)
        except OSError:
            return True
        progress_manager.update_task(task, completed=100)
        return False

    return True
