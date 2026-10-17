
import time
import ctypes
import pyautogui


class ActionManager:
    def __init__(self):
        self.mouse_state = "Idle"
        self.mouse_button_held = False
        self.mouse_screen_width, self.mouse_screen_height = pyautogui.size()
        self.actions = {
            "SWIPE LEFT": self.snap_left,
            "SWIPE RIGHT": self.snap_right,
            "SWIPE DOWN": self.minimize_all,
            "SWIPE UP": self.restore_windows,
            "Peace Sign": self.switch_app,
            "Thumbs Up": self.play_pause,
            "Closed Fist": self.toggle_emergency_stop,
            "Pinch": self.toggle_mouse_mode,
        }

        self.last_action_time = 0
        self.action_cooldown = 0.5
        self.emergency_stop = False
        self.mouse_mode = False

    def execute(self, event):
        gesture = event["gesture"]

        # Emergency stop must always remain accessible.
        if gesture == "Closed Fist":
            self.toggle_emergency_stop()
            return

        if self.emergency_stop:
            print("Actions disabled. Make a Closed Fist to re-enable.")
            return

        action = self.actions.get(gesture)
        if action is None:
            return

        now = time.monotonic()
        if now - self.last_action_time < self.action_cooldown:
            return

        self.last_action_time = now

        try:
            action()
        except Exception as error:
            print(f"Action failed: {error}")

    # Window controls
    def snap_left(self):
        pyautogui.hotkey("win", "left")
        print("ACTION: Window snapped left")

    def snap_right(self):
        pyautogui.hotkey("win", "right")
        print("ACTION: Window snapped right")

    def minimize_all(self):
        pyautogui.hotkey("win", "m")
        print("ACTION: All windows minimized")

    def restore_windows(self):
        pyautogui.hotkey("win", "shift", "m")
        print("ACTION: Minimized windows restored")

    
    def process_mouse(self, gesture, landmarks=None):
        # Release the button if the hand disappears or tracking is lost.
        if landmarks is None or gesture in ("Unknown", "Waiting for gesture..."):
            self.release_mouse()
            self.mouse_state = "Idle"
            return

        # Move the cursor only while Pinch is active.
        if gesture == "Pinch":
            if self.mouse_button_held:
                self.release_mouse()

            self.mouse_state = "Pinch"

            index_tip = landmarks[8]
            x = int(index_tip.x * self.mouse_screen_width)
            y = int(index_tip.y * self.mouse_screen_height)

            x = max(0, min(x, self.mouse_screen_width - 1))
            y = max(0, min(y, self.mouse_screen_height - 1))

            pyautogui.moveTo(x, y, duration=0)
            return

        # Entering Click State from Pinch presses and holds left mouse.
        if gesture == "Click State":
            if self.mouse_state == "Pinch" and not self.mouse_button_held:
                pyautogui.mouseDown(button="left")
                self.mouse_button_held = True
                print("MOUSE: Left button held")

            self.mouse_state = "Click State"
            return

        # Any other recognized gesture stops mouse control.
        self.release_mouse()
        self.mouse_state = gesture


    def release_mouse(self):
        if self.mouse_button_held:
            pyautogui.mouseUp(button="left")
            self.mouse_button_held = False
            print("MOUSE: Left button released")

    # Gesture controls
    def switch_app(self):
        pyautogui.keyDown("alt")
        pyautogui.press("tab")
        pyautogui.keyUp("alt")
        print("ACTION: Switched application")

    def play_pause(self):
        # Windows media play/pause key
        ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)
        print("ACTION: Media play/pause")

    def toggle_emergency_stop(self):
        self.emergency_stop = not self.emergency_stop

        if self.emergency_stop:
            self.mouse_mode = False
            print("EMERGENCY STOP: Gesture actions disabled")
        else:
            print("EMERGENCY STOP: Gesture actions re-enabled")

    def toggle_mouse_mode(self):
        self.mouse_mode = not self.mouse_mode
        print(f"Mouse interaction mode: {'ON' if self.mouse_mode else 'OFF'}")
