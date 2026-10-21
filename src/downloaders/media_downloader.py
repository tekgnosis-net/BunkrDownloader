"""Module that provides tools to manage the downloading of individual files from Bunkr.

It supports retry mechanisms, progress tracking, and error handling for a robust
download experience.
"""

from __future__ import annotations

import logging
import os
import random
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from bs4 import BeautifulSoup
from requests import RequestException

from src.bunkr_utils import (
    get_subdomain,
    mark_subdomain_as_offline,
    refresh_server_status,
    subdomain_is_offline,
)
from src.config import (
    DOWNLOAD_HEADERS,
    DownloadInfo,
    HTTPStatus,
    SessionInfo,
    TransferSettings,
    STATUS_CHECK_ON_FAILURE,
    MAINTENANCE_BACKOFF_DELAYS_SECONDS,
)
from src.crawlers.api_utils import get_signed_download_url
from src.file_utils import (
    log_maintenance_event,
    truncate_filename,
    write_on_session_log,
)

from .connection_governor import Cancelled
from .download_utils import DownloadOutcome, finalise_download, save_file_with_progress
from .remote_probe import RemoteInfo, probe_remote
from .segmented_download import (
    SegmentedDownloader,
    SegmentedOutcome,
    TransferMode,
    TransferPlan,
    plan_transfer,
)
from .transfer_context import TransferContext, make_transfer_context
from .transfer_manifest import (
    TransferManifest,
    discard_partial,
    etags_conflict,
    load_manifest,
    manifest_matches_remote,
    manifest_path,
    temp_path_for,
)

if TYPE_CHECKING:
    from src.managers.live_manager import LiveManager


class _SingleVerdict(Enum):
    """What to do with the response to a single-stream GET."""

    STREAM = "stream"                      # write the body (at resume_from)
    STREAM_FROM_ZERO = "stream_from_zero"  # server ignored Range: drop partial, use the 200 body
    RESET = "reset"                        # 416 / bad Content-Range: partial is invalid
    REFRESH = "refresh"                    # 401/403: signed URL expired


class MediaDownloader:  # pylint: disable=too-many-instance-attributes
    """Manage the downloading of individual files from Bunkr URLs.

    ``transfer_context`` carries the job's settings, connection governor and
    cancel flag; a private one is built from ``session_info.args`` when the
    caller does not pass one (tests, standalone use).
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        session_info: SessionInfo,
        download_info: DownloadInfo,
        live_manager: LiveManager,
        retries: int = 5,
        *,
        transfer_context: TransferContext | None = None,
    ) -> None:
        """Initialize the MediaDownloader instance."""
        self.session_info = session_info
        self.download_info = download_info
        self.live_manager = live_manager
        self.retries = retries
        self._ctx = transfer_context or make_transfer_context(session_info.args)
        self._settings: TransferSettings | None = None
        self._remote: RemoteInfo | None = None
        self._refreshes = 0
        self._resets = 0

    def _caps(self) -> TransferSettings:
        """Return the job's resolved transfer settings."""
        return self._settings or self._ctx.settings

    def _pause(self, seconds: float) -> bool:
        """Back off for ``seconds``; False (immediately) if the job is cancelled."""
        return not self._ctx.cancel_event.wait(seconds)

    def attempt_download(self, final_path: str) -> DownloadOutcome:
        """Download ``final_path`` with retries, segmentation and resume."""
        if self._ctx.cancelled:
            return DownloadOutcome.RETRYABLE_FAILURE
        headers = self._download_headers()
        settings = self._ctx.settings
        self._settings = settings
        self._refreshes = 0
        self._resets = 0

        temp_path = temp_path_for(final_path)
        self._drop_legacy_temp(final_path, temp_path)
        remote = probe_remote(self.download_info.download_link, headers)
        existing, remote = self._validate_existing(temp_path, remote)
        self._remote = remote
        plan = plan_transfer(
            remote, settings, existing=existing, url_origin=self.download_info.item_page,
        )
        if existing is not None and existing.bytes_done:
            pct = existing.bytes_done * 100 // max(existing.size, 1)
            self.live_manager.update_log(
                event="Download progress",
                details=f"Resuming {self.download_info.filename}: {pct}% already on disk.",
            )
        plan = self._without_pwrite_fallback(plan)
        if plan.mode is TransferMode.SEGMENTED:
            return self._run_segmented(plan, temp_path, final_path, headers)
        return self._run_single(plan, temp_path, final_path, headers)

    @staticmethod
    def _drop_legacy_temp(final_path: str | Path, temp_path: Path) -> None:
        """Delete a manifest-less ``<stem>.temp`` left by builds that named partials so.

        Older releases wrote ``video.temp`` for ``video.mp4`` and simply
        overwrote it on the next attempt; with the ``video.mp4.temp`` name it
        would otherwise linger forever. A ``<stem>.temp`` that has a
        ``.parts`` manifest is left alone (it may be a live partial of a file
        literally named ``<stem>``) and is swept by age like any partial.
        """
        legacy = Path(final_path).with_suffix(".temp")
        if legacy == temp_path or manifest_path(legacy).exists() or not legacy.is_file():
            return
        try:
            legacy.unlink()
        except OSError as err:
            logging.debug("Could not remove legacy partial %s: %s", legacy, err)

    def _validate_existing(
        self, temp_path: Path, remote: RemoteInfo,
    ) -> tuple[TransferManifest | None, RemoteInfo]:
        """Load the on-disk manifest; return ``(usable_manifest, remote_to_plan_with)``.

        When the HEAD probe failed but a structurally valid manifest with
        progress exists, the transfer proceeds from the manifest's own
        size/ETag: every 206 is then checked against them (``Content-Range``
        total and, when both sides have one, the ETag), so a changed remote
        is still caught before any byte is trusted.
        """
        existing = load_manifest(manifest_path(temp_path))
        if existing is None:
            return None, remote
        if remote.size is None:
            if existing.bytes_done:
                # A failed probe says nothing about the remote: never throw away progress.
                self.live_manager.update_log(
                    event="Download progress",
                    details=(
                        f"Probe failed for {self.download_info.filename}; resuming from "
                        "the on-disk partial and validating each range response."
                    ),
                )
                return existing, RemoteInfo(
                    size=existing.size, etag=existing.etag, accepts_ranges=True,
                )
            discard_partial(temp_path)
            return None, remote
        if not manifest_matches_remote(existing, size=remote.size, etag=remote.etag):
            discard_partial(temp_path)
            self.live_manager.update_log(
                event="Download progress",
                details=(
                    f"Discarding stale partial for {self.download_info.filename}: "
                    "remote file changed."
                ),
            )
            return None, remote
        return existing, remote

    def _download_headers(self) -> dict[str, str]:
        return (
            self.session_info.network.download_headers
            if self.session_info.network is not None
            else DOWNLOAD_HEADERS
        )

    def _without_pwrite_fallback(self, plan: TransferPlan) -> TransferPlan:
        """Downgrade a segmented plan to a resumable single stream without ``os.pwrite``."""
        if plan.mode is TransferMode.SEGMENTED and not hasattr(os, "pwrite"):
            remote = plan.remote
            return TransferPlan(
                TransferMode.SINGLE,
                TransferManifest.plan(
                    remote.size, 1, etag=remote.etag, url_origin=self.download_info.item_page,
                ),
                remote,
            )
        return plan

    def _fresh_manifest(self, count: int, fallback: TransferManifest) -> TransferManifest:
        """Rebuild an empty manifest from the most recently probed remote."""
        remote = self._remote
        size = remote.size if remote is not None and remote.size is not None else fallback.size
        etag = remote.etag if remote is not None and remote.size is not None else fallback.etag
        return TransferManifest.plan(size, count, etag=etag, url_origin=fallback.url_origin)

    def _take_refresh(self) -> str | None:
        """Spend one link refresh; back off before every refresh after the first."""
        if self._refreshes and not self._pause(3 + random.uniform(1, 3)):  # noqa: S311
            return None
        self._refreshes += 1
        return self._refresh_link()

    def _replan_after_refresh(
        self, fresh: str, manifest: TransferManifest | None, temp_path: Path,
        headers: dict[str, str],
    ) -> TransferPlan | None:
        """Adopt ``fresh`` and re-probe it; return a new plan if the remote changed."""
        self.download_info.download_link = fresh
        remote = probe_remote(fresh, headers)
        self._remote = remote
        if (
            manifest is None
            or remote.size is None
            or manifest_matches_remote(manifest, size=remote.size, etag=remote.etag)
        ):
            return None
        discard_partial(temp_path)
        self.live_manager.update_log(
            event="Download progress",
            details=(
                f"Discarding stale partial for {self.download_info.filename}: "
                "remote file changed after link refresh."
            ),
        )
        plan = plan_transfer(
            remote, self._caps(), existing=None, url_origin=self.download_info.item_page,
        )
        return self._without_pwrite_fallback(plan)

    def _run_segmented(  # pylint: disable=too-many-branches
        self, plan: TransferPlan, temp_path: Path, final_path: str, headers: dict[str, str],
    ) -> DownloadOutcome:
        manifest = plan.manifest
        assert manifest is not None
        self.live_manager.update_log(
            event="Download progress",
            details=(
                f"Segmented download: {len(manifest.segments)} x "
                f"{manifest.segments[0].length / (1024 * 1024):.1f} MB for "
                f"{self.download_info.filename}"
            ),
        )
        attempt = 0
        while attempt < self.retries:
            if self._ctx.cancelled:
                return DownloadOutcome.RETRYABLE_FAILURE
            downloader = SegmentedDownloader(
                url=self.download_info.download_link, headers=headers, temp_path=temp_path,
                manifest=manifest, progress_manager=self.live_manager,
                task=self.download_info.task, governor=self._ctx.governor,
                cancel_event=self._ctx.cancel_event,
            )
            outcome = downloader.run()
            if outcome is SegmentedOutcome.COMPLETE:
                return finalise_download(
                    file_size=manifest.size, total_downloaded=manifest.size,
                    temp_path=temp_path, final_path=final_path,
                    progress_manager=self.live_manager, task=self.download_info.task,
                    manifest_file=manifest_path(temp_path),
                )
            if outcome is SegmentedOutcome.NEEDS_REFRESH:
                if self._refreshes >= self._caps().link_refresh_max:
                    return DownloadOutcome.RETRYABLE_FAILURE
                fresh = self._take_refresh()
                if fresh is None:
                    return DownloadOutcome.RETRYABLE_FAILURE
                replan = self._replan_after_refresh(fresh, manifest, temp_path, headers)
                if replan is not None:
                    if replan.mode is not TransferMode.SEGMENTED:
                        return self._run_single(replan, temp_path, final_path, headers)
                    manifest = replan.manifest
                    assert manifest is not None
                continue
            if outcome is SegmentedOutcome.RANGE_UNSUPPORTED:
                discard_partial(temp_path)
                return self._run_single(
                    TransferPlan(TransferMode.SINGLE_NO_RESUME, None, plan.remote),
                    temp_path, final_path, headers,
                )
            if outcome is SegmentedOutcome.MANIFEST_INVALID:
                if self._resets >= self._caps().manifest_reset_max:
                    return DownloadOutcome.TERMINAL_FAILURE
                self._resets += 1
                discard_partial(temp_path)
                manifest = self._fresh_manifest(len(manifest.segments), manifest)
                continue
            if outcome is SegmentedOutcome.TERMINAL:
                return DownloadOutcome.TERMINAL_FAILURE
            if outcome is SegmentedOutcome.CANCELLED:
                return DownloadOutcome.RETRYABLE_FAILURE
            if downloader.last_error is not None:
                # An HTTP status (429/5xx/521/...): same status-page check,
                # maintenance event and backoff as the single-stream path.
                if not self._handle_request_exception(downloader.last_error, attempt):
                    break
            elif not self._retry_with_backoff(attempt, event="Retrying download"):
                break
            attempt += 1
        return DownloadOutcome.RETRYABLE_FAILURE

    @staticmethod
    def _content_range_ok(response: requests.Response, start: int, size: int) -> bool:
        """True if the 206 ``Content-Range`` is exactly ``bytes start-(size-1)/size``."""
        got = response.headers.get("Content-Range", "").replace(" ", "").lower()
        return got == f"bytes{start}-{size - 1}/{size}"

    def _drop_single_partial(self, temp_path: Path, manifest: TransferManifest) -> None:
        discard_partial(temp_path)
        manifest.segments[0].done = 0

    def _single_resume_offset(self, temp_path: Path, manifest: TransferManifest | None) -> int:
        """Bytes to skip with a Range GET; 0 (partial dropped) if the temp cannot back them."""
        resume_from = manifest.segments[0].done if manifest is not None else 0
        if not resume_from:
            return 0
        try:
            on_disk = temp_path.stat().st_size
        except OSError:
            on_disk = -1
        if on_disk >= resume_from:
            return resume_from
        self._drop_single_partial(temp_path, manifest)
        self.live_manager.update_log(
            event="Download progress",
            details=(
                f"Partial file for {self.download_info.filename} is missing or "
                "short; restarting from the beginning."
            ),
        )
        return 0

    def _single_verdict(
        self, response: requests.Response, resume_from: int, manifest: TransferManifest | None,
    ) -> _SingleVerdict:
        """Classify a single-stream response; raises ``HTTPError`` for other failures."""
        status = response.status_code
        if status == HTTPStatus.RANGE_NOT_SATISFIABLE and resume_from:
            return _SingleVerdict.RESET
        if status in (HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED):
            return _SingleVerdict.REFRESH
        response.raise_for_status()
        if not resume_from or manifest is None:
            return _SingleVerdict.STREAM
        if status == HTTPStatus.OK:
            return _SingleVerdict.STREAM_FROM_ZERO
        if (
            status != HTTPStatus.PARTIAL_CONTENT
            or not self._content_range_ok(response, resume_from, manifest.size)
            or etags_conflict(manifest.etag, response.headers.get("ETag"))
        ):
            return _SingleVerdict.RESET
        return _SingleVerdict.STREAM

    def _run_single(  # pylint: disable=too-many-branches
        self, plan: TransferPlan, temp_path: Path, final_path: str, headers: dict[str, str],
    ) -> DownloadOutcome:
        """One stream (Range-resumed from the manifest), holding a governor slot.

        The slot covers the GET and the body; every refresh, backoff and
        hand-off to :meth:`_run_segmented` happens after it is released, so
        no thread ever holds two slots.
        """
        manifest = plan.manifest
        attempt = 0
        while attempt < self.retries:
            if self._ctx.cancelled:
                return DownloadOutcome.RETRYABLE_FAILURE
            resume_from = self._single_resume_offset(temp_path, manifest)
            request_headers = dict(headers)
            if resume_from:
                request_headers["Range"] = f"bytes={resume_from}-"
            failure: RequestException | None = None
            verdict: _SingleVerdict | None = None
            try:
                with self._ctx.governor.slot(cancel_event=self._ctx.cancel_event):
                    response: requests.Response | None = None
                    try:
                        response = requests.get(
                            self.download_info.download_link, stream=True,
                            headers=request_headers, timeout=30,
                        )
                        verdict = self._single_verdict(response, resume_from, manifest)
                    except RequestException as req_err:
                        if response is not None:
                            response.close()
                        failure = req_err
                    else:
                        if verdict is _SingleVerdict.STREAM_FROM_ZERO:
                            self._drop_single_partial(temp_path, manifest)
                            resume_from = 0
                        if verdict in (_SingleVerdict.STREAM, _SingleVerdict.STREAM_FROM_ZERO):
                            with response:
                                return save_file_with_progress(
                                    response, final_path, self.download_info.task,
                                    self.live_manager,
                                    download_url=self.download_info.download_link,
                                    download_headers=headers, resume_from=resume_from,
                                    manifest=manifest, cancel_event=self._ctx.cancel_event,
                                )
                        response.close()
            except Cancelled:
                return DownloadOutcome.RETRYABLE_FAILURE

            # ---- outside the slot ----
            if failure is not None:
                if not self._handle_request_exception(failure, attempt):
                    break
                attempt += 1
                continue
            if verdict is _SingleVerdict.RESET:
                if self._resets >= self._caps().manifest_reset_max:
                    return DownloadOutcome.TERMINAL_FAILURE
                self._resets += 1
                discard_partial(temp_path)
                manifest = self._fresh_manifest(1, manifest)
                continue
            # _SingleVerdict.REFRESH
            if self._refreshes >= self._caps().link_refresh_max:
                return DownloadOutcome.RETRYABLE_FAILURE
            fresh = self._take_refresh()
            if fresh is not None:
                replan = self._replan_after_refresh(fresh, manifest, temp_path, headers)
                if replan is not None:
                    if replan.mode is TransferMode.SEGMENTED:
                        return self._run_segmented(replan, temp_path, final_path, headers)
                    manifest = replan.manifest
        return DownloadOutcome.RETRYABLE_FAILURE

    def _refresh_link(self) -> str | None:
        """Re-resolve the signed CDN URL from the item page; ``None`` if impossible."""
        item_page = self.download_info.item_page
        if not item_page:
            return None
        network = self.session_info.network
        page_headers = network.headers if network is not None else None
        try:
            page = requests.get(item_page, headers=page_headers, timeout=20)
            page.raise_for_status()
            soup = BeautifulSoup(page.text, "html.parser")
            link = get_signed_download_url(soup, network=network)
        except (RequestException, ValueError, AttributeError):
            return None
        if link:
            self.live_manager.update_log(
                event="Download progress",
                details=f"Signed URL expired; re-resolved {self.download_info.filename}.",
            )
        return link

    def download(self) -> dict | None:
        """Handle the download process."""
        if self._ctx.cancelled:
            return None
        is_final_attempt = self.retries == 1
        is_offline = subdomain_is_offline(
            self.download_info.download_link,
            self.session_info.bunkr_status,
        )

        if is_offline and is_final_attempt:
            self.live_manager.update_log(
                event="Non-operational subdomain",
                details=f"The subdomain for {self.download_info.filename} is offline. "
                "Check the log file.",
            )
            write_on_session_log(self.download_info.download_link)
            self.live_manager.update_task(self.download_info.task, visible=False)
            return None

        formatted_filename = truncate_filename(self.download_info.filename)
        final_path = Path(self.session_info.download_path) / formatted_filename

        # Skip download if the file exists or is blacklisted
        if self._skip_file_download(final_path):
            return None

        # Attempt to download the file with retries
        outcome = self.attempt_download(final_path)

        # Handle failed download after retries
        if outcome is not DownloadOutcome.SUCCESS:
            return self._handle_failed_download(
                is_final_attempt=is_final_attempt, cancelled=self._ctx.cancelled,
            )

        return None

    # Private methods
    def _skip_file_download(self, final_path: str) -> bool:
        """Determine whether a file should be skipped during download.

        This method checks the following conditions:
        - If the file already exists at the specified path.
        - If the file's name matches any pattern in the ignore list.
        - If the file's name does not match any pattern in the include list.

        If any of these conditions are met, the download is skipped, and appropriate
        logs are updated.
        """
        ignore_list = getattr(self.session_info.args, "ignore", [])
        include_list = getattr(self.session_info.args, "include", [])

        def log_and_skip_event(reason: str) -> bool:
            """Log the skip reason and updates the task before."""
            self.live_manager.update_log(event="Skipped download", details=reason)
            self.live_manager.update_task(
                self.download_info.task,
                completed=100,
                visible=False,
            )
            return True

        # Check if the file already exists
        if Path(final_path).exists():
            return log_and_skip_event(
                f"{self.download_info.filename} has already been downloaded.",
            )

        # Check if the file is in the ignore list
        if ignore_list and any(
            word in self.download_info.filename for word in ignore_list
        ):
            return log_and_skip_event(
                f"{self.download_info.filename} matches the ignore list.",
            )

        # Check if the file is not in the include list
        if include_list and all(
            word not in self.download_info.filename for word in include_list
        ):
            return log_and_skip_event(
                f"No included words found for {self.download_info.filename}.",
            )

        # If none of the skip conditions are met, do not skip
        return False

    def _retry_with_backoff(
        self, attempt: int, *, event: str, maintenance_delay: bool = False
    ) -> bool:
        """Log error, apply backoff, and return True if should retry."""
        self.live_manager.update_log(
            event=event,
            details=f"{event} for {self.download_info.filename} "
            f"({attempt + 1}/{self.retries})...",
        )

        if attempt < self.retries - 1:
            if maintenance_delay:
                # Longer delays for maintenance (env knob; default 2/5/10 min)
                delays = MAINTENANCE_BACKOFF_DELAYS_SECONDS
                delay = delays[min(attempt, len(delays) - 1)]
                delay += random.uniform(1, 10)  # noqa: S311
            else:
                # Standard exponential backoff
                delay = 3 ** (attempt + 1) + random.uniform(1, 3)  # noqa: S311

            return self._pause(delay)

        return False

    def _handle_request_exception(
        self, req_err: RequestException, attempt: int,
    ) -> bool:
        """Handle exceptions during the request and manages retries."""
        is_server_down = (
            req_err.response is None
            or req_err.response.status_code == HTTPStatus.SERVER_DOWN
        )

        # Mark the subdomain as offline and potentially retry based on status check
        if is_server_down:
            subdomain = get_subdomain(self.download_info.download_link)

            # Check if status checking is enabled and not explicitly disabled
            skip_status_check = getattr(
                self.session_info.args, "skip_status_check", False
            ) if self.session_info.args else False

            if STATUS_CHECK_ON_FAILURE and not skip_status_check:
                # Fetch real-time status from the status page
                cache_ttl = getattr(
                    self.session_info.args, "status_cache_ttl", 60
                ) if self.session_info.args else 60

                current_status, was_updated = refresh_server_status(
                    subdomain,
                    self.session_info.bunkr_status,
                    cache_ttl_seconds=cache_ttl,
                    network=self.session_info.network,
                )

                status_check_msg = "(refreshed)" if was_updated else "(cached)"

                # Check if server is under maintenance
                if "Maintenance" in current_status or "maintenance" in current_status.lower():
                    # Log maintenance event to session log
                    log_maintenance_event(
                        subdomain, current_status, self.download_info.download_link
                    )

                    maintenance_details = (
                        f"{subdomain} is under maintenance {status_check_msg}: "
                        f"{current_status}. File {self.download_info.filename} "
                        f"will be retried."
                    )
                    self.live_manager.update_maintenance(
                        subdomain=subdomain,
                        status=current_status,
                        affected_files_count=1,
                        event="Maintenance detected",
                        details=maintenance_details,
                    )

                    # Get maintenance strategy
                    maintenance_strategy = getattr(
                        self.session_info.args, "maintenance_strategy", "backoff"
                    ) if self.session_info.args else "backoff"

                    if maintenance_strategy == "skip":
                        # Log and skip this file
                        self.live_manager.update_log(
                            event="Maintenance skip",
                            details=(
                                f"Skipping {self.download_info.filename} due to "
                                f"maintenance (strategy: skip)."
                            ),
                        )
                        return False

                    # Use backoff strategy with longer delays for maintenance
                    return self._retry_with_backoff(
                        attempt,
                        event="Waiting for maintenance",
                        maintenance_delay=True
                    )

                # Status page says operational but we got 521 - transient issue
                if current_status == "Operational":
                    self.live_manager.update_log(
                        event="Transient error",
                        details=(
                            f"{subdomain} reported operational {status_check_msg} "
                            f"but returned 521. Retrying {self.download_info.filename}..."
                        ),
                    )
                    return self._retry_with_backoff(
                        attempt, event="Retrying transient failure"
                    )

            # Fallback: mark as offline and don't retry
            marked_subdomain = mark_subdomain_as_offline(
                self.session_info.bunkr_status,
                self.download_info.download_link,
            )
            self.live_manager.update_log(
                event="No response",
                details=f"Subdomain {marked_subdomain} has been marked as offline.",
            )
            return False

        if req_err.response.status_code in (
            HTTPStatus.TOO_MANY_REQUESTS,
            HTTPStatus.SERVICE_UNAVAILABLE,
        ):
            return self._retry_with_backoff(attempt, event="Retrying download")

        if req_err.response.status_code == HTTPStatus.BAD_GATEWAY:
            # Check status on 502 errors as well
            skip_status_check = getattr(
                self.session_info.args, "skip_status_check", False
            ) if self.session_info.args else False

            if STATUS_CHECK_ON_FAILURE and not skip_status_check:
                subdomain = get_subdomain(self.download_info.download_link)
                cache_ttl = getattr(
                    self.session_info.args, "status_cache_ttl", 60
                ) if self.session_info.args else 60

                current_status, _ = refresh_server_status(
                    subdomain,
                    self.session_info.bunkr_status,
                    cache_ttl_seconds=cache_ttl,
                    network=self.session_info.network,
                )

                if "Maintenance" in current_status or "maintenance" in current_status.lower():
                    # Log maintenance event to session log
                    log_maintenance_event(
                        subdomain, current_status, self.download_info.download_link
                    )

                    self.live_manager.update_maintenance(
                        subdomain=subdomain,
                        status=current_status,
                        affected_files_count=1,
                        event="Maintenance detected (502)",
                        details=(
                            f"{subdomain} maintenance during bad gateway for "
                            f"{self.download_info.filename}."
                        ),
                    )
                    return self._retry_with_backoff(
                        attempt,
                        event="Waiting for maintenance",
                        maintenance_delay=True
                    )

            self.live_manager.update_log(
                event="Server error",
                details=f"Bad gateway for {self.download_info.filename}.",
            )
            # Setting retries to 1 forces an immediate failure on the next check.
            self.retries = 1
            return False

        # Do not retry, exit the loop
        self.live_manager.update_log(event="Request error", details=str(req_err))
        return False

    def _handle_failed_download(
        self, *, is_final_attempt: bool, cancelled: bool = False,
    ) -> dict | None:
        """Handle a failed download after all retry attempts.

        A ``cancelled`` job is never queued for the retry pass nor written to
        the session log: its partial stays on disk for a later run.
        """
        if cancelled:
            self.live_manager.update_log(
                event="Download stopped",
                details=f"Stopped {self.download_info.filename}: the job was cancelled.",
            )
            self.live_manager.update_task(self.download_info.task, visible=False)
            return None

        if not is_final_attempt:
            self.live_manager.update_log(
                event="Exceeded retry attempts",
                details=f"Max retries reached for {self.download_info.filename}. "
                "It will be retried one more time after all other tasks.",
            )
            return {
                "id": self.download_info.task,
                "filename": self.download_info.filename,
                "download_link": self.download_info.download_link,
                # item_page is carried forward so _retry_failed_download can
                # re-resolve a fresh signed CDN URL instead of replaying a
                # stale one. Defaults to None when MediaDownloader was used
                # standalone (single-file download path).
                "item_page": self.download_info.item_page,
            }

        self.live_manager.update_log(
            event="Download failed",
            details=f"Failed to download {self.download_info.filename}. "
            "Check the log file.",
        )
        self.live_manager.update_task(self.download_info.task, visible=False)
        return None
