"""Configurable prompts for LLM vision analysis."""

from typing import Optional


class ChangeDetectionPrompt:
    """Generates prompts for detecting meaningful changes in surveillance footage.

    This class handles the prompt template for asking the LLM to explicitly decide
    whether a meaningful change has occurred, compared to recent observations.

    The LLM is asked to respond with a JSON structure containing:
    - meaningful_change: bool (whether the change is meaningful)
    - reason: str (explanation of the decision)
    """

    # Initialization prompt - runs once at startup to establish baseline
    INITIALIZATION_PROMPT = """You are setting up a surveillance system. Analyze the frame(s) provided and describe the baseline scene briefly.

IMPORTANT: You may receive 1-5 frames showing the scene. Analyze all provided frames to understand the baseline state.

Your response must be valid JSON:
{{"meaningful_change": true, "reason": "one sentence describing the scene"}}

Keep the reason to 1-2 sentences max. Examples: "Empty room with chair" or "Person standing by window"."""

    # Default prompt that can be overridden
    DEFAULT_PROMPT = """Compare the [LAST ANNOUNCEMENT] to the [CURRENT REALITY] and decide if a NEW event occurred.

[LAST ANNOUNCEMENT]: {memory_context}
[CURRENT REALITY]: {motion_info}
[FRAMES]: {frame_count} provided. The last frame is the CURRENT moment.

A NEW EVENT (meaningful_change: true) is:
1. APPEARANCE: Room was empty, but now a person/object is present.
2. DEPARTURE: Person was present, but now the room is empty.
3. NEW ACTIVITY: The same person is doing something SIGNIFICANTLY different (e.g., was standing, now dancing).
4. NEW OBJECT: A different person or object appeared.

NOT A NEW EVENT (meaningful_change: false):
1. CONTINUATION: The same person is doing the same activity (minor movement/pose changes).
2. STILL EMPTY: The room is still empty and the last announcement said it was empty.

Respond ONLY in JSON:
{{
  "meaningful_change": true/false,
  "observation": "Detailed 2-3 sentence visual description.",
  "announcement": "Under 10 words for audio (e.g., 'Person is dancing', 'Room is now empty')."
}}"""

    def __init__(self, custom_prompt: Optional[str] = None):
        """Initialize the prompt generator.

        Args:
            custom_prompt: Optional custom prompt to use instead of default
        """
        self.prompt = custom_prompt or self.DEFAULT_PROMPT

    def build_initialization_prompt(self) -> str:
        """Build the initialization prompt for establishing baseline.

        Returns:
            Initialization prompt string
        """
        return self.INITIALIZATION_PROMPT

    def build_prompt(
        self,
        memory_context: str = "",
        motion_bbox: Optional[dict] = None,
        frame_count: int = 1,
    ) -> str:
        """Build the change detection prompt with context.

        Args:
            memory_context: Recent observations context from StateManager
            motion_bbox: Motion detection bounding box (x, y, w, h) or None
            frame_count: Number of frames being sent to the LLM

        Returns:
            Formatted prompt string with context injected
        """
        # Extract motion region coordinates or indicate no active motion
        if motion_bbox:
            x, y, w, h = motion_bbox.get("x", 0), motion_bbox.get("y", 0), motion_bbox.get("w", 0), motion_bbox.get("h", 0)
            motion_info = f"Motion at x={x}, y={y}, {w}x{h}."
        else:
            motion_info = "No active motion (checking for departures)."

        # Format the prompt with context
        formatted_prompt = self.prompt.format(
            memory_context=memory_context or "No prior announcements. Room is assumed empty.",
            frame_count=frame_count,
            motion_info=motion_info,
        )

        return formatted_prompt
