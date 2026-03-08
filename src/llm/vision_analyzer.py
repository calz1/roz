"""LLM integration for vision analysis."""

import logging
import base64
import time
import json
from typing import List, Optional, Tuple
import numpy as np
import requests

from .prompt_config import ChangeDetectionPrompt
from .rate_limiter import AdaptiveRateLimiter

logger = logging.getLogger("roz.llm.vision")


class VisionAnalyzer:
    """Analyzes images using remote LLM vision model.

    Sends frames to a configured LLM endpoint for scene analysis.
    Handles encoding, retries, and graceful degradation on failures.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str = "qwen-vision",
        timeout: int = 30,
        max_retries: int = 3,
        prompt_config: Optional[ChangeDetectionPrompt] = None,
        enable_rate_limiting: bool = True,
    ):
        """Initialize vision analyzer.

        Args:
            endpoint: LLM API endpoint URL
            api_key: API key for authentication
            model: LLM model name (default: qwen-vision)
            timeout: Request timeout in seconds (default: 30)
            max_retries: Maximum number of retry attempts (default: 3)
            prompt_config: ChangeDetectionPrompt for intelligent filtering (optional)
            enable_rate_limiting: Enable adaptive rate limiting (default: True)
        """
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.prompt_config = prompt_config or ChangeDetectionPrompt()
        self.rate_limiter = AdaptiveRateLimiter() if enable_rate_limiting else None

    def analyze(
        self,
        frames: List[np.ndarray],
        motion_bbox: Optional[dict] = None,
        memory_context: str = "",
    ) -> str:
        """Analyze frames with LLM vision model.

        Args:
            frames: List of frames (numpy arrays, BGR format)
            motion_bbox: Motion detection bounding box (x, y, w, h)
            memory_context: Recent memory context from StateManager

        Returns:
            Scene description from LLM, or error message on failure
        """
        if not frames:
            logger.warning("No frames provided for analysis")
            return "No frames available for analysis"

        try:
            # Encode frames to base64
            encoded_frames = self._encode_frames(frames)

            # Build prompt with context
            prompt = self._build_prompt(motion_bbox, memory_context)

            # Send to LLM with retries
            response = self._call_llm(encoded_frames, prompt)

            if response:
                logger.info(f"LLM analysis successful: {response[:100]}...")
                return response

            logger.warning("LLM returned empty response")
            return "Analysis complete but no description generated"

        except Exception as e:
            logger.error(f"Error during LLM analysis: {e}")
            return f"Analysis failed: {str(e)}"

    def analyze_initialization(
        self,
        frames: List[np.ndarray],
    ) -> str:
        """Analyze frames to establish baseline scene (initialization).

        Used once at startup to establish what's currently in the scene.
        Always returns the description for memory/baseline.

        Args:
            frames: List of frames (numpy arrays, BGR format)

        Returns:
            Scene description from LLM
        """
        if not frames:
            logger.warning("No frames provided for initialization analysis")
            return "Empty scene (no frames captured)"

        try:
            # Encode frames to base64
            encoded_frames = self._encode_frames(frames)

            # Get initialization prompt
            prompt = self.prompt_config.build_initialization_prompt()

            # Send to LLM with retries - initialization always waits for response
            response = self._call_llm(encoded_frames, prompt, allow_rate_limit_skip=False)

            if response:
                # Extract decision from JSON response
                change_detected, reason = self._extract_decision(response)
                logger.info(f"System initialization: {reason}")
                return reason

            logger.warning("LLM returned empty response for initialization")
            return "Initialization failed - no response from LLM"

        except Exception as e:
            logger.error(f"Error during initialization analysis: {e}")
            return f"Initialization error: {str(e)}"

    def analyze_with_change_detection(
        self,
        frames: List[np.ndarray],
        motion_bbox: Optional[dict] = None,
        memory_context: str = "",
    ) -> Tuple[bool, str]:
        """Analyze frames with explicit change detection decision.

        Requests the LLM to explicitly decide if a meaningful change has occurred,
        returning a structured JSON response with the decision and reason.

        Args:
            frames: List of frames (numpy arrays, BGR format)
            motion_bbox: Motion detection bounding box (x, y, w, h)
            memory_context: Recent memory context from StateManager

        Returns:
            Tuple of (change_detected: bool, reason: str)
            - change_detected: True if meaningful change detected, False otherwise
            - reason: LLM's explanation for the decision
        """
        if not frames:
            logger.warning("No frames provided for change detection analysis")
            return False, "No frames available for analysis"

        analysis_start = time.time()
        try:
            # Encode frames to base64
            encode_start = time.time()
            encoded_frames = self._encode_frames(frames)
            encode_latency = time.time() - encode_start
            logger.debug(f"Frame encoding: {encode_latency*1000:.0f}ms")

            # Build change detection prompt with context and frame count
            prompt = self.prompt_config.build_prompt(
                memory_context=memory_context,
                motion_bbox=motion_bbox,
                frame_count=len(frames),
            )

            # Send to LLM with retries
            response = self._call_llm(encoded_frames, prompt)

            if response:
                # Extract decision from JSON response
                change_detected, reason = self._extract_decision(response)
                analysis_latency = time.time() - analysis_start
                logger.debug(f"Total LLM analysis latency: {analysis_latency:.2f}s (encode: {encode_latency*1000:.0f}ms)")
                logger.info(
                    f"Change detection: {change_detected} - {reason}"
                )
                return change_detected, reason

            logger.warning("LLM returned empty response for change detection")
            return False, "LLM returned empty response"

        except Exception as e:
            logger.error(f"Error during change detection analysis: {e}")
            # Default to False (skip) on error to prevent noise buildup
            return False, f"Analysis error: {str(e)}"

    def _extract_decision(self, response: str) -> Tuple[bool, str]:
        """Extract meaningful_change decision from LLM JSON response.
        Parses the LLM's JSON response to extract whether a meaningful change
        was detected and returns the announcement for audio broadcast.
        Also extracts the detailed observation for memory context.

        Args:
            response: LLM response string (expected to be JSON)

        Returns:
            Tuple of (change_detected: bool, announcement: str)
            The announcement is the brief text for audio broadcast.
            Defaults to (False, "parsing error") if JSON parsing fails
        """
        try:
            # Try to find and parse JSON in the response
            # The response might have extra text, so we look for JSON object
            json_str = response.strip()

            # If response has markdown code blocks, extract the JSON
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            # Parse JSON
            data = json.loads(json_str)

            # Extract fields
            change_detected = data.get("meaningful_change", False)

            # Try new format first (announcement + observation), fall back to old format (reason)
            if "announcement" in data:
                # New format: use announcement for audio, observation for memory
                announcement = data.get("announcement", "Event detected")
                observation = data.get("observation", announcement)
                # Store observation in memory if change detected
                self._last_observation = observation
                result = str(announcement)
            else:
                # Old format: use reason for everything
                result = data.get("reason", "No reason provided")
                self._last_observation = result

            logger.debug(f"LLM decision: change_detected={change_detected}, announcement={result}")
            return bool(change_detected), result

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}")
            logger.debug(f"Raw response was: {response[:200]}")
            # Default to False (skip) on parsing error
            return False, "Could not parse LLM response"
        except Exception as e:
            logger.error(f"Error extracting decision from response: {e}")
            return False, "Error extracting decision"

    def _encode_frames(self, frames: List[np.ndarray]) -> List[str]:
        """Encode frames to base64 for transmission.

        Args:
            frames: List of numpy arrays (BGR format)

        Returns:
            List of base64-encoded frame strings
        """
        import cv2

        encoded = []
        for frame in frames:
            # Encode frame to JPEG (reduces size vs PNG)
            success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if success:
                b64_frame = base64.b64encode(buffer).decode("utf-8")
                encoded.append(b64_frame)
            else:
                logger.warning("Failed to encode frame to JPEG")
        return encoded

    def _build_prompt(self, motion_bbox: Optional[dict], memory_context: str) -> str:
        """Build prompt for LLM analysis.

        Args:
            motion_bbox: Motion bounding box or None
            memory_context: Recent observations context

        Returns:
            Formatted prompt string
        """
        prompt = "Analyze the provided image(s) and describe the scene. "

        if motion_bbox:
            prompt += (
                f"Motion was detected in region: x={motion_bbox.get('x', 0)}, "
                f"y={motion_bbox.get('y', 0)}, "
                f"width={motion_bbox.get('w', 0)}, height={motion_bbox.get('h', 0)}. "
            )

        prompt += "Provide a brief, clear description of what changed or what you observe."

        if memory_context:
            prompt += f"\n\nContext from recent observations:\n{memory_context}\n\n"
            prompt += "If this looks like the same scene as recent observations, mention that."

        return prompt

    def _call_llm(self, encoded_frames: List[str], prompt: str, allow_rate_limit_skip: bool = True) -> Optional[str]:
        """Call LLM endpoint with retries and adaptive rate limiting.

        Args:
            encoded_frames: Base64-encoded frames
            prompt: Analysis prompt
            allow_rate_limit_skip: If True, skip if rate limited. If False, wait and retry.

        Returns:
            LLM response or None on failure
        """
        # Apply rate limiting if enabled
        if self.rate_limiter:
            if not self.rate_limiter.can_submit():
                if allow_rate_limit_skip:
                    # Motion detection: skip if not ready
                    wait_time = self.rate_limiter.get_wait_time()
                    logger.debug(f"Rate limited: skipping request (wait {wait_time:.1f}s)")
                    return None
                else:
                    # Initialization: wait for rate limiter to be ready
                    wait_time = self.rate_limiter.get_wait_time()
                    logger.info(f"Waiting for rate limiter: {wait_time:.1f}s")
                    time.sleep(wait_time)
            self.rate_limiter.record_submission()

        request_start = time.time()

        for attempt in range(self.max_retries):
            try:
                # Build message content with images and text
                content = []

                # Add images as vision content with explicit labels
                for i, frame_b64 in enumerate(encoded_frames):
                    # Use intuitive labels based on position in sequence
                    if i == len(encoded_frames) - 1:
                        label = f"CURRENT FRAME (NOW) - {i+1}:"
                    elif i == len(encoded_frames) - 2:
                        label = f"PREVIOUS FRAME (BEFORE) - {i+1}:"
                    else:
                        label = f"HISTORICAL FRAME - {i+1}:"
                        
                    content.append({
                        "type": "text",
                        "text": label
                    })
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{frame_b64}"
                        }
                    })

                # Add text prompt
                content.append({
                    "type": "text",
                    "text": prompt
                })

                # Prepare OpenAI-compatible request payload
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": content
                        }
                    ]
                }

                headers = {
                    "Content-Type": "application/json",
                }

                # Only add auth header if API key is provided (not for local services)
                if self.api_key and self.api_key != "not-needed-for-local":
                    headers["Authorization"] = f"Bearer {self.api_key}"

                # Send request
                llm_request_start = time.time()
                response = requests.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                llm_request_latency = time.time() - llm_request_start
                logger.debug(f"LLM request latency: {llm_request_latency:.2f}s")

                if response.status_code == 200:
                    data = response.json()
                    # Extract content from OpenAI-compatible response
                    if "choices" in data and data["choices"]:
                        choice = data["choices"][0]
                        if "message" in choice:
                            result = choice["message"].get("content", "")
                            # Record latency for adaptive rate limiting
                            if self.rate_limiter:
                                latency = time.time() - request_start
                                self.rate_limiter.record_completion(latency)
                            return result
                    return None

                elif response.status_code == 401:
                    logger.error("LLM authentication failed - check API key")
                    if self.rate_limiter:
                        self.rate_limiter.record_completion(time.time() - request_start)
                    return None

                else:
                    logger.warning(
                        f"LLM request failed with status {response.status_code}: "
                        f"{response.text[:200]}"
                    )

            except requests.Timeout:
                logger.warning(f"LLM request timeout (attempt {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    backoff_seconds = 2 ** attempt
                    time.sleep(min(backoff_seconds, 1))  # Cap at 1 second for interruptibility

            except requests.ConnectionError as e:
                logger.warning(
                    f"Failed to connect to LLM endpoint (attempt {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    backoff_seconds = 2 ** attempt
                    time.sleep(min(backoff_seconds, 1))  # Cap at 1 second for interruptibility

            except Exception as e:
                logger.error(f"Unexpected error calling LLM: {e}")
                return None

        # Record completion even on failure
        if self.rate_limiter:
            self.rate_limiter.record_completion(time.time() - request_start)

        logger.error(f"LLM analysis failed after {self.max_retries} retries")
        return None
