import os
from datetime import datetime
from picamera2 import Picamera2

class Camera:
    
    def __init__(self, image_dir="data/images"):
        self.image_dir = image_dir
        os.makedirs(self.image_dir, exist_ok=True)

        self.picam2 = Picamera2()
        config = self.picam2.create_still_configuration()
        self.picam2.configure(config)

    def capture(self):
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        filename = f"growth_{timestamp}.jpg"
        filepath = os.path.join(self.image_dir, filename)

        self.picam2.start()
        self.picam2.capture_file(filepath)
        self.picam2.stop()

        return filepath


if __name__ == "__main__":
    test_dir = os.path.join(os.path.dirname(__file__), "test_photos")
    cam = Camera(image_dir=test_dir)
    path = cam.capture()
    print(f"Test capture saved to: {path}")