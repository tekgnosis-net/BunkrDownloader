"""Python-based downloader for Bunkr albums and files.

Usage:
    Run the script from the command line with a valid album or media URL:
        python3 downloader.py <album_or_media_url>
"""

from __future__ import annotations

import asyncio
import sys
import logging
from typing import TYPE_CHECKING

from requests.exceptions import ConnectionError as RequestConnectionError
from requests.exceptions import RequestException, Timeout

from src.bunkr_utils import get_bunkr_status_cached
from src.config import (
    AlbumInfo,
    DownloadInfo,
    SessionInfo,
    MAX_WORKERS,
    apply_argument_overrides,
    build_network_context,
    parse_arguments,
)
from src.crawlers.crawler_utils import (
    extract_all_album_item_pages,
    get_download_info,
)
from src.downloaders.album_downloader import AlbumDownloader, MediaDownloader
from src.downloaders.transfer_context import TransferContext, make_transfer_context
from src.crawlers.api_utils import detect_item_page_maintenance
from src.file_utils import (
    create_download_directory,
    format_directory_name,
    log_maintenance_event,
)
from src.general_utils import (
    check_disk_space,
    check_python_version,
    clear_terminal,
    fetch_page,
)
from src.managers.live_manager import initialize_managers
from src.url_utils import (
    check_url_type,
    get_album_id,
    get_album_name,
    get_host_page,
    get_identifier,
)

if TYPE_CHECKING:
    from argparse import Namespace

    from bs4 import BeautifulSoup

    from src.managers.live_manager import LiveManager


async def handle_download_process(
    session_info: SessionInfo,
    url: str,
    initial_soup: BeautifulSoup,
    live_manager: LiveManager,
    transfer_context: TransferContext | None = None,
) -> None:
    """Handle the download process for a Bunkr album or a single item.

    ``transfer_context`` (the job's settings, connection governor and cancel
    flag) is shared by every file; one is built from the args when omitted.
    """
    if transfer_context is None:
        transfer_context = make_transfer_context(session_info.args)
    if session_info.args:
        log_level = getattr(session_info.args, "log_level", "info")
        max_workers = getattr(session_info.args, "max_workers", MAX_WORKERS)
    else:
        log_level = "info"
        max_workers = MAX_WORKERS
    host_page = get_host_page(url)
    identifier = get_identifier(url, soup=initial_soup)

    if log_level.lower() == "debug":
        live_manager.update_log(
            event="Debug",
            details=f"Resolved identifier {identifier} for {url}",
        )

    # Album download
    if check_url_type(url):
        item_pages = await extract_all_album_item_pages(
            initial_soup, host_page, url, network=session_info.network,
        )
        await AlbumDownloader(
            session_info=session_info,
            album_info=AlbumInfo(album_id=identifier, item_pages=item_pages),
            live_manager=live_manager,
            transfer_context=transfer_context,
        ).download_album(max_workers=max_workers)

    # Single item download
    else:
        download_link, filename = await get_download_info(
            url, initial_soup, network=session_info.network,
        )
        if not download_link:
            maintenance = detect_item_page_maintenance(initial_soup)
            if maintenance:
                # The file's server is under maintenance: record it for a
                # later retry and say so, instead of a generic failure.
                log_maintenance_event("Unknown", "Maintenance", url)
                live_manager.update_maintenance(
                    subdomain="Unknown",
                    status="Maintenance",
                    affected_files_count=1,
                    event="Maintenance detected",
                    details=f"Item page for {filename or url} says: {maintenance}",
                )
                return
            # Bunkr API failed (network error, non-200 response) — mirror the
            # album-path behaviour of skipping rather than passing None into
            # requests.get and blowing up with a cryptic TypeError.
            live_manager.update_log(
                event="Download link unresolved",
                details=f"Could not resolve a download URL for {filename or url}",
            )
            return
        live_manager.add_overall_task(identifier, num_tasks=1)
        task = live_manager.add_task()

        media_downloader = MediaDownloader(
            session_info=session_info,
            download_info=DownloadInfo(
                download_link=download_link,
                filename=filename,
                task=task,
                # The item page lets an expired signed URL be re-resolved mid-transfer.
                item_page=url,
            ),
            live_manager=live_manager,
            transfer_context=transfer_context,
        )
        # Off the event loop, like album items: the loop stays responsive (web
        # progress, cancellation) and a cancel reaches the worker via the event.
        await asyncio.to_thread(media_downloader.download)


async def validate_and_download(
    bunkr_status: dict[str, str],
    url: str,
    live_manager: LiveManager,
    args: Namespace | None = None,
    transfer_context: TransferContext | None = None,
) -> None:
    """Validate the provided URL, and initiate the download process.

    ``transfer_context`` lets the caller own the job's cancel flag (the web
    layer sets it from the cancel endpoint); one is built from ``args`` when
    omitted. Ctrl-C (``KeyboardInterrupt``) or task cancellation sets the
    flag so download threads stop within one chunk, leaving resumable
    partials.
    """
    if transfer_context is None:
        transfer_context = make_transfer_context(args)
    log_level = getattr(args, "log_level", "info") if args else "info"
    logging.getLogger().setLevel(log_level.upper())

    # Check the available disk space on the download path before starting the download
    if args and not args.disable_disk_check:
        check_disk_space(live_manager, custom_path=args.custom_path)
    elif args and args.disable_disk_check and log_level.lower() == "debug":
        live_manager.update_log(
            event="Debug",
            details="Disk space check skipped by configuration",
        )

    network = build_network_context(args)
    soup = await fetch_page(url, network=network)
    if soup is None:
        live_manager.update_log(
            event="Fetch failed",
            details=f"Unable to load page content for {url}. Please verify the link and retry.",
        )
        raise RuntimeError(f"Failed to fetch page for {url}")
    album_id = get_album_id(url) if check_url_type(url) else None
    album_name = get_album_name(soup)

    directory_name = format_directory_name(album_name, album_id)
    download_path = create_download_directory(
        directory_name,
        custom_path=args.custom_path,
    )
    session_info = SessionInfo(
        args=args,
        bunkr_status=bunkr_status,
        download_path=download_path,
        network=network,
    )

    if log_level.lower() == "debug":
        live_manager.update_log(
            event="Debug",
            details=(
                f"Prepared session for '{album_name or 'single file'}'"
                f" at {download_path}"
            ),
        )

    try:
        max_workers = getattr(args, "max_workers", MAX_WORKERS) if args else MAX_WORKERS
        if log_level.lower() == "debug":
            live_manager.update_log(
                event="Debug",
                details=f"Using {max_workers} concurrent worker(s) for album downloads",
            )
        await handle_download_process(
            session_info,
            url,
            soup,
            live_manager,
            transfer_context,
        )

    except (KeyboardInterrupt, asyncio.CancelledError):
        # Worker threads under asyncio.to_thread outlive the cancelled
        # coroutine; the event is what actually stops them.
        transfer_context.cancel_event.set()
        raise

    except (RequestConnectionError, Timeout, RequestException) as err:
        raise RuntimeError(f"Error downloading from {url}: {err}") from err


async def main() -> None:
    """Initialize the download process."""
    clear_terminal()
    check_python_version()

    args = parse_arguments()
    apply_argument_overrides(args)
    bunkr_status = get_bunkr_status_cached(build_network_context(args)) or {}
    live_manager = initialize_managers(
        disable_ui=args.disable_ui,
        log_level=getattr(args, "log_level", "info"),
    )

    try:
        with live_manager.live:
            await validate_and_download(
                bunkr_status,
                args.url,
                live_manager,
                args=args,
            )
            live_manager.stop()

    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Python >= 3.11 re-raises Ctrl-C here after cancelling main().
        sys.exit(1)
