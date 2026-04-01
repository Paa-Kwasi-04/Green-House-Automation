"""HTTP image server and uploader utilities for greenhouse photos."""

import json
import ipaddress
import logging
import mimetypes
import os
import socket
import ssl
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional, Tuple
from urllib import request
from urllib.parse import quote, unquote, urlparse

logger = logging.getLogger(__name__)


def detect_lan_ip() -> str:
    """Detect a likely LAN IPv4 address for external URL construction.

    Returns
    -------
    str
        Detected non-loopback IPv4 address, or ``127.0.0.1`` as fallback.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # No packet is sent; connect() is used only to pick the outbound interface.
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def _detect_tailscale_ip() -> Optional[str]:
    """Detect local Tailscale IPv4 address.

    Returns
    -------
    str or None
        First IPv4 from ``tailscale ip -4`` when available, otherwise ``None``.
    """
    try:
        output = subprocess.check_output(
            ["tailscale", "ip", "-4"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if output:
            # tailscale may return multiple IPv4 lines; prefer the first one.
            return output.splitlines()[0].strip()
    except Exception:
        return None
    return None


def _normalize_public_base_url(raw_value: str, default_scheme: str = "http") -> str:
    """Normalize a public base URL string.

    Parameters
    ----------
    raw_value : str
        Input URL or host value, with or without scheme.
    default_scheme : str, optional
        Scheme inserted when missing.

    Returns
    -------
    str
        Normalized URL without trailing slash, or empty string for empty input.
    """
    raw = (raw_value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"{default_scheme}://{raw}"
    parsed = urlparse(raw)
    if not parsed.netloc and parsed.path:
        # Handles values like "example.com:8000" that urlparse treats as path.
        raw = f"{default_scheme}://{parsed.path}"
    return raw.rstrip("/")


def host_is_local_or_private(host: str) -> bool:
    """Check whether a host resolves to local/private scope.

    Parameters
    ----------
    host : str
        Hostname or IP address.

    Returns
    -------
    bool
        ``True`` for loopback/private/link-local IPs and localhost aliases.
    """
    host_value = (host or "").strip().lower()
    if host_value in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True
    try:
        ip_obj = ipaddress.ip_address(host_value)
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
    except ValueError:
        # Hostname/domain: cannot determine scope reliably.
        return False


def resolve_public_base_url(http_public_host: str, http_port: int) -> str:
    """Resolve externally shared base URL from environment and runtime hints.

    Parameters
    ----------
    http_public_host : str
        Fallback host used when no explicit public URL can be resolved.
    http_port : int
        HTTP port used for generated fallback URLs.

    Returns
    -------
    str
        Resolved base URL using priority:
        explicit public URL, Tailscale funnel URL, Tailscale host, detected
        Tailscale IP, then fallback host+port.
    """
    explicit_public = _normalize_public_base_url(
        os.getenv("GREENHOUSE_PUBLIC_BASE_URL", ""),
        default_scheme="http",
    )
    if explicit_public:
        return explicit_public

    funnel_public = _normalize_public_base_url(
        os.getenv("GREENHOUSE_TAILSCALE_FUNNEL_URL", ""),
        default_scheme="https",
    )
    if funnel_public:
        return funnel_public

    tailnet_host = (os.getenv("GREENHOUSE_TAILSCALE_HOST", "") or "").strip()
    if tailnet_host:
        tailnet_scheme = (os.getenv("GREENHOUSE_TAILSCALE_SCHEME", "http") or "http").strip().lower()
        if tailnet_scheme not in {"http", "https"}:
            logger.warning(
                "Invalid GREENHOUSE_TAILSCALE_SCHEME=%s. Using http.",
                tailnet_scheme,
            )
            tailnet_scheme = "http"
        return _normalize_public_base_url(tailnet_host, default_scheme=tailnet_scheme)

    ts_ip = _detect_tailscale_ip()
    if ts_ip:
        return f"http://{ts_ip}:{http_port}"

    return f"http://{http_public_host}:{http_port}"


def latest_served_image_url(upload_dir: str, image_base_url: str) -> Optional[str]:
    """Return URL of the latest image currently available on the HTTP server.

    Parameters
    ----------
    upload_dir : str
        Directory containing served image files.
    image_base_url : str
        Public base URL prefix for image serving endpoint.

    Returns
    -------
    str or None
        URL to most recently modified image file, or ``None`` when unavailable.
    """
    try:
        if not os.path.isdir(upload_dir):
            return None
        candidates = []
        for name in os.listdir(upload_dir):
            if name.lower().endswith((".jpg", ".jpeg", ".png")):
                full_path = os.path.join(upload_dir, name)
                if os.path.isfile(full_path):
                    candidates.append(full_path)
        if not candidates:
            return None
        latest = max(candidates, key=os.path.getmtime)
        latest_name = os.path.basename(latest)
        return f"{image_base_url.rstrip('/')}/{quote(latest_name)}"
    except Exception as exc:
        logger.warning("Unable to resolve latest served image: %s", exc)
        return None


class ImageHTTPServer:
    """Small threaded HTTP server to receive and serve greenhouse images.

    Parameters
    ----------
    host : str, optional
        Interface address to bind.
    port : int, optional
        TCP port to listen on.
    upload_dir : str, optional
        Directory where uploaded/captured images are served from.
    frame_provider : callable, optional
        Zero-argument callback returning JPEG bytes for stream frames.
    stream_fps : float, optional
        Target MJPEG stream frame rate.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        upload_dir: str = "uploads",
        frame_provider: Optional[Callable[[], bytes]] = None,
        stream_fps: float = 2.0,
    ):
        self.host = host
        self.port = port
        self.upload_dir = upload_dir
        self.frame_provider = frame_provider
        self.stream_fps = stream_fps
        os.makedirs(self.upload_dir, exist_ok=True)

        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start HTTP server in a background daemon thread."""
        if self._server is not None:
            return

        self._stop_event.clear()
        handler = self._build_handler(self.upload_dir, self.frame_provider, self.stream_fps, self._stop_event)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop HTTP server and release socket resources."""
        if self._server is None:
            return

        self._stop_event.set()
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

        self._thread = None
        self._server = None

    @staticmethod
    def _build_handler(
        upload_dir: str,
        frame_provider: Optional[Callable[[], bytes]],
        stream_fps: float,
        stop_event: threading.Event,
    ):
        frame_interval = 1.0 / max(stream_fps, 0.1)

        class _ImageHandler(BaseHTTPRequestHandler):
            def _send_json(self, status_code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_redirect(self, location: str) -> None:
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _stream_frames(self) -> None:
                if frame_provider is None:
                    self._send_json(503, {"error": "Live stream not configured"})
                    return

                boundary = "frame"
                self.send_response(200)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Pragma", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
                self.end_headers()

                try:
                    while not stop_event.is_set():
                        loop_start = time.time()
                        frame = frame_provider()
                        if not frame:
                            time.sleep(frame_interval)
                            continue

                        self.wfile.write(f"--{boundary}\r\n".encode("ascii"))
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                        elapsed = time.time() - loop_start
                        if elapsed < frame_interval:
                            time.sleep(frame_interval - elapsed)
                except (BrokenPipeError, ConnectionResetError):
                    logger.debug("Live stream client disconnected")
                except TypeError:
                    # Camera may be tearing down while a stream client is connected.
                    if not stop_event.is_set():
                        logger.error("Live stream error: camera frame provider returned invalid data")
                except Exception as exc:
                    if not stop_event.is_set():
                        logger.error("Live stream error: %s", exc)

            def _send_file(self, file_path: str) -> None:
                content_type, _ = mimetypes.guess_type(file_path)
                content_type = content_type or "application/octet-stream"

                with open(file_path, "rb") as file_obj:
                    data = file_obj.read()

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _latest_image(self) -> Optional[str]:
                candidates = []
                for name in os.listdir(upload_dir):
                    if name.lower().endswith((".jpg", ".jpeg", ".png")):
                        full_path = os.path.join(upload_dir, name)
                        if os.path.isfile(full_path):
                            candidates.append(full_path)

                if not candidates:
                    return None

                return max(candidates, key=os.path.getmtime)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                request_path = parsed.path

                if request_path == "/":
                    self._send_redirect("/stream")
                    return

                if request_path == "/health":
                    self._send_json(200, {"status": "ok"})
                    return

                if request_path == "/latest":
                    latest = self._latest_image()
                    if latest is None:
                        self._send_json(404, {"error": "No images available"})
                        return
                    self._send_file(latest)
                    return

                if request_path == "/stream":
                    self._stream_frames()
                    return

                if request_path.startswith("/images/"):
                    image_name = os.path.basename(unquote(request_path.replace("/images/", "", 1)))
                    file_path = os.path.join(upload_dir, image_name)
                    if not os.path.isfile(file_path):
                        self._send_json(404, {"error": "Image not found"})
                        return
                    self._send_file(file_path)
                    return

                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                request_path = parsed.path

                if request_path != "/upload":
                    self._send_json(404, {"error": "Not found"})
                    return

                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0:
                    self._send_json(400, {"error": "Empty body"})
                    return

                body = self.rfile.read(content_length)
                raw_name = self.headers.get("X-Filename")
                if raw_name:
                    file_name = os.path.basename(raw_name)
                else:
                    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    file_name = f"image_{stamp}.jpg"

                save_path = os.path.join(upload_dir, file_name)
                if os.path.exists(save_path):
                    stamp = datetime.now().strftime("%H%M%S")
                    root, ext = os.path.splitext(file_name)
                    save_path = os.path.join(upload_dir, f"{root}_{stamp}{ext or '.jpg'}")

                with open(save_path, "wb") as file_obj:
                    file_obj.write(body)

                self._send_json(
                    201,
                    {
                        "message": "Image stored",
                        "filename": os.path.basename(save_path),
                        "size": len(body),
                    },
                )

            def log_message(self, format_text: str, *args) -> None:
                logger.debug("HTTP %s - %s", self.address_string(), format_text % args)

        return _ImageHandler


def post_image(image_path: str, url: str, timeout: float = 5.0, verify_tls: bool = True) -> Tuple[int, str]:
    """Post a local image file as raw bytes to an HTTP endpoint.

    Parameters
    ----------
    image_path : str
        Path to local image file.
    url : str
        HTTP/HTTPS endpoint URL that accepts ``POST`` uploads.
    timeout : float, optional
        Request timeout in seconds.
    verify_tls : bool, optional
        Whether TLS certificate verification should be enforced for HTTPS.

    Returns
    -------
    tuple of (int, str)
        HTTP status code and decoded response body.
    """
    with open(image_path, "rb") as file_obj:
        data = file_obj.read()

    req = request.Request(
        url=url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "image/jpeg",
            "X-Filename": os.path.basename(image_path),
        },
    )

    ssl_context = None
    if url.lower().startswith("https://") and not verify_tls:
        ssl_context = ssl._create_unverified_context()

    with request.urlopen(req, timeout=timeout, context=ssl_context) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.getcode(), body
