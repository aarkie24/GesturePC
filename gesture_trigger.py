
import time


class GestureTrigger:
    def __init__(self, cooldown=0.8):
        self.cooldown = cooldown
        self.last_trigger_time = {}
        self.previous_gesture = {}

    def update(self, hand_label, gesture):
        """
        Return a gesture event once when a new gesture is recognized.
        Return None if it should not trigger.
        """
        now = time.monotonic()

        previous = self.previous_gesture.get(hand_label, "Unknown")
        self.previous_gesture[hand_label] = gesture

        # Only trigger when entering a new recognized gesture.
        if gesture in ("Unknown", "Open Palm (tracking)",
                       "Waiting for gesture..."):
            return None

        if gesture == previous:
            return None

        key = (hand_label, gesture)
        last_time = self.last_trigger_time.get(key, 0.0)

        if now - last_time < self.cooldown:
            return None

        self.last_trigger_time[key] = now

        return {
            "hand": hand_label,
            "gesture": gesture,
            "timestamp": now
        }
