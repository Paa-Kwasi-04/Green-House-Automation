"""HTTP image server and uploader utilities for greenhouse photos."""

import json
import logging
import mimetypes
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional, Tuple
from urllib import request
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


class ImageHTTPServer:
    """Small HTTP server to receive and serve camera images."""

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
        """Stop HTTP server and release socket."""
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


def post_image(image_path: str, url: str, timeout: float = 5.0) -> Tuple[int, str]:
    """Post a local image file as raw bytes to an HTTP endpoint."""
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

    with request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.getcode(), body
