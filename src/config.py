"""Configuration module for managing constants and settings used across the project.

These configurations aim to improve modularity and readability by consolidating
settings into a single location.
"""

from __future__ import annotations

import os
from argparse import ArgumentParser
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace


# ============================
# Paths and Files
# ============================
DOWNLOAD_FOLDER = "Downloads"  # The folder where downloaded files will be stored.
URLS_FILE = "URLs.txt"         # The file containing the list of URLs to process.
SESSION_LOG = os.getenv("SESSION_LOG_PATH", "session.log")  # The file used to log errors.
MIN_DISK_SPACE_GB = 2          # Minimum free disk space (in GB) required.

# ============================
# API / Status Endpoints
# ============================
DEFAULT_STATUS_PAGE = os.getenv(
    "BUNKR_STATUS_URL",
    "https://status.bunkr.ru/",
)
DEFAULT_BUNKR_API = os.getenv(
    "BUNKR_API_URL",
    "https://bunkr.cr/api/vs",
)
DEFAULT_DOWNLOAD_REFERER = os.getenv(
    "BUNKR_DOWNLOAD_REFERER",
    "https://get.bunkrr.su/",
)
DEFAULT_USER_AGENT = os.getenv(
    "BUNKR_USER_AGENT",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0",
)
DEFAULT_FALLBACK_DOMAIN = os.getenv("BUNKR_FALLBACK_DOMAIN", "bunkr.cr")

STATUS_PAGE = DEFAULT_STATUS_PAGE  # The URL of the status page for checking
                                   # service availability.
BUNKR_API = DEFAULT_BUNKR_API      # The API for retrieving encryption data.
FALLBACK_DOMAIN = DEFAULT_FALLBACK_DOMAIN

# ============================
# Regex Patterns
# ============================
MEDIA_SLUG_REGEX = r'const\s+slug\s*=\s*"([a-zA-Z0-9_-]+)"'  # Extract media slug.
VALID_SLUG_REGEX = r"^[a-zA-Z0-9_-]+$"                       # Validate media slug.
VALID_CHARACTERS_REGEX = r"[^a-zA-Z0-9 _-]"                  # Validate characters.

# ============================
# UI & Table Settings
# ============================
BUFFER_SIZE = 5                   # Maximum number of items showed in buffers.
PROGRESS_COLUMNS_SEPARATOR = "•"  # Visual separator used between progress bar columns.

# Colors used for the progress manager UI elements
PROGRESS_MANAGER_COLORS = {
    "title_color": "light_cyan3",           # Title color for progress panels.
    "overall_border_color": "bright_blue",  # Border color for overall progress panel.
    "task_border_color": "medium_purple",   # Border color for task progress panel.
}

# Setting used for the log manager UI elements
LOG_MANAGER_CONFIG = {
    "colors": {
        "title_color": "light_cyan3",  # Title color for log panel.
        "border_color": "cyan",        # Border color for log panel.
    },
    "min_column_widths": {
        "Timestamp": 10,
        "Event": 15,
        "Details": 30,
    },
    "column_styles": {
        "Timestamp": "pale_turquoise4",
        "Event": "pale_turquoise1",
        "Details": "pale_turquoise4",
    },
}

# ============================
# Download Settings
# ============================
MAX_FILENAME_LEN = 120  # The maximum length for a file name.
MAX_WORKERS = 3         # The maximum number of threads for concurrent downloads.

# Status page checking behavior
STATUS_CHECK_ON_FAILURE = (
    os.getenv("STATUS_CHECK_ON_FAILURE", "true").lower() == "true"
)
STATUS_CACHE_TTL_SECONDS = int(os.getenv("STATUS_CACHE_TTL_SECONDS", "60"))
# Strategy: 'backoff' (retry with delays) or 'skip' (log and skip)
MAINTENANCE_RETRY_STRATEGY = os.getenv("MAINTENANCE_RETRY_STRATEGY", "backoff")

# Mapping of URL identifiers to a boolean for album (True) vs single file (False).
URL_TYPE_MAPPING = {"a": True, "f": False, "i": False, "v": False}

# Constants for file sizes, expressed in bytes.
KB = 1024
MB = 1024 * KB
GB = 1024 * MB

# Thresholds for file sizes and corresponding chunk sizes used during download.
THRESHOLDS = [
    (1 * MB, 32 * KB),    # Less than 1 MB
    (10 * MB, 128 * KB),  # 1 MB to 10 MB
    (50 * MB, 512 * KB),  # 10 MB to 50 MB
    (100 * MB, 1 * MB),   # 50 MB to 100 MB
    (250 * MB, 2 * MB),   # 100 MB to 250 MB
    (500 * MB, 4 * MB),   # 250 MB to 500 MB
    (1 * GB, 8 * MB),     # 500 MB to 1 GB
]

# Default chunk size for files larger than the largest threshold.
LARGE_FILE_CHUNK_SIZE = 16 * MB

# ============================
# HTTP / Network
# ============================
class HTTPStatus(IntEnum):
    """Enumeration of common HTTP status codes used in the project."""

    OK = 200
    FORBIDDEN = 403
    TOO_MANY_REQUESTS = 429
    INTERNAL_ERROR = 500
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    SERVER_DOWN = 521

# Mapping of HTTP error codes to human-readable fetch error messages.
FETCH_ERROR_MESSAGES: dict[HTTPStatus, str] = {
    HTTPStatus.FORBIDDEN: "DDoSGuard blocked the request to {url}",
    HTTPStatus.INTERNAL_ERROR: "Internal server error when fetching {url}",
    HTTPStatus.BAD_GATEWAY: "Bad gateway for {url}, probably offline",
}

# Headers used for general HTTP requests.
HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
}

# Headers specifically tailored for download requests.
DOWNLOAD_HEADERS: dict[str, str] = {
    "User-Agent": HEADERS["User-Agent"],
    "Connection": "keep-alive",
    "Referer": DEFAULT_DOWNLOAD_REFERER,
}

# ============================
# Data Classes
# ============================
@dataclass
class DownloadInfo:
    """Represent the information related to a download task."""

    download_link: str
    filename: str
    task: int

@dataclass
class SessionInfo:
    """Hold the session-related information."""

    args: Namespace | None
    bunkr_status: dict[str, str]
    download_path: str


def update_network_settings(
    *,
    status_page: str | None = None,
    api_endpoint: str | None = None,
    download_referer: str | None = None,
    user_agent: str | None = None,
    fallback_domain: str | None = None,
) -> None:
    """Update global network configuration used for Bunkr requests."""

    module_globals = globals()

    if status_page:
        module_globals["STATUS_PAGE"] = str(status_page)

    if api_endpoint:
        module_globals["BUNKR_API"] = str(api_endpoint)

    if fallback_domain:
        module_globals["FALLBACK_DOMAIN"] = str(fallback_domain)

    if user_agent:
        user_agent_str = str(user_agent)
        HEADERS["User-Agent"] = user_agent_str
        DOWNLOAD_HEADERS["User-Agent"] = user_agent_str

    if download_referer:
        DOWNLOAD_HEADERS["Referer"] = str(download_referer)


def get_network_settings() -> dict[str, str]:
    """Return the currently active Bunkr networking settings."""

    download_referer = DOWNLOAD_HEADERS.get("Referer")
    user_agent = HEADERS.get("User-Agent")

    return {
        "status_page": str(STATUS_PAGE),
        "api_endpoint": str(BUNKR_API),
        "download_referer": str(download_referer) if download_referer else "",
        "user_agent": str(user_agent) if user_agent else "",
        "fallback_domain": str(FALLBACK_DOMAIN),
    }


def apply_argument_overrides(args: Namespace | None) -> None:
    """Apply network overrides captured from CLI or API namespaces."""

    if args is None:
        return

    update_network_settings(
        status_page=getattr(args, "status_page", None),
        api_endpoint=getattr(args, "bunkr_api", None),
        download_referer=getattr(args, "download_referer", None),
        user_agent=getattr(args, "user_agent", None),
        fallback_domain=getattr(args, "fallback_domain", None),
    )

@dataclass
class AlbumInfo:
    """Store the information about an album and its associated item pages."""

    album_id: str
    item_pages: list[str]

@dataclass
class ProgressConfig:
    """Configuration for progress bar settings."""

    task_name: str
    item_description: str
    color: str = PROGRESS_MANAGER_COLORS["title_color"]
    panel_width = 40
    overall_buffer: deque = field(default_factory=lambda: deque(maxlen=BUFFER_SIZE))


# ============================
# Argument Parsing
# ============================
def add_common_arguments(parser: ArgumentParser) -> None:
    """Add arguments shared across parsers."""
    parser.add_argument(
        "--custom-path",
        type=str,
        default=None,
        help="The directory where the downloaded content will be saved.",
    )
    parser.add_argument(
        "--disable-ui",
        action="store_true",
        help="Disable the user interface.",
    )
    parser.add_argument(
        "--disable-disk-check",
        action="store_true",
        help="Disable the disk space check for available free space.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=MAX_WORKERS,
        help="Maximum concurrent downloads for album items (default: %(default)s).",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Verbosity used for runtime logs.",
    )
    parser.add_argument(
        "--status-page",
        type=str,
        default=STATUS_PAGE,
        help="Override the Bunkr status page URL (default: %(default)s).",
    )
    parser.add_argument(
        "--bunkr-api",
        type=str,
        default=BUNKR_API,
        help="Override the Bunkr API endpoint (default: %(default)s).",
    )
    parser.add_argument(
        "--download-referer",
        type=str,
        default=DOWNLOAD_HEADERS.get("Referer", DEFAULT_DOWNLOAD_REFERER),
        help="Referer header sent with download requests (default: %(default)s).",
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        default=HEADERS.get("User-Agent", DEFAULT_USER_AGENT),
        help="User agent string for HTTP requests (default: %(default)s).",
    )
    parser.add_argument(
        "--fallback-domain",
        type=str,
        default=FALLBACK_DOMAIN,
        help="Fallback Bunkr domain used after 403 responses (default: %(default)s).",
    )
    parser.add_argument(
        "--skip-status-check",
        action="store_true",
        help="Disable real-time status page checks on download failures.",
    )
    parser.add_argument(
        "--status-cache-ttl",
        type=int,
        default=STATUS_CACHE_TTL_SECONDS,
        help=(
            "Cache duration for status page results in seconds "
            "(default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--maintenance-strategy",
        choices=["backoff", "skip"],
        default=MAINTENANCE_RETRY_STRATEGY,
        help=(
            "Strategy for handling maintenance: 'backoff' retries with delays, "
            "'skip' logs and skips (default: %(default)s)."
        ),
    )


def setup_parser(
        *, include_url: bool = False, include_filters: bool = False,
    ) -> ArgumentParser:
    """Set up parser with optional argument groups."""
    parser = ArgumentParser(description="Command-line arguments.")

    if include_url:
        parser.add_argument("url", type=str, help="The URL to process")

    if include_filters:
        parser.add_argument(
            "--ignore",
            type=str,
            nargs="+",
            help="Skip files whose names contain any of these substrings.",
        )
        parser.add_argument(
            "--include",
            type=str,
            nargs="+",
            help="Only download files whose names contain these substrings.",
        )

    add_common_arguments(parser)
    return parser


def parse_arguments(*, common_only: bool = False) -> Namespace:
    """Full argument parser (including URL, filters, and common)."""
    parser = (
        setup_parser() if common_only
        else setup_parser(include_url=True, include_filters=True)
    )
    return parser.parse_args()
