# System Flow & Module Connection Map

This document explains how files, classes, and functions connect with each other across **Gesture PC**, detailing runtime data flows, threading boundaries, and interface contracts.

---

## 1. High-Level Architectural Flow

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. UI LAYER (PySide6 - Main UI Thread)                                       │
│ main_window.py, live_monitor_tab.py, gesture_studio_tab.py,                  │
│ workflow_studio_tab.py, testing_tab.py, settings_tab.py, tray.py, live_overlay.py │
└──────────────────────────┬───────────────────────▲──────────────────────────┘
                           │ UI Commands           │ Qt Signals (Queued)
                           ▼                       │
┌──────────────────────────────────────────────────┴──────────────────────────┐
│ 2. APPLICATION SERVICES & CONTROL (services/)                               │
│ runtime_controller.py ──(picks sink)──► diagnostic_sink.py (TEST / STOPPED) │
│                       └──(picks sink)──► live_sink.py (LIVE only)           │
│ execution_gate.py ◄─────── closes ─────── global_hotkey.py / UI Stop       │
│ event_bus.py ──────────── publishes ────► ui/qt_bridge.py                   │
│ snapshot_service.py ────── creates ─────► TemplateSnapshot / WorkflowSnapshot│
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │ Pipeline Control (Start/Stop)
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. CAMERA & RECOGNITION PIPELINE (camera/ + gestures/ - Dedicated Threads)   │
│ Capture Thread:                                                             │
│ camera_manager.py ──► capture_worker.py ──► opencv_backend.py (Latest Mailbox)│
│                                                          │ Raw Frame        │
│ Recognition Thread:                                      ▼                  │
│ recognition_engine.py ◄── hand_tracker.py ◄── mediapipe_backend.py          │
│        │                                                                    │
│        ▼ (Ordered Pipeline)                                                 │
│ hand_selector.py ──► normalizer.py ──► static_matcher.py / dynamic_matcher.py│
│        │                                     │                              │
│        ▼                                     ▼ Candidate Match              │
│ FrameAnalysis (All frames)             trigger_validator.py                 │
│        │                                     │ Passed Trigger?              │
│        ▼                                     ▼                              │
│ ┌───────────────┐                  RecognitionEvent (Accepted Only)         │
│ │   EventSink   │ ◄──────────────────────────┘                              │
│ └──────┬────────┘                                                           │
└────────┼────────────────────────────────────────────────────────────────────┘
         │
         ├── [In TEST / STOPPED / RECORDING mode]
         │    └─► diagnostic_sink.py ──► event_bus.py ──► UI diagnostics & logs
         │
         └── [In LIVE mode only]
              └─► live_sink.py
                    │ 1. ExecutionGate.admit()
                    │ 2. context/active_application.py (Capture AppContext)
                    │ 3. workflows/workflow_resolver.py (Resolve matching workflow)
                    │ 4. workflows/execution_dispatcher.py.submit()
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. EXECUTION LAYER (workflows/ - Dedicated Single-Worker Thread)            │
│ workflow_executor.py                                                        │
│        │                                                                    │
│        ├── Check: Gate epoch still valid? Token cancelled?                  │
│        ▼                                                                    │
│ action_registry.py ──► Action (keyboard, mouse, window, application)         │
│        │                                                                    │
│        ▼ calls port                                                         │
│ domain/ports.py: DesktopActionAdapter                                       │
│        │                                                                    │
│        ▼ implemented by                                                     │
│ adapters/windows/desktop_actions.py (Win32 SendInput / ctypes)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. File-by-File Connection Directory

### A. Composition Root & App Lifecycle
- `main.py`:
  - Calls `app/paths.py` to acquire the single-instance lock file.
  - Calls `app/logging_config.py` to configure structured log rotation.
  - Calls `app/application.py:Application.build()` to construct the graph.
  - Starts the Qt event loop (`QApplication.exec()`) and ensures clean shutdown.
- `app/application.py`:
  - **Composition Root**: Instantiates database connections, migrations, repositories, camera backend, recognition engine, execution gate, dispatcher, sinks, controller, and UI.
  - Injects `LiveSink` with references to `ExecutionGate` and `ExecutionDispatcher`.
  - Injects `DiagnosticSink` **without** any execution or gate dependencies.
  - Injects services into UI tabs and `MainWindow`.
- `app/config.py`:
  - Defines `SettingsSchema` (Pydantic model) containing default values, validation bounds, and setting categories.
  - Loaded by `services/configuration_service.py` to validate database values against defaults.

### B. Core Services (`services/`)
- `services/runtime_controller.py`:
  - Enforces the runtime state machine (`STOPPED`, `RECORDING`, `TEST`, `LIVE`).
  - Connects to `CameraManager` to start/stop the capture pipeline.
  - Configures `RecognitionEngine` with the active `EventSink` (`DiagnosticSink` or `LiveSink`).
  - Listens to system events (session lock/sleep) and failure counters to force immediate fallback to `STOPPED`.
- `services/execution_gate.py`:
  - Thread-safe admission token generator (`admit()`).
  - Tracks monotonic `epoch`. Any call to `close()` increments the epoch and sets the cancellation token, instantly invalidating all unexecuted actions in-flight.
- `services/diagnostic_sink.py`:
  - Receives `FrameAnalysis` and `RecognitionEvent` when mode is `TEST`, `RECORDING`, or `STOPPED`.
  - Forwards diagnostic events directly to `EventBus` for UI visualization.
  - Has zero imports or references to execution components.
- `services/live_sink.py`:
  - Receives `RecognitionEvent` when mode is `LIVE`.
  - Calls `ExecutionGate.admit()` to acquire an execution ticket.
  - Queries `context/active_application.py` for foreground process info.
  - Calls `workflows/workflow_resolver.py` to find the highest-priority workflow.
  - Forwards the admitted request to `workflows/execution_dispatcher.py`.
- `services/event_bus.py`:
  - Pure publish/subscribe bus for decoupled domain events.
  - Listened to by `ui/qt_bridge.py` and `services/event_logger.py`.

### C. Camera & Tracking (`camera/`)
- `camera/camera_manager.py`:
  - Coordinates camera hardware state. Ensures only one thread opens the hardware device.
  - Manages life cycle of `CaptureWorker`.
- `camera/capture_worker.py`:
  - Background `QThread` or Python `Thread` running OpenCV frame retrieval.
  - Puts the latest frame into a single-frame mailbox (`writeable=False` NumPy array).
- `camera/opencv_backend.py`:
  - Implements `domain/ports.py:CameraBackend` via `cv2.VideoCapture`.
- `camera/hand_tracker.py` & `camera/mediapipe_backend.py`:
  - Implements `domain/ports.py:HandTrackerBackend`.
  - Wraps MediaPipe Tasks `HandLandmarker` in synchronous `VIDEO` mode.
  - Returns raw 21 landmark 3D positions per frame.

### D. Gesture Recognition Engine (`gestures/`)
- `gestures/recognition_engine.py`:
  - Coordinates the recognition pipeline on each new camera frame.
  - Execution order:
    1. Call `camera/hand_tracker.py` -> extracts landmarks.
    2. Call `gestures/hand_selector.py` -> picks the active hand (Right/Left).
    3. Call `gestures/normalizer.py` -> scales by palm unit, centers wrist.
    4. Call `gestures/feature_extractor.py` -> calculates joint angles and pairwise distances.
    5. Call `gestures/static_matcher.py` -> compares against static templates in `TemplateSnapshot`.
    6. Call `gestures/segmenter.py` + `gestures/resampler.py` + `gestures/dynamic_matcher.py` -> evaluates dynamic gestures at motion segment end.
    7. Call `gestures/trigger_validator.py` -> evaluates pose stability duration, cooldown, and rearm release.
    8. Emits `FrameAnalysis` (every frame) and `RecognitionEvent` (accepted triggers) to `EventSink`.

### E. Workflows & Execution (`workflows/`)
- `workflows/workflow_resolver.py`:
  - Pure function. Input: `(gesture_id, AppContext, WorkflowSnapshot)`.
  - Output: Matching `WorkflowDefinition` (prefers app-specific workflow over default; respects strict-per-app toggle).
- `workflows/workflow_preview.py`:
  - Pure function generating human-readable descriptions of what a workflow would do (used in dry-runs and Test mode).
- `workflows/execution_dispatcher.py`:
  - Enforces `DROP_WHILE_BUSY`. Holds single worker thread.
  - Drops new requests if the worker is actively busy running a previous workflow.
  - Passes admitted request to `WorkflowExecutor`.
- `workflows/workflow_executor.py`:
  - Runs on the dedicated single execution worker thread.
  - Iterates through `WorkflowAction` objects:
    - Before EVERY action: re-verifies `ExecutionGate.is_admitted(epoch)` and checks `cancellation_token.is_set()`.
    - Looks up the executable action in `workflows/action_registry.py`.
    - Calls `action.execute(context, adapter)`.
- `workflows/actions/`:
  - Action implementations (`window_actions.py`, `keyboard_actions.py`, `mouse_actions.py`, `application_actions.py`).
  - Calls `domain/ports.py:DesktopActionAdapter`.

### F. Windows Adapters (`adapters/windows/`)
- `adapters/windows/desktop_actions.py`:
  - Implements `DesktopActionAdapter` using Win32 `SendInput` (`ctypes`).
  - Supports keyboard chords, mouse clicks, mouse moves, and window state changes.
- `adapters/windows/foreground_window.py`:
  - Implements `ForegroundWindowProvider`. Calls Win32 `GetForegroundWindow` and `psutil` to inspect the active process name and path.
- `adapters/windows/global_hotkey.py`:
  - Implements `GlobalHotkeyService` via Win32 `RegisterHotKey`. Listens on a dedicated message-only window thread.
  - Upon receiving the hotkey event (`Ctrl+Alt+Shift+X`), immediately calls `ExecutionGate.close()` and notifies `RuntimeController`.
- `adapters/windows/session_events.py`:
  - Implements `SessionEventSource`. Hooks `WTSRegisterSessionNotification` to catch lock, logoff, and display sleep events, immediately forcing fallback to `STOPPED`.

### G. Persistence & Data Layer (`database/`)
- `database/connection.py`:
  - Provides SQLite connection factory with WAL mode, foreign keys, and 5000 ms busy timeout.
- `database/migrator.py`:
  - Runs sequential numbered SQL scripts from `database/migrations/` (`0001_initial.sql`).
- `database/codecs.py`:
  - Serializes and deserializes landmark float32 arrays into SQLite BLOBs.
- `database/repositories/`:
  - `gesture_repository.py`: CRUD for gestures and raw landmark samples.
  - `workflow_repository.py`: CRUD for workflows and actions.
  - `settings_repository.py`: Key-value storage for settings.
  - `log_repository.py`: Inserts execution and diagnostic records (written by background log thread).

---

## 3. End-to-End Runtime Flows

### Flow A: Application Startup
1. User launches `main.py`.
2. `paths.py` checks single-instance lock file.
3. `logging_config.py` sets up 5 x 1MB rotating log files.
4. `application.py:Application.build()`:
   - Initializes SQLite connection and runs `database/migrator.py`.
   - Constructs repositories.
   - Loads and validates settings via `ConfigurationService`.
   - Constructs `EventBus` and `EventLogger`.
   - Constructs `ExecutionGate` and `ExecutionDispatcher`.
   - Constructs `LiveSink` (holding gate & dispatcher) and `DiagnosticSink` (holding neither).
   - Constructs `CameraManager` and `RecognitionEngine`.
   - Constructs `RuntimeController` starting in `STOPPED`.
   - Builds `SnapshotService` to compile current templates and workflows into immutable snapshots.
   - Instantiates `MainWindow`, injecting `QtBridge` and child tab views.
5. `main_window.show()`. Application awaits user input in `STOPPED` mode.

### Flow B: Starting Live Mode
1. User clicks "Start Live Automation" in `MainWindow` or `LiveMonitorTab`.
2. `MainWindow` sends command to `RuntimeController.start_live()`.
3. `RuntimeController` verifies preconditions (§4.3):
   - Global stop hotkey registered successfully.
   - Camera opened and producing frames.
   - Settings valid; at least one enabled gesture has an enabled workflow.
   - Windows session is unlocked.
4. `RuntimeController` sets mode to `LIVE`.
5. `RuntimeController` points `RecognitionEngine`'s sink to `LiveSink`.
6. `ExecutionGate.open()` opens the gate and increments epoch.
7. `EventBus` publishes `RuntimeStatusChanged(mode=LIVE)`.
8. `QtBridge` receives event and triggers UI update (status badge green, LIVE overlay appears).

### Flow C: Real-Time Recognition to Execution
1. `CaptureWorker` captures OpenCV frame -> places in mailbox.
2. `RecognitionEngine` (recognition thread) retrieves frame:
   - `MediaPipeBackend.process_video_frame()` produces raw 21 3D landmarks.
   - `HandSelector` selects the designated hand.
   - `Normalizer` translates wrist to origin and scales by palm distance.
   - `FeatureExtractor` extracts joint angles and finger states.
   - `StaticMatcher` computes Euclidean distance to all static templates in `TemplateSnapshot`.
   - `TriggerValidator` checks:
     - Distance $\le$ threshold?
     - Ratio to runner-up $\le$ margin ratio?
     - Pose held steadily for $\ge 400\text{ ms}$?
     - Gesture not in active cooldown?
3. If trigger conditions are satisfied:
   - Emits `RecognitionEvent(gesture_id, timestamp)` to `LiveSink`.
4. `LiveSink`:
   - Checks `ExecutionGate.admit(request)`. If closed, drops request.
   - Captures `AppContext` from `ForegroundWindowProvider`.
   - Calls `WorkflowResolver.resolve(gesture_id, app_context, workflow_snapshot)`.
   - Checks rate limit ($\le 20\text{ executions/min}$).
   - Calls `ExecutionDispatcher.submit(execution_request)`.
5. `ExecutionDispatcher`:
   - If worker is currently busy (`DROP_WHILE_BUSY`), drops request and logs `DROPPED_BUSY`.
   - Otherwise, dispatches request to execution worker thread.
6. `WorkflowExecutor`:
   - Before executing action 1..N:
     - Checks `ExecutionGate.is_admitted(ticket.epoch)`.
     - Checks `cancellation_token.is_set()`.
   - Executes action via `DesktopActionAdapter` (Win32 `SendInput`).
   - Emits `WorkflowCompleted` to `EventBus` -> logged in SQLite log table.

### Flow D: Emergency Stop Sequence
1. User presses `Ctrl+Alt+Shift+X` (or clicks STOP in UI, Overlay, or Tray).
2. Win32 `WM_HOTKEY` message fires in `GlobalHotkeyService` background thread.
3. Immediately calls `ExecutionGate.close()`:
   - Sets gate closed.
   - Increments `epoch` (invalidating all outstanding admissions).
   - Sets `cancellation_token` (aborting sleeps or active action loops).
4. `GlobalHotkeyService` notifies `RuntimeController.stop_immediately(REASON_HOTKEY)`.
5. `RuntimeController` transitions state to `STOPPED`:
   - Switches recognition sink back to `DiagnosticSink`.
   - Clears pending dispatcher items.
6. Total stop latency target: $p95 \le 100\text{ ms}$.

### Flow E: Static Gesture Recording & Calibration in Gesture Studio
1. User selects target hand (`RIGHT`, `LEFT`, or `EITHER`) and clicks "Start Recording".
2. `RuntimeController.transition_to(RuntimeMode.RECORDING)`:
   - Camera starts delivering frames to `CaptureWorker`.
   - Lossless queue activated (`recording_queue`).
3. `StaticGestureRecorder`:
   - Enters `COUNTDOWN` state (3000 ms countdown). Shows live preview with countdown and quality indicator (hand present & steady).
   - Enters `CAPTURING` state: gathers frames over `static_capture_window_ms` (1500 ms).
   - On window completion, invokes `RecordingValidator.validate_static_recording()`:
     - Verifies hand presence, consistency, speed $\le 0.35$ palm units/s, and pose deviation $\le 0.10$ palm units against running median pose.
     - Selects up to 30 evenly spaced valid sample frames.
4. `GestureService.check_static_collisions()`:
   - Computes base threshold $1.5 \times p95(r)$ clamped to $[0.06, 0.30]$.
   - Checks minimum MLD against all existing gestures of the same hand.
   - If collision detected, UI warns the user with conflicting gesture name and distance.
5. User enters gesture name and clicks "Save Gesture" (or "Save Anyway"):
   - Persists gesture metadata and raw landmark BLOBs in SQLite in a single transaction.
   - Fires `GestureRegistered` event.
   - `SnapshotService` debounces and compiles new `TemplateSnapshot` with atomic reference swap.

### Flow F: Safe Evaluation in Test Mode (Recognition Only)
1. User clicks "Start Test" on `TestingTab` (or `LiveMonitorTab`).
2. `RuntimeController` transitions to `RuntimeMode.TEST`:
   - `active_sink` set to `DiagnosticSink`.
   - Camera pipeline starts.
3. `RecognitionPipeline` background worker thread polls frames from `camera_manager.live_mailbox`:
   - `HandTracker` extracts 3D world landmarks and aspect-corrected image landmarks.
   - `HandSelector` selects designated hand according to `tracked_hand`.
   - `RecognitionEngine` calculates 80 ms EMA hand speed.
   - If hand is stationary:
     - `normalize_world_landmarks()` translates wrist to origin and scales by palm unit ($\|L_9 - L_0\|$).
     - `extract_static_features()` builds 60-element feature vector.
     - `StaticMatcher.match()` evaluates template distances and margin ratio ($d_1 / d_2 \le 0.80$).
     - `TriggerValidator.update()` tracks temporal stability hold toward 400 ms.
4. `RecognitionEngine` produces `FrameAnalysis` and optional `RecognitionEvent`.
5. `active_sink` (`DiagnosticSink`) receives diagnostics and events:
   - Forwards to `QtBridge`.
   - Zero execution capability: cannot admit, dispatch, or execute actions (Rule R4 / AC-09).
6. `QtBridge` updates `TestingTab`:
   - Real-time diagnostic telemetry (speed, best match, distance, threshold, margin, trigger state).
   - Stability hold progress bar (0 to 400 ms).
   - Accepted triggers table.

---

## 4. Threading Architecture & Boundaries

```text
┌──────────────────┐
│   Main Thread    │  PySide6 GUI event loop, painting, user interaction.
└────────┬─────────┘  NEVER runs recognition, camera I/O, or desktop actions.
         │
         ▼ Queued Signals via ui/qt_bridge.py
┌──────────────────┐
│  Capture Thread  │  OpenCV VideoCapture reading; latest-frame mailbox.
└──────────────────┘
┌──────────────────┐
│Recognition Thread│  MediaPipe Tasks HandLandmarker + Normalizer + Matchers.
└──────────────────┘
┌──────────────────┐
│ Execution Worker │  Single worker thread executing workflow actions sequentially.
└──────────────────┘
┌──────────────────┐
│ OS Events Thread │  Win32 message pump for RegisterHotKey & session events.
└──────────────────┘
┌──────────────────┐
│Log Writer Thread │  Batched asynchronous SQLite database writes for logs.
└──────────────────┘
```
