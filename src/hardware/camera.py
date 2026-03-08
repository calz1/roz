"""USB camera interface for frame capture."""

import cv2
import numpy as np
from typing import Optional, Tuple
import logging

logger = logging.getLogger("roz.hardware.camera")


class Camera:
    """USB camera interface using OpenCV."""

    def __init__(self, device_id: int = 0, width: int = 640, height: int = 480):
        """Initialize camera.

        Args:
            device_id: Video device ID (default 0 for /dev/video0)
            width: Target frame width
            height: Target frame height
        """
        self.device_id = device_id
        self.width = width
        self.height = height
        self.cap: Optional[cv2.VideoCapture] = None

    def open(self) -> bool:
        """Open camera device.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.cap = cv2.VideoCapture(self.device_id)
            if not self.cap.isOpened():
                logger.error(f"Failed to open camera device {self.device_id}")
                return False

            # Set resolution
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

            logger.info(f"Camera opened: device={self.device_id}, resolution={self.width}x{self.height}")
            return True

        except Exception as e:
            logger.error(f"Error opening camera: {e}")
            return False

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read a frame from camera.

        Returns:
            Tuple of (success, frame) where frame is numpy array or None
        """
        if self.cap is None:
            logger.warning("Camera not opened")
            return False, None

        try:
            ret, frame = self.cap.read()
            if not ret:
                logger.warning("Failed to read frame from camera")
            return ret, frame

        except Exception as e:
            logger.error(f"Error reading frame: {e}")
            return False, None

    def close(self) -> None:
        """Close camera device."""
        if self.cap is not None:
            self.cap.release()
            logger.info("Camera closed")

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
