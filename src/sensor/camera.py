import os
import io
import time
import logging
import threading
from datetime import datetime
from picamera2 import Picamera2

logger = logging.getLogger(__name__)


class Camera:
    
    def __init__(self, image_dir="data/images", stream_size=(640, 480)):
        self.image_dir = image_dir
        os.makedirs(self.image_dir, exist_ok=True)

        self.picam2 = Picamera2()
        self._stream_config = self.picam2.create_preview_configuration(main={"size": stream_size})
        self._still_config = self.picam2.create_still_configuration()
        self.picam2.configure(self._stream_config)
        self._lock = threading.Lock()
        self._started = False
        self._warmup_done = False
        self._startup_warmup_seconds = 1.5
        self._still_settle_seconds = 0.6

    def _ensure_started(self):
        """Start camera once and keep it running for still captures and live feed."""
        if not self._started:
            self.picam2.start()
            self._started = True
        if not self._warmup_done:
            # Give AE/AWB time to settle so first captures are not black.
            time.sleep(self._startup_warmup_seconds)
            self._warmup_done = True

    def capture(self):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        filename = f"growth_{timestamp}.jpg"
        filepath = os.path.join(self.image_dir, filename)

        with self._lock:
            self._ensure_started()
            try:
                # Reliable still capture path for Picamera2 versions where switch_mode can hang.
                self.picam2.stop()
                self.picam2.configure(self._still_config)
                self.picam2.start()
                time.sleep(self._still_settle_seconds)
                self.picam2.capture_file(filepath)

                # Return to low-latency stream mode.
                self.picam2.stop()
                self.picam2.configure(self._stream_config)
                self.picam2.start()
                self._warmup_done = True
            except Exception:
                # Fallback to current mode capture if mode change fails.
                time.sleep(self._still_settle_seconds)
                self.picam2.capture_file(filepath)

        return filepath

    def capture_frame_jpeg(self) -> bytes:
        """Capture a single JPEG frame as bytes for HTTP streaming."""
        with self._lock:
            self._ensure_started()
            frame_buffer = io.BytesIO()
            self.picam2.capture_file(frame_buffer, format="jpeg")
            return frame_buffer.getvalue()

    def shutdown(self) -> None:
        """Release camera resources on application shutdown."""
        with self._lock:
            if self._started:
                self.picam2.stop()
                self._started = False
            self._warmup_done = False
            self.picam2.close()
        logger.info("Camera resources released")


if __name__ == "__main__":
    test_dir = os.path.join(os.path.dirname(__file__), "test_photos")
    cam = Camera(image_dir=test_dir)
    path = cam.capture()
    print(f"Test capture saved to: {path}")