"""Pry — Behavioral Biometrics v2.
Real human behavior simulation: hesitation, scroll-back, mouse drift, reading time.
Modern anti-bot systems detect 'too perfect' behavior. This module makes
behavior more realistic by adding human imperfections."""

import logging
import math
import random
from typing import Any

logger = logging.getLogger(__name__)


class HumanBehaviorSimulator:
    """Generate realistic human behavior patterns."""

    def __init__(self) -> None:
        self._page_focus_time = 0

    def mouse_path(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        steps: int | None = None,
    ) -> list[dict[str, float]]:
        """Generate a human-like mouse path between two points.

        Uses bezier curve with random control points to create natural
        curved paths, with speed variation (fast in middle, slow at endpoints).
        """
        if steps is None:
            distance = math.sqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2)
            steps = max(10, min(50, int(distance / 20)))

        # Random control points for bezier curve
        ctrl1 = (
            start[0] + (end[0] - start[0]) * random.uniform(0.2, 0.4) + random.uniform(-50, 50),
            start[1] + (end[1] - start[1]) * random.uniform(0.2, 0.4) + random.uniform(-50, 50),
        )
        ctrl2 = (
            start[0] + (end[0] - start[0]) * random.uniform(0.6, 0.8) + random.uniform(-30, 30),
            start[1] + (end[1] - start[1]) * random.uniform(0.6, 0.8) + random.uniform(-30, 30),
        )

        path: list[dict[str, float]] = []
        for i in range(steps + 1):
            t = i / steps
            # Cubic bezier
            x = (
                (1 - t) ** 3 * start[0]
                + 3 * (1 - t) ** 2 * t * ctrl1[0]
                + 3 * (1 - t) * t ** 2 * ctrl2[0]
                + t ** 3 * end[0]
            )
            y = (
                (1 - t) ** 3 * start[1]
                + 3 * (1 - t) ** 2 * t * ctrl1[1]
                + 3 * (1 - t) * t ** 2 * ctrl2[1]
                + t ** 3 * end[1]
            )
            # Speed: slow at start/end, fast in middle
            speed_mod = math.sin(t * math.pi) * 0.5 + 0.5  # 0 at endpoints, 1 in middle
            # Add tiny jitter
            x += random.uniform(-2, 2)
            y += random.uniform(-2, 2)
            path.append(
                {
                    "x": round(x, 1),
                    "y": round(y, 1),
                    "t": round(t, 3),
                    "speed": round(speed_mod, 3),
                }
            )
        return path

    def reading_pause(self, content_length: int) -> float:
        """How long a human would pause to read content of this length.
        Based on average reading speed of 250 words/minute."""
        words = content_length / 5  # Rough estimate
        seconds = (words / 250) * 60
        # Add variance: 60-130% of average (some skim, some read carefully)
        variance = random.uniform(0.6, 1.3)
        # Add micro-pauses every ~20 words
        micro_pauses = max(0, words // 20) * random.uniform(0.5, 2.0)
        return round(seconds * variance + micro_pauses, 2)

    def scroll_pattern(
        self, page_height: int, viewport_height: int = 800
    ) -> list[dict[str, Any]]:
        """Generate realistic scroll pattern for a page.

        Humans don't scroll linearly — they scroll, pause, scroll back, etc.
        """
        patterns: list[dict[str, Any]] = []
        current_y = 0
        # Initial scroll: fast down to see the page
        current_y = min(page_height, viewport_height * 0.5)
        patterns.append(
            {
                "y": current_y,
                "speed": "fast",
                "pause_after": random.uniform(0.5, 1.5),
            }
        )

        while current_y < page_height - viewport_height:
            # Decide: continue down, or scroll back up
            if random.random() < 0.15 and current_y > viewport_height:
                # Scroll back up a bit
                current_y = max(0, current_y - random.randint(100, 400))
                patterns.append(
                    {
                        "y": current_y,
                        "speed": "slow",
                        "pause_after": random.uniform(1.0, 3.0),
                        "action": "scroll_back",
                    }
                )
            else:
                # Scroll down a bit
                scroll_amount = random.randint(200, 600)
                current_y = min(page_height, current_y + scroll_amount)
                # Pause longer on certain content (images, headings)
                pause = (
                    random.uniform(1.0, 4.0)
                    if random.random() < 0.2
                    else random.uniform(0.2, 1.0)
                )
                patterns.append(
                    {
                        "y": current_y,
                        "speed": "normal",
                        "pause_after": pause,
                    }
                )
        # Final scroll to bottom
        patterns.append(
            {"y": page_height, "speed": "fast", "pause_after": 0.5}
        )
        return patterns

    def typing_pattern(self, text: str) -> list[dict[str, Any]]:
        """Generate realistic typing timings.

        Humans have variable typing speed: faster on common words,
        slower on rare words, occasional pauses to think.
        """
        timings: list[dict[str, Any]] = []
        common_words = {
            "the", "a", "an", "is", "are", "was", "and", "or", "but",
            "in", "on", "at", "to", "for", "of", "with",
        }
        words = text.split(" ")
        for i, word in enumerate(words):
            if word.lower().strip(".,!?") in common_words:
                delay = random.uniform(0.05, 0.15)  # Fast for common words
            else:
                delay = random.uniform(0.1, 0.3)  # Slower for less common
            # Occasional "thinking" pause
            if random.random() < 0.05:
                delay += random.uniform(0.5, 2.0)
            # Space between words: faster
            if i < len(words) - 1:
                delay += random.uniform(0.05, 0.12)
            timings.append({"char": word, "delay_ms": round(delay * 1000)})
        return timings

    def click_decision_delay(self) -> float:
        """How long a human takes to decide to click something they see.
        Range: 200ms (impulsive) to 2000ms (cautious)."""
        # Most clicks are fast (200-500ms)
        r = random.random()
        if r < 0.4:
            return random.uniform(0.2, 0.5)  # Impulsive
        if r < 0.9:
            return random.uniform(0.5, 1.2)  # Normal
        return random.uniform(1.2, 2.5)  # Cautious (rare)

    def form_filling_sequence(self, field_count: int) -> list[dict[str, Any]]:
        """Generate realistic form filling sequence with field-switch delays."""
        sequence: list[dict[str, Any]] = []
        for i in range(field_count):
            # Type field
            sequence.append(
                {
                    "action": "type",
                    "field_index": i,
                    "duration_ms": random.randint(500, 3000),
                }
            )
            # Tab to next field (or submit on last)
            if i < field_count - 1:
                sequence.append({"action": "tab", "pause_ms": random.randint(200, 800)})
        sequence.append({"action": "review", "pause_ms": random.randint(500, 2000)})
        sequence.append({"action": "submit", "duration_ms": random.randint(300, 1000)})
        return sequence


behavior = HumanBehaviorSimulator()
