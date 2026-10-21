# tests/helpers/range_server.py
"""Tiny HTTP server for transfer tests: Range support plus fault injection."""

from __future__ import annotations

import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FILE_SIZE = 5 * 1024 * 1024
CHUNK_SIZE = 65536


class RangeServer:  # pylint: disable=too-many-instance-attributes
    """Owns a background ThreadingHTTPServer serving one in-memory file."""

    def __init__(self) -> None:  # pylint: disable=too-many-statements
        rng = random.Random(1234)
        self.data = bytes(rng.getrandbits(8) for _ in range(FILE_SIZE))
        self.etag = '"test-etag-1"'
        self.ignore_range = False
        self.no_ranges = False
        self.forbid_from_request: int | None = None
        self.abort_once_after: int | None = None
        self.chunk_delay = 0.0          # seconds slept after each body chunk (throttle)
        self.get_count = 0
        self.in_flight = 0
        self.peak_in_flight = 0
        self._lock = threading.Lock()
        self._aborted_once = False
        server = self

        class Handler(BaseHTTPRequestHandler):  # pylint: disable=missing-class-docstring
            protocol_version = "HTTP/1.1"
            counted = False      # this request is included in server.in_flight

            def log_message(self, *_args):  # silence
                return

            def _common_headers(self, length: int) -> None:
                self.send_header("Content-Length", str(length))
                self.send_header("ETag", server.etag)
                if not server.no_ranges:
                    self.send_header("Accept-Ranges", "bytes")

            def do_HEAD(self):  # pylint: disable=invalid-name
                """Answer HEAD with length, ETag and range support."""
                self.send_response(200)
                self._common_headers(len(server.data))
                self.end_headers()

            def do_GET(self):  # pylint: disable=invalid-name
                """Serve GET with fault injection and counters."""
                with server._lock:  # pylint: disable=protected-access
                    server.get_count += 1
                    count = server.get_count
                    server.in_flight += 1
                    server.peak_in_flight = max(server.peak_in_flight, server.in_flight)
                self.counted = True
                try:
                    self._respond_get(count)
                finally:
                    self._leave()

            def _leave(self) -> None:
                """Stop counting this request as in flight (idempotent per request)."""
                if self.counted:
                    self.counted = False
                    with server._lock:  # pylint: disable=protected-access
                        server.in_flight -= 1

            def _respond_get(self, count: int) -> None:
                if server.forbid_from_request is not None and count >= server.forbid_from_request:
                    self.send_response(403)
                    self._common_headers(0)
                    self.end_headers()
                    return
                rng_header = self.headers.get("Range")
                start, end = 0, len(server.data) - 1
                status = 200
                if rng_header and not (server.ignore_range or server.no_ranges):
                    spec = rng_header.replace("bytes=", "")
                    lo, _, hi = spec.partition("-")
                    start = int(lo)
                    end = min(int(hi), len(server.data) - 1) if hi else end
                    if start >= len(server.data):
                        self.send_response(416)
                        self._common_headers(0)
                        self.send_header("Content-Range", f"bytes */{len(server.data)}")
                        self.end_headers()
                        return
                    status = 206
                body = server.data[start:end + 1]
                self.send_response(status)
                self._common_headers(len(body))
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(server.data)}")
                self.end_headers()
                with server._lock:  # pylint: disable=protected-access
                    abort_at = None
                    will_abort = (
                        server.abort_once_after is not None
                        and not server._aborted_once  # pylint: disable=protected-access
                        and server.abort_once_after < len(body)
                    )
                    if will_abort:
                        server._aborted_once = True  # pylint: disable=protected-access
                        abort_at = server.abort_once_after
                self._send_body(body, abort_at)

            def _send_body(self, body: bytes, abort_at: int | None) -> None:
                sent = 0
                try:
                    for offset in range(0, len(body), CHUNK_SIZE):
                        chunk = body[offset:offset + CHUNK_SIZE]
                        if offset + CHUNK_SIZE >= len(body):
                            # Leave before the final bytes: once the client has them it
                            # releases its slot, and the next GET must not overlap this one.
                            self._leave()
                        if abort_at is not None and sent + len(chunk) > abort_at:
                            self.wfile.write(chunk[: max(0, abort_at - sent)])
                            self.wfile.flush()
                            self.close_connection = True
                            self.connection.close()
                            return
                        self.wfile.write(chunk)
                        sent += len(chunk)
                        if server.chunk_delay and offset + CHUNK_SIZE < len(body):
                            time.sleep(server.chunk_delay)
                except (BrokenPipeError, ConnectionResetError):
                    # Client disconnected mid-body: return quietly, no socketserver traceback.
                    self.close_connection = True

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}/file.bin"

    def reset(self) -> None:
        """Clear counters and fault flags between scenarios."""
        self.ignore_range = False
        self.no_ranges = False
        self.forbid_from_request = None
        self.abort_once_after = None
        self.chunk_delay = 0.0
        self.get_count = 0
        self.peak_in_flight = 0
        self._aborted_once = False

    def close(self) -> None:
        """Stop the server."""
        self._httpd.shutdown()
        self._httpd.server_close()
