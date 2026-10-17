
import cv2
import mediapipe as mp
import math
import time
from collections import deque
from gesture_trigger import GestureTrigger
from actionManager import ActionManager

action_manager = ActionManager()
trigger_manager = GestureTrigger(cooldown=0.8)

# -----------------------------
# INITIALIZATION
# -----------------------------

mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

landmark_style = mp_draw.DrawingSpec(
    color=(80, 220, 100), thickness=2, circle_radius=4
)
connection_style = mp_draw.DrawingSpec(
    color=(255, 180, 70), thickness=3
)

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    hands.close()
    raise RuntimeError("Could not access webcam.")

# -----------------------------
# SETTINGS
# -----------------------------

SWIPE_DISTANCE = 0.18
SWIPE_TIME_LIMIT = 0.8
SWIPE_COOLDOWN = 0.8
UNKNOWN_GRACE_PERIOD = 0.20

hand_history = {"Left": deque(maxlen=30), "Right": deque(maxlen=30)}
last_open_palm_time = {"Left": 0.0, "Right": 0.0}
last_swipe_time = {"Left": 0.0, "Right": 0.0}

last_event = "Waiting for gesture..."
last_event_time = 0.0


# -----------------------------
# GESTURE CLASSIFICATION
# -----------------------------

def distance(point1, point2):
    return math.hypot(
        point1.x - point2.x,
        point1.y - point2.y
    )


def classify_gesture(landmarks):
    lm = landmarks.landmark

    index_up = lm[8].y < lm[6].y
    middle_up = lm[12].y < lm[10].y
    ring_up = lm[16].y < lm[14].y
    pinky_up = lm[20].y < lm[18].y

    fingers = [index_up, middle_up, ring_up, pinky_up]
    extended_count = sum(fingers)

    thumb_extended = (
        distance(lm[4], lm[5]) >
        distance(lm[3], lm[5])
    )

    # Open Palm
    if extended_count == 4 and thumb_extended:
        return "Open Palm"

    # Peace Sign
    if index_up and middle_up and not ring_up and not pinky_up:
        return "Peace Sign"

    # Pinch: index folded; other three fingers extended
    index_down = lm[8].y > lm[6].y
    middle_down = lm[12].y > lm[10].y
    ring_down = lm[16].y > lm[14].y

    if index_down and middle_up and ring_up and pinky_up:
        return "Pinch"

    # Click State: index, middle, ring folded; pinky extended
    if index_down and middle_down and ring_down and pinky_up:
        return "Click State"

    # Closed Fist
    if extended_count == 0 and not thumb_extended:
        return "Closed Fist"

    # Thumbs Up
    if thumb_extended and not any(fingers):
        return "Thumbs Up"

    return "Unknown"


# -----------------------------
# SWIPE DETECTION
# -----------------------------

def detect_swipe(hand_label, x, y, now):
    history = hand_history[hand_label]
    history.append((now, x, y))

    while len(history) > 1 and now - history[0][0] > SWIPE_TIME_LIMIT:
        history.popleft()

    if len(history) < 3:
        return None

    start_time, start_x, start_y = history[0]
    elapsed = now - start_time

    if elapsed <= 0:
        return None

    dx = x - start_x
    dy = y - start_y

    if math.hypot(dx, dy) < SWIPE_DISTANCE:
        return None

    if abs(dx) > abs(dy) * 1.3:
        direction = "RIGHT" if dx > 0 else "LEFT"
    elif abs(dy) > abs(dx) * 1.3:
        direction = "DOWN" if dy > 0 else "UP"
    else:
        return None

    if now - last_swipe_time[hand_label] < SWIPE_COOLDOWN:
        return None

    last_swipe_time[hand_label] = now
    history.clear()
    return f"SWIPE {direction}"


# -----------------------------
# MAIN LOOP
# -----------------------------
print("Gesture recognition running. Press Q to quit.")

try:
    while True:
        success, frame = cap.read()
        if not success:
            print("Could not read webcam frame.")
            break

        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = hands.process(rgb_frame)
        rgb_frame.flags.writeable = True

        now = time.monotonic()
        detected_hands = 0
        seen_hands = set()
        mouse_processed = False

        if results.multi_hand_landmarks:
            for index, hand_landmarks in enumerate(results.multi_hand_landmarks):
                detected_hands += 1
                lm = hand_landmarks.landmark

                hand_label = "Unknown"
                if results.multi_handedness and index < len(results.multi_handedness):
                    hand_label = (
                        results.multi_handedness[index]
                        .classification[0].label
                    )

                if hand_label not in hand_history:
                    hand_label = "Left"

                seen_hands.add(hand_label)
                gesture = classify_gesture(hand_landmarks)

                wrist_x = lm[0].x
                wrist_y = lm[0].y

                # Swipes require Open Palm.
                if gesture == "Open Palm":
                    last_open_palm_time[hand_label] = now
                    swipe = detect_swipe(hand_label, wrist_x, wrist_y, now)
                    if swipe:
                        gesture = swipe

                elif (
                    gesture == "Unknown"
                    and now - last_open_palm_time[hand_label]
                    <= UNKNOWN_GRACE_PERIOD
                ):
                    swipe = detect_swipe(hand_label, wrist_x, wrist_y, now)
                    if swipe:
                        gesture = swipe
                    else:
                        gesture = "Open Palm (tracking)"
                else:
                    hand_history[hand_label].clear()

                # Mouse processing runs every frame, not only on new triggers.
                # Swipes must not be interpreted as mouse gestures.
                if gesture.startswith("SWIPE"):
                    action_manager.process_mouse(gesture, None)
                else:
                    action_manager.process_mouse(
                        gesture, hand_landmarks.landmark
                    )

                mouse_processed = True

                mp_draw.draw_landmarks(
                    frame, hand_landmarks, mp_hands.HAND_CONNECTIONS,
                    landmark_style, connection_style
                )

                height, width, _ = frame.shape
                x_label = int(min(p.x for p in lm) * width)
                y_label = max(int(min(p.y for p in lm) * height) - 15, 30)

                cv2.putText(
                    frame, f"{hand_label}: {gesture}",
                    (x_label, y_label), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 255, 255), 2
                )

                event = trigger_manager.update(hand_label, gesture)

                if event:
                    print(
                        f"TRIGGER | {event['hand']} hand | "
                        f"{event['gesture']}"
                    )
                    last_event = f"{event['hand']}: {event['gesture']}"
                    last_event_time = now
                    action_manager.execute(event)

        # If the hand disappears, release any held click.
        if not mouse_processed:
            action_manager.process_mouse("Unknown", None)

        for label in hand_history:
            if label not in seen_hands:
                if now - last_open_palm_time[label] > UNKNOWN_GRACE_PERIOD:
                    hand_history[label].clear()

        # -----------------------------
        # STATUS UI
        # -----------------------------

        cv2.rectangle(frame, (10, 10), (470, 100), (30, 30, 30), -1)

        cv2.putText(
            frame, f"Hands detected: {detected_hands}/1",
            (20, 38), cv2.FONT_HERSHEY_SIMPLEX,
            0.65, (100, 255, 150), 2
        )

        event_text = (
            last_event if now - last_event_time < 2.0
            else "Waiting for gesture..."
        )

        cv2.putText(
            frame, event_text, (20, 75),
            cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 220, 255), 2
        )

        cv2.imshow("Gesture PC - Recognition", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    action_manager.release_mouse()
    cap.release()
    hands.close()
    cv2.destroyAllWindows()
