"""Motion detection algorithm using frame differencing."""

import cv2
import numpy as np
from typing import Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger("roz.detection.motion")


@dataclass
class MotionResult:
    """Result of motion detection."""
    detected: bool
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    contour_count: int = 0
    confidence: float = 0.0  # Confidence score from 0-1


class MotionDetector:
    """Detects motion in video frames using frame differencing."""

    def __init__(
        self,
        sensitivity: str = "medium",
        min_contour_area: int = 500,
        blur_kernel_size: int = 5,
        threshold_delta: int = 25,
        enable_morphology: bool = True,
        morphology_kernel_size: int = 3,
        min_motion_pixels: int = 50,
    ):
        """Initialize motion detector.

        Args:
            sensitivity: 'high', 'medium', or 'low'
            min_contour_area: Minimum contour area to consider as motion
            blur_kernel_size: Gaussian blur kernel size
            threshold_delta: Threshold for binary threshold
            enable_morphology: Enable morphological closing to reduce noise
            morphology_kernel_size: Kernel size for morphological operations
            min_motion_pixels: Minimum total motion pixels to consider detection valid
        """
        self.sensitivity = sensitivity
        self.min_contour_area = min_contour_area
        self.blur_kernel_size = blur_kernel_size
        self.threshold_delta = threshold_delta
        self.enable_morphology = enable_morphology
        self.morphology_kernel_size = morphology_kernel_size
        self.min_motion_pixels = min_motion_pixels

        # Adjust thresholds based on sensitivity
        self._apply_sensitivity()

        self.baseline: Optional[np.ndarray] = None
        self.previous_motion_frame: Optional[np.ndarray] = None
        logger.info(f"MotionDetector initialized: sensitivity={sensitivity}, enable_morphology={enable_morphology}")

    def _apply_sensitivity(self) -> None:
        """Adjust detection thresholds based on sensitivity setting."""
        if self.sensitivity == "high":
            self.min_contour_area = max(100, self.min_contour_area // 5)
            self.threshold_delta = max(10, self.threshold_delta // 2)
        elif self.sensitivity == "low":
            self.min_contour_area = self.min_contour_area * 3
            self.threshold_delta = self.threshold_delta * 2

    def set_baseline(self, frame: np.ndarray) -> None:
        """Set baseline frame for comparison.

        Args:
            frame: Reference frame (BGR format)
        """
        self.baseline = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        logger.debug("Baseline frame set")

    def detect(self, frame: np.ndarray) -> MotionResult:
        """Detect motion in frame.

        Args:
            frame: Frame to analyze (BGR format)

        Returns:
            MotionResult with detection status and bounding box
        """
        if self.baseline is None:
            logger.warning("No baseline set, cannot detect motion")
            return MotionResult(detected=False)

        try:
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Apply Gaussian blur
            blurred = cv2.GaussianBlur(
                gray, (self.blur_kernel_size, self.blur_kernel_size), 0
            )

            # Compute frame difference
            frame_delta = cv2.absdiff(self.baseline, blurred)

            # Binary threshold
            thresh = cv2.threshold(
                frame_delta, self.threshold_delta, 255, cv2.THRESH_BINARY
            )[1]

            # Morphological operations to reduce noise and grain artifacts
            if self.enable_morphology:
                kernel = cv2.getStructuringElement(
                    cv2.MORPH_ELLIPSE,
                    (self.morphology_kernel_size, self.morphology_kernel_size)
                )
                # Opening: removes small noise first
                thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
                # Closing: fills small holes in foreground
                thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)

            # Dilate to connect broken regions
            dilated = cv2.dilate(thresh, None, iterations=2)

            # Find contours
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # Filter by area and find bounding box
            motion_detected = False
            total_motion_pixels = 0
            min_x, min_y = float("inf"), float("inf")
            max_x, max_y = 0, 0

            for contour in contours:
                area = cv2.contourArea(contour)
                if area > self.min_contour_area:
                    motion_detected = True
                    total_motion_pixels += area
                    x, y, w, h = cv2.boundingRect(contour)
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x + w)
                    max_y = max(max_y, y + h)

            # Additional filter: ensure total motion pixels meet minimum threshold
            if motion_detected and total_motion_pixels < self.min_motion_pixels:
                logger.debug(
                    f"Motion filtered: total_pixels={total_motion_pixels} < min={self.min_motion_pixels}"
                )
                return MotionResult(detected=False, contour_count=len(contours))

            if motion_detected:
                # Calculate confidence based on motion magnitude relative to frame size
                frame_area = frame.shape[0] * frame.shape[1]
                confidence = min(1.0, total_motion_pixels / (frame_area * 0.1))

                result = MotionResult(
                    detected=True,
                    x=int(min_x),
                    y=int(min_y),
                    w=int(max_x - min_x),
                    h=int(max_y - min_y),
                    contour_count=len(contours),
                    confidence=confidence,
                )
                return result

            return MotionResult(detected=False, contour_count=len(contours))

        except Exception as e:
            logger.error(f"Error during motion detection: {e}")
            return MotionResult(detected=False)
