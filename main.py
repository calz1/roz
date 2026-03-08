#!/usr/bin/env python3
"""Roz Console MVP - Simple motion detection + LLM analysis.

Dead simple: camera → motion detection → LLM analysis → console output.
No threading, no complexity, just the core loop.
"""

import sys
import logging
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import init_config
from src.hardware.camera import Camera
from src.detection.motion_detector import MotionDetector
from src.llm.vision_analyzer import VisionAnalyzer
from src.speech.announcer import Announcer

# Setup logging
log_format = '[%(asctime)s] [%(levelname)s] %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("roz.console")

# Also log to file for analysis (with DEBUG level to capture all timing details)
log_file_handler = logging.FileHandler('timing.log')
log_file_handler.setLevel(logging.DEBUG)
log_file_handler.setFormatter(logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(log_file_handler)
# Enable DEBUG logging for vision analyzer to capture component timings
vision_logger = logging.getLogger("roz.llm.vision")
vision_logger.setLevel(logging.DEBUG)
vision_logger.addHandler(log_file_handler)
# Enable INFO logging for announcer to capture TTS timing
announcer_logger = logging.getLogger("roz.speech.announcer")
announcer_logger.addHandler(log_file_handler)


def main():
    """Main entry point."""
    try:
        # Load config
        logger.info("Loading configuration...")
        config = init_config()

        # Initialize camera
        logger.info("Initializing camera...")
        camera = Camera(device_id=0, width=640, height=480)
        if not camera.open():
            logger.error("Failed to open camera")
            return 1
        logger.info("✓ Camera initialized")

        # Initialize motion detector
        logger.info(f"Initializing motion detector (sensitivity: {config.motion.sensitivity})...")
        motion_detector = MotionDetector(
            sensitivity=config.motion.sensitivity,
            min_contour_area=config.motion.min_contour_area,
            blur_kernel_size=config.motion.blur_kernel_size,
            threshold_delta=config.motion.threshold_delta,
            enable_morphology=config.motion.enable_morphology,
            morphology_kernel_size=config.motion.morphology_kernel_size,
            min_motion_pixels=config.motion.min_motion_pixels,
        )
        logger.info("✓ Motion detector initialized")

        # Establish baseline frame
        logger.info("Establishing baseline frame...")
        for _ in range(10):
            ret, frame = camera.read_frame()
            if ret and frame is not None:
                motion_detector.set_baseline(frame)
                logger.info("✓ Baseline frame established")
                time.sleep(0.5)  # Stabilize
                break
        else:
            logger.error("Failed to establish baseline")
            camera.close()
            return 1

        # Initialize announcer
        logger.info("Initializing Piper TTS...")
        announcer = Announcer(
            voice_model=config.tts.voice_model,
            volume=config.tts.volume
        )
        announcer.init_tts()
        logger.info("✓ Announcer ready")

        # Initialize LLM analyzer
        logger.info("Initializing LLM analyzer...")
        analyzer = VisionAnalyzer(
            endpoint=config.llm.endpoint,
            api_key=config.llm.api_key,
            model=config.llm.model,
            timeout=config.llm.timeout,
            max_retries=config.llm.max_retries,
            enable_rate_limiting=False,  # Use simple cooldown instead
        )
        logger.info("✓ LLM analyzer initialized")

        logger.info("")
        logger.info("=" * 60)
        logger.info("Motion Monitor Ready (Ctrl+C to stop)")
        logger.info("=" * 60)
        logger.info("")

        # Main loop
        check_interval = config.motion.frame_check_interval_ms / 1000.0
        last_analysis_completed = 0
        analysis_cooldown = 2.0  # Min 2 seconds between analyses
        analysis_in_progress = False
        memory = []  # Keep last 3 LLM analyses for context (tuples of (timestamp, reason))
        analyzed_frames = []  # Keep last N analyzed frames for multi-image context

        # Adaptive frame count parameters
        frame_count = 2  # Start with 2 frames (before+after)
        min_frames = 1   # Minimum: just current frame
        max_frames = 4   # Maximum: 4 frames for rich context
        target_lag_threshold = 2.0  # If lagging by more than 2s, reduce frames
        fast_response_threshold = 0.8  # If responding under 0.8s, can increase frames
        recent_latencies = []  # Track last 5 latencies for smoothing

        # Motion persistence tracking to catch people leaving
        motion_was_active = False
        last_motion_time = 0
        post_motion_check_pending = False
        motion_settle_timeout = 3.5  # Wait 3.5s after motion stops for final check

        while True:
            # Read frame with timestamp
            frame_capture_time = time.time()
            ret, frame = camera.read_frame()
            if not ret or frame is None:
                time.sleep(0.1)
                continue

            # Detect motion
            motion_start = time.time()
            motion = motion_detector.detect(frame)
            motion_latency = time.time() - motion_start

            now = time.time()
            should_analyze = False
            is_post_motion_check = False

            # Normal motion detection
            if motion.detected:
                motion_was_active = True
                last_motion_time = now
                post_motion_check_pending = True
                
                # Analyze if enough time passed since last analysis
                if not analysis_in_progress and (now - last_analysis_completed) >= analysis_cooldown:
                    should_analyze = True
            
            # Post-motion cooldown check (to catch someone leaving)
            elif post_motion_check_pending and (now - last_motion_time) >= motion_settle_timeout:
                if not analysis_in_progress:
                    should_analyze = True
                    is_post_motion_check = True
                    post_motion_check_pending = False
                    logger.info(f"[COOLDOWN] No motion for {motion_settle_timeout}s, performing final scene check...")

            # Trigger analysis if needed
            if should_analyze:
                analysis_in_progress = True
                pipeline_start = time.time()

                if not is_post_motion_check:
                    logger.info(
                        f"[MOTION] Detected at (x={motion.x}, y={motion.y}, "
                        f"w={motion.w}, h={motion.h}, confidence={motion.confidence:.2f}) [motion_detect: {motion_latency*1000:.0f}ms]"
                    )

                # Build frames list adaptively
                prior_frame_count = frame_count - 1
                frames_to_analyze = analyzed_frames[-prior_frame_count:] + [frame] if prior_frame_count > 0 else [frame]
                
                # Send to LLM
                try:
                    llm_start = time.time()
                    
                    # Use actual bbox if motion, or None if post-motion check
                    bbox = {"x": motion.x, "y": motion.y, "w": motion.w, "h": motion.h} if not is_post_motion_check else None

                    # Build memory context from last 3 analyses
                    memory_context = ""
                    if memory:
                        observations = []
                        for idx, (timestamp, announcement, obs) in enumerate(reversed(memory), 1):
                            observations.append(f"{idx}: [ANNOUNCED: \"{announcement}\"] {obs}")
                        memory_context = f"PAST EVENTS (in reverse chronological order, 1=most recent):\n" + "\n".join(observations)

                    changed, reason = analyzer.analyze_with_change_detection(
                        frames=frames_to_analyze,
                        motion_bbox=bbox,
                        memory_context=memory_context,
                    )
                    llm_latency = time.time() - llm_start
                    last_analysis_completed = time.time()

                    # Track latencies for adaptive adjustment
                    recent_latencies.append(llm_latency)
                    if len(recent_latencies) > 5:
                        recent_latencies.pop(0)

                    # Calculate lag: time between frame capture and analysis completion
                    lag = time.time() - frame_capture_time

                    # Adjust frame count adaptively based on lag and latency
                    avg_latency = sum(recent_latencies) / len(recent_latencies) if recent_latencies else llm_latency

                    if lag > target_lag_threshold and frame_count > min_frames:
                        # Lagging behind: reduce frames
                        frame_count -= 1
                        logger.info(f"  → Reducing frame count to {frame_count} (lag: {lag:.1f}s)")
                    elif avg_latency < fast_response_threshold and lag < 1.5 and frame_count < max_frames:
                        # Fast response and not lagging: increase frames for better context
                        frame_count += 1
                        logger.info(f"  → Increasing frame count to {frame_count} (fast response: {avg_latency:.2f}s)")

                    # Add current frame to analyzed frames history (keep last max_frames-1)
                    analyzed_frames.append(frame)
                    if len(analyzed_frames) > max_frames - 1:
                        analyzed_frames.pop(0)

                    if changed:
                        announce_start = time.time()
                        logger.info(f"✓ CHANGE DETECTED: {reason}")
                        # Print observation for debugging
                        observation = getattr(analyzer, '_last_observation', reason)
                        logger.info(f"  → Observation: {observation}")

                        announcer.announce(reason, frame_capture_time=frame_capture_time)
                        announce_latency = time.time() - announce_start
                        # Add to memory only when change detected (keep last 3)
                        # Store both announcement and detailed observation for context
                        memory.append((now, reason, observation))  # (timestamp, announcement, observation)
                        if len(memory) > 3:
                            memory.pop(0)
                        logger.debug(f"Memory context updated: [{reason}] {observation[:80]}...")
                    else:
                        announce_latency = 0
                        logger.info(f"  ⊘ No meaningful change: {reason}")
                        # Print observation for debugging
                        observation = getattr(analyzer, '_last_observation', reason)
                        logger.info(f"  → Observation: {observation}")

                    # If scene is empty, update baseline and clear frame history
                    # This prevents hallucinating people from old frames
                    # We do this regardless of 'changed' to keep state clean
                    obs_lower = observation.lower()
                    reason_lower = reason.lower()
                    is_empty = any(word in obs_lower or word in reason_lower for word in ['empty', 'no one', 'no people', 'nobody', 'left the room', 'exited'])

                    if is_empty:
                        logger.info("  → Scene is empty: updating baseline and clearing frame history")
                        motion_detector.set_baseline(frame)
                        analyzed_frames.clear()
                    total_pipeline_latency = time.time() - pipeline_start
                    total_end_to_end = time.time() - frame_capture_time
                    # Note: TTS runs async in background, so announce_latency is just queue time
                    # Real TTS latency is logged separately by announcer with "Frame→Audio" metric
                    if changed:
                        logger.info(
                            f"  [LLM: {llm_latency:.2f}s | Queued TTS: {announce_latency:.2f}s | "
                            f"Capture→LLM done: {lag:.2f}s | Frames: {len(frames_to_analyze)} | Memory: {len(memory)}]"
                        )
                        logger.info(f"  (See TTS log for full Frame→Audio latency)")
                    else:
                        logger.info(
                            f"  [LLM: {llm_latency:.2f}s | Capture→Done: {lag:.2f}s | Frames: {len(frames_to_analyze)} | Memory: {len(memory)}]"
                        )

                except Exception as e:
                    logger.error(f"LLM Error: {e}")
                finally:
                    analysis_in_progress = False

            # Sleep
            time.sleep(check_interval)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1
    finally:
        if 'camera' in locals():
            camera.close()
        if 'announcer' in locals():
            announcer.stop()
        logger.info("Stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
