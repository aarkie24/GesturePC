# Architectural & Engineering Decisions Record (ADR)

This document tracks all major design and engineering decisions for **Gesture PC**, detailing the context, the decision made, alternatives evaluated, the underlying rationale, and how each decision is enforced.

---

## Decision Index

- [DEC-01: Template Matching First over Custom Neural Network Training](#dec-01-template-matching-first-over-custom-neural-network-training)
- [DEC-02: Single Shared Recognition Engine for Both Test and Live Modes](#dec-02-single-shared-recognition-engine-for-both-test-and-live-modes)
- [DEC-03: Structural Safety Boundary via ExecutionGate and Mode Sinks](#dec-03-structural-safety-boundary-via-executiongate-and-mode-sinks)
- [DEC-04: Workflow Configuration as Pure Data (No Code Execution)](#dec-04-workflow-configuration-as-pure-data-no-code-execution)
- [DEC-05: SQLite with Write-Ahead Logging (WAL) and Numbered Migrations](#dec-05-sqlite-with-write-ahead-logging-wal-and-numbered-migrations)
- [DEC-06: Windows-First Behind Clean Port Protocols](#dec-06-windows-first-behind-clean-port-protocols)
- [DEC-07: Vertical Slice Architecture in Early Milestones (M3)](#dec-07-vertical-slice-architecture-in-early-milestones-m3)
- [DEC-08: Storing Raw Landmark Observations; Deriving Features at Runtime](#dec-08-storing-raw-landmark-observations-deriving-features-at-runtime)
- [DEC-09: Orientation-Sensitive, Hand-Specific Matching Without Auto-Mirroring](#dec-09-orientation-sensitive-hand-specific-matching-without-auto-mirroring)
- [DEC-10: Motion-Segmented Band-Limited DTW with Early Abandoning](#dec-10-motion-segmented-band-limited-dtw-with-early-abandoning)
- [DEC-11: Drop-While-Busy Execution Policy (At-Most-Once Execution)](#dec-11-drop-while-busy-execution-policy-at-most-once-execution)
- [DEC-12: Action Risk Tiers, Elevated Dialogs, and Approved Applications](#dec-12-action-risk-tiers-elevated-dialogs-and-approved-applications)
- [DEC-13: Multilateral Immediate Stop Mechanism (Global Hotkey, Overlay, Tray)](#dec-13-multilateral-immediate-stop-mechanism-global-hotkey-overlay-tray)
- [DEC-14: Bundled MediaPipe Tasks HandLandmarker in Synchronous VIDEO Mode](#dec-14-bundled-mediapipe-tasks-handlandmarker-in-synchronous-video-mode)
- [DEC-15: Direct ctypes SendInput Wrapper over Heavy Automation Libraries](#dec-15-direct-ctypes-sendinput-wrapper-over-heavy-automation-libraries)
- [DEC-16: Strict Offline Guarantee (Zero Network Access Policy)](#dec-16-strict-offline-guarantee-zero-network-access-policy)
- [DEC-17: Headless OpenCV to Prevent Qt Plugin Collisions](#dec-17-headless-opencv-to-prevent-qt-plugin-collisions)
- [DEC-18: Pure Dependency Injection via Composition Root](#dec-18-pure-dependency-injection-via-composition-root)
- [DEC-19: Synchronous MediaPipe Tasks Landmarker Confirmed for Windows](#dec-19-synchronous-mediapipe-tasks-landmarker-confirmed-for-windows)
- [DEC-20: Vectorized NumPy DTW Accepted; Numba Rejected](#dec-20-vectorized-numpy-dtw-accepted-numba-rejected)
- [DEC-21: DSHOW Confirmed as Primary VideoCapture Backend on Windows](#dec-21-dshow-confirmed-as-primary-videocapture-backend-on-windows)
- [DEC-22: Native 64-bit Win32 SendInput and RegisterHotKey Primitives Validated](#dec-22-native-64-bit-win32-sendinput-and-registerhotkey-primitives-validated)
- [DEC-23: Isolated Win32 Message Pump for Stop Hotkey & Session Events](#dec-23-isolated-win32-message-pump-for-stop-hotkey--session-events)
- [DEC-24: Single-Slot Frame Mailbox with Monotonic Grab Timestamps](#dec-24-single-slot-frame-mailbox-with-monotonic-grab-timestamps)

---

### DEC-01: Template Matching First over Custom Neural Network Training
* **Status:** Accepted
* **Context:** The system requires users to define custom static poses and dynamic movements on their local machine.
* **Decision:** Use nearest-neighbor normalized landmark vector distance (static) and motion-segmented dynamic time warping (dynamic), rather than training or fine-tuning neural networks per user.
* **Alternatives Considered:** Training a small MLP / LSTM or fine-tuning a classifier per user.
* **Reason:** Template matching requires only 1 to 5 user samples, trains in 0 ms, operates with zero GPU requirements, produces fully interpretable distance metrics and thresholds, and avoids catastrophic forgetting or dataset collection friction.
* **Enforcement:** `gestures/static_matcher.py` and `gestures/dynamic_matcher.py`.

---

### DEC-02: Single Shared Recognition Engine for Both Test and Live Modes
* **Status:** Accepted
* **Context:** The application has a "Test mode" (for safe preview/tuning) and a "Live mode" (executing real actions).
* **Decision:** The camera, tracking, normalization, matching, and trigger validation run the exact same code in both modes. Only the output `EventSink` is switched.
* **Alternatives Considered:** A separate testing simulator or mock recognizer for Test mode.
* **Reason:** Ensures what the user sees and validates in Test mode behaves with 100% mathematical fidelity in Live mode, preventing "works in test but fails in live" discrepancies.
* **Enforcement:** Architectural Rule R3; verified by `tests/architecture/test_import_rules.py`.

---

### DEC-03: Structural Safety Boundary via ExecutionGate and Mode Sinks
* **Status:** Accepted
* **Context:** Ensuring desktop actions are never triggered accidentally or while in diagnostic/testing/recording states.
* **Decision:** Execution capability is guarded by structural wiring:
  - `STOPPED`, `RECORDING`, and `TEST` routes frames/events to `DiagnosticSink` only. `DiagnosticSink` has zero import paths or references to `ExecutionGate`, `ExecutionDispatcher`, or `DesktopActionAdapter`.
  - Only `LiveSink` holds access to `ExecutionGate` and `ExecutionDispatcher`.
  - `ExecutionGate` enforces epoch-based admission tickets; invalidation immediately revokes in-flight execution.
* **Alternatives Considered:** A simple boolean `is_live` check inside the action executor.
* **Reason:** Boolean checks can be bypassed by race conditions or refactoring regressions. Structural isolation prevents desktop actions from executing even if bugs occur in recognition.
* **Enforcement:** Architectural Rules R1, R2, R4; enforced by `tests/architecture/test_import_rules.py` and unit tests in `tests/unit/test_execution_gate.py`.

---

### DEC-04: Workflow Configuration as Pure Data (No Code Execution)
* **Status:** Accepted
* **Context:** Workflows need to be stored, edited, and dynamically executed.
* **Decision:** All actions and parameters are strictly validated Pydantic models mapped to a whitelist of registered action classes in `ActionRegistry`. Arbitrary scripting, `eval()`, `exec()`, `pickle`, and `shell=True` are strictly prohibited.
* **Alternatives Considered:** Python scripts or shell command strings written by the user.
* **Reason:** Desktop security. A compromised database or misconfigured action must never lead to arbitrary code execution or privilege escalation.
* **Enforcement:** Architectural Rule R5; AST audit in architecture tests (`tests/architecture/test_no_eval.py`).

---

### DEC-05: SQLite with Write-Ahead Logging (WAL) and Numbered Migrations
* **Status:** Accepted
* **Context:** Storing gestures, landmark samples, workflows, settings, and execution logs in a single-user desktop environment.
* **Decision:** Use SQLite via Python's standard `sqlite3` module with `PRAGMA journal_mode=WAL`, foreign key enforcement, and explicit sequential SQL migration files (`database/migrations/0001_initial.sql`).
* **Alternatives Considered:** JSON files, raw pickle files, or an ORM like SQLAlchemy.
* **Reason:** SQLite is zero-dependency, crash-resilient (ACID), provides transactional integrity across multiple relations (cascading deletes for gestures/workflows), and handles binary BLOBs (compressed landmark vectors) cleanly. WAL mode allows concurrent readers without blocking writes.
* **Enforcement:** `database/connection.py`, `database/migrator.py`.

---

### DEC-06: Windows-First Behind Clean Port Protocols
* **Status:** Accepted
* **Context:** Automation requires deep OS interaction (input synthesis, window enumeration, global hotkeys, session events), but core domain logic should remain testable and portable.
* **Decision:** Define Python `typing.Protocol` interfaces in `domain/ports.py` (`DesktopActionAdapter`, `ForegroundWindowProvider`, `GlobalHotkeyService`, `SessionEventSource`). Concrete Windows implementations live exclusively in `adapters/windows/`.
* **Alternatives Considered:** Direct inline calls to `win32gui` or `ctypes` across UI or workflow modules.
* **Reason:** Enables fast, 100% headless automated testing using mock/fake adapters (`tests/fakes/`), eliminating accidental clicks on developer machines during CI runs.
* **Enforcement:** Architectural Rule R1; `tests/architecture/test_import_rules.py`.

---

### DEC-07: Vertical Slice Architecture in Early Milestones (M3)
* **Status:** Accepted
* **Context:** Risk of developing disconnected subsystems that fail to integrate smoothly near project completion.
* **Decision:** Build a complete vertical slice in Milestone 3 (camera -> tracking -> normalization -> static matching -> trigger validation -> Test UI) before expanding the workflow action catalog or adding dynamic DTW.
* **Alternatives Considered:** Building all UI tabs first or building all action types first.
* **Reason:** De-risks the hardest engineering problem (real-time camera capture + MediaPipe tracking + math matching) early in the schedule.
* **Enforcement:** Milestone sequence in `implementationPlan.md` §16.

---

### DEC-08: Storing Raw Landmark Observations; Deriving Features at Runtime
* **Status:** Accepted
* **Context:** Gesture samples can be stored as raw 3D coordinates or as precalculated feature vectors.
* **Decision:** Persist raw 21-landmark (x, y, z) coordinates (both image-relative and world landmarks) in SQLite as float32 binary arrays. Feature extraction (angles, distances) is derived dynamically in memory.
* **Alternatives Considered:** Storing only computed feature vectors in the database.
* **Reason:** Allows upgrading the normalization algorithm or feature representation in future versions without forcing users to delete and re-record their gestures.
* **Enforcement:** `database/codecs.py`, `domain/models.py`.

---

### DEC-09: Orientation-Sensitive, Hand-Specific Matching Without Auto-Mirroring
* **Status:** Accepted
* **Context:** Hand gestures can be performed by left or right hands, upright or sideways.
* **Decision:** Matchers are orientation-sensitive (relative to camera frame) and hand-specific (`LEFT`, `RIGHT`, or explicit `EITHER`). Left/right mirroring is disabled in v1.
* **Alternatives Considered:** Rotation-invariant matching and automatic template mirroring.
* **Reason:** In automation, orientation differentiates critical gestures (e.g., Thumbs Up [Confirm] vs. Thumbs Down [Reject], or Swipe Right vs. Swipe Left). Automatic mirroring causes ambiguity and false triggers.
* **Enforcement:** `gestures/normalizer.py`, `gestures/static_matcher.py`.

---

### DEC-10: Motion-Segmented Band-Limited DTW with Early Abandoning
* **Status:** Accepted
* **Context:** Real-time Dynamic Time Warping (DTW) across multiple template trajectories can be computationally prohibitive at high frame rates.
* **Decision:**
  1. Trigger dynamic matching only at the completion of a motion segment (velocity drops below idle threshold).
  2. Resample the feature sequence to a fixed temporal resolution (15 Hz).
  3. Run Sakoe-Chiba band-limited DTW (band fraction 0.25) with early abandonment (aborting computation when partial distance exceeds current best).
* **Alternatives Considered:** Continuous frame-by-frame sliding window DTW.
* **Reason:** Continuous DTW wastes CPU on stationary frames. Segmented DTW bounds execution to $\le 5$ ms per template comparison.
* **Enforcement:** `gestures/dynamic_matcher.py`, `gestures/resampler.py`, `gestures/segmenter.py`.

---

### DEC-11: Drop-While-Busy Execution Policy (At-Most-Once Execution)
* **Status:** Accepted
* **Context:** How to handle gestures recognized while a previous workflow is actively executing.
* **Decision:** Implement `DROP_WHILE_BUSY`. If an execution request arrives while the worker thread is busy, the event is immediately dropped and logged. At-most-once execution; zero automatic retries.
* **Alternatives Considered:** Multi-item FIFO queue or queuing with debounce.
* **Reason:** Queuing desktop automation leads to dangerous "runaway" action queues where keystrokes or mouse clicks fire seconds later over unexpected windows.
* **Enforcement:** `services/live_sink.py`, `workflows/execution_dispatcher.py`.

---

### DEC-12: Action Risk Tiers, Elevated Dialogs, and Approved Applications
* **Status:** Accepted
* **Context:** Automation can perform destructive tasks (closing windows, executing system shortcuts).
* **Decision:** Actions are classified into `SAFE` and `ELEVATED`. Workflows containing elevated actions require explicit user confirmation upon entering Live mode. Launching applications is restricted to an approved application whitelist.
* **Alternatives Considered:** Unrestricted system execution.
* **Reason:** Prevents accidental data loss or desktop hijacking through false recognition triggers.
* **Enforcement:** `workflows/actions/base.py`, `services/runtime_controller.py`.

---

### DEC-13: Multilateral Immediate Stop Mechanism (Global Hotkey, Overlay, Tray)
* **Status:** Accepted
* **Context:** A runaway workflow or misrecognized gesture must be stoppable instantaneously.
* **Decision:** Provide three independent stop vectors:
  1. Global Windows hotkey (`Ctrl+Alt+Shift+X` via `RegisterHotKey`).
  2. Always-on-top click-through LIVE overlay stop button.
  3. System tray icon context menu Stop.
  Live mode refuses to launch unless the global hotkey is successfully registered. Stop requests close `ExecutionGate` synchronously ($p95 \le 100\text{ ms}$).
* **Alternatives Considered:** In-window UI button only.
* **Reason:** When live automation executes, the main application window is usually out of focus or covered. An OS-level hotkey is mandatory.
* **Enforcement:** `adapters/windows/global_hotkey.py`, `services/execution_gate.py`, `services/runtime_controller.py`.

---

### DEC-14: Bundled MediaPipe Tasks HandLandmarker in Synchronous VIDEO Mode
* **Status:** Accepted
* **Context:** Hand tracking framework selection and threading mode.
* **Decision:** Bundle official `hand_landmarker.task` locally with SHA-256 verification. Use MediaPipe Tasks API in `VIDEO` running mode synchronously on a dedicated recognition thread. Disallow legacy `mp.solutions.hands`.
* **Alternatives Considered:** MediaPipe `LIVE_STREAM` asynchronous callback mode or legacy solution API.
* **Reason:** `LIVE_STREAM` uses internal native threads that can cause GIL lock contention and out-of-order landmark callbacks. Synchronous `VIDEO` mode gives the application strict determinism per frame.
* **Enforcement:** `camera/mediapipe_backend.py`, `app/application.py`.

---

### DEC-15: Direct ctypes SendInput Wrapper over Heavy Automation Libraries
* **Status:** Accepted
* **Context:** Synthesizing keyboard, mouse, and window management events on Windows.
* **Decision:** Build a lean `ctypes` wrapper over Win32 `SendInput`, `SetForegroundWindow`, and `ShowWindow`. Do not depend on PyAutoGUI.
* **Alternatives Considered:** PyAutoGUI, keyboard/mouse third-party libraries.
* **Reason:** PyAutoGUI introduces hidden global sleeps (`PAUSE`), global failsafe exceptions, and extra dependencies. Direct `SendInput` provides deterministic, millisecond-accurate input synthesis and clean cancellation checking before every event.
* **Enforcement:** `adapters/windows/desktop_actions.py`.

---

### DEC-16: Strict Offline Guarantee (Zero Network Access Policy)
* **Status:** Accepted
* **Context:** Privacy and security considerations for a webcam-enabled desktop app.
* **Decision:** Zero outbound or inbound network connections. All models, migrations, and assets are local.
* **Alternatives Considered:** Cloud telemetry or online model downloading.
* **Reason:** User webcam feeds and desktop activity are highly sensitive. An offline guarantee builds complete user trust.
* **Enforcement:** Architecture test `tests/architecture/test_no_network.py` auditing socket/requests imports.

---

### DEC-17: Headless OpenCV to Prevent Qt Plugin Collisions
* **Status:** Accepted
* **Context:** OpenCV standard binary packages often bundle their own copy of Qt, conflicting with PySide6.
* **Decision:** Standardize on `opencv-python-headless`.
* **Alternatives Considered:** `opencv-python` with `QT_QPA_PLATFORM_PLUGIN_PATH` environment workarounds.
* **Reason:** Avoids dynamic linker / DLL symbol collisions between PySide6 Qt binaries and OpenCV Qt binaries.
* **Enforcement:** `requirements.txt` and compatibility verification in Milestone 0.

---

### DEC-18: Pure Dependency Injection via Composition Root
* **Status:** Accepted
* **Context:** Managing lifecycle, testing fakes, and clean shutdown across multithreaded services.
* **Decision:** Instantiate all database connections, repositories, services, adapters, controllers, and UI components in `app/application.py` and pass dependencies downward. Zero global singletons.
* **Alternatives Considered:** Global module variables (`app_state.py`).
* **Reason:** Module-level state makes unit testing impossible to run in parallel and leads to memory leaks and shutdown deadlocks.
* **Enforcement:** `app/application.py`, `main.py`.

---

### DEC-19: Synchronous MediaPipe Tasks Landmarker Confirmed for Windows
* **Status:** Accepted (Validated in Milestone 0)
* **Context:** Validating MediaPipe Tasks `HandLandmarker` on Python 3.11 Windows x64.
* **Decision:** The bundled `assets/models/hand_landmarker.task` model with TensorFlow Lite XNNPACK delegate operates synchronously on CPU in `RunningMode.VIDEO`.
* **Benchmark Evidence:** Tested on physical webcam (640x480): sustained pipeline achieved 29.8 FPS (target: $\ge 20$ FPS); raw tracking inference $p50 = 11.4\text{ ms}$; capture-to-landmark $p95 = 48.4\text{ ms}$ (target: $\le 100\text{ ms}$).
* **Enforcement:** `tools/benchmark_pipeline.py`, `camera/mediapipe_backend.py`.

---

### DEC-20: Vectorized NumPy DTW Accepted; Numba Rejected
* **Status:** Accepted (Validated in Milestone 0)
* **Context:** §12.1 requires Sakoe-Chiba band-limited DTW to run in $\le 5\text{ ms}$ per comparison and $\le 20\text{ ms}$ per segment for 10 gestures, posing an open question whether `numba` is required.
* **Decision:** Reject `numba`. Retain pure vectorized NumPy implementation with precomputed pairwise coordinate distance matrix.
* **Benchmark Evidence:** 45x45 sequence with 10 features achieved $p50 = 0.48\text{ ms}$, $p95 = 0.50\text{ ms}$ per comparison; batch of 10 templates runs in $\sim 5.0\text{ ms}$ (target: $\le 20\text{ ms}$).
* **Reason:** Pure NumPy is 10x faster than the required ceiling without introducing LLVM compiler dependencies, complex packaging wheels, or JIT warm-up latency.
* **Enforcement:** `tools/benchmark_pipeline.py`, `gestures/dynamic_matcher.py`.

---

### DEC-21: DSHOW Confirmed as Primary VideoCapture Backend on Windows
* **Status:** Accepted (Validated in Milestone 0)
* **Context:** Testing OpenCV camera backends (`CAP_DSHOW` vs `CAP_MSMF`) on Windows 10/11.
* **Decision:** Use `cv2.CAP_DSHOW` as default backend with automatic fallback to `cv2.CAP_MSMF`.
* **Benchmark Evidence:** Probing index 0 demonstrated `DSHOW` initialized in 844.5 ms vs `MSMF` at 980.1 ms; both cleanly deliver 640x480 BGR frames without driver errors.
* **Enforcement:** `app/config.py`, `camera/opencv_backend.py`.

---

### DEC-22: Native 64-bit Win32 SendInput and RegisterHotKey Primitives Validated
* **Status:** Accepted (Validated in Milestone 0)
* **Context:** Ensuring input synthesis and emergency global stop hotkeys function reliably under 64-bit Windows ctypes without third-party dependencies.
* **Decision:** Implement direct Win32 `RegisterHotKey(Ctrl+Alt+Shift+X)` and `SendInput` using `ctypes.Structure` with explicit 40-byte 64-bit union layout.
* **Benchmark Evidence:** `RegisterHotKey` succeeded immediately with error code 0; `INPUT` struct size matched exactly 40 bytes.
* **Reason:** Native 64-bit ABI alignment requires precise struct sizing; avoids runtime memory corruption or ctypes pointer truncation.
* **Enforcement:** `tools/benchmark_pipeline.py`, `adapters/windows/global_hotkey.py`, `adapters/windows/desktop_actions.py`.

---

### DEC-23: Isolated Win32 Message Pump for Stop Hotkey & Session Events
* **Status:** Accepted (Validated in Milestone 2)
* **Context:** The emergency stop hotkey and session lock events must fire instantaneously even if the main PySide6 UI thread is hung, minimized, or out of focus.
* **Decision:** Run dedicated hidden Win32 message pump threads (`GetMessageW`) for `RegisterHotKey` and `WTSRegisterSessionNotification`.
* **Reason:** Guarantees that stop signals execute in $O(1)$ directly closing the `ExecutionGate` without waiting on Qt's event loop.
* **Enforcement:** `adapters/windows/global_hotkey.py`, `adapters/windows/session_events.py`.

---

### DEC-24: Single-Slot Frame Mailbox with Monotonic Grab Timestamps
* **Status:** Accepted (Validated in Milestone 2)
* **Context:** Video frames can arrive faster than tracking can process, risking queue buildup and stale frame latency.
* **Decision:** In LIVE and TEST modes, capture writes into a single-slot `LatestFrameMailbox` that overwrites older unconsumed frames, recording exact `time.monotonic_ns()` at grab time. In RECORDING mode, frames route to a bounded 300-frame lossless queue.
* **Reason:** Prevents stale action triggers, eliminates latency accumulation, and bounds memory usage to zero queue growth.
* **Enforcement:** `camera/frame_types.py`, `camera/capture_worker.py`.

---

### DEC-25: Mean Landmark Deviation (MLD) in Normalized Palm Units for Static Pose Matching
* **Status:** Accepted (Validated in Milestone 3)
* **Context:** Static gestures must be matched invariantly to hand distance, camera zoom, hand size, and screen resolution, while preserving hand orientation (e.g. distinguishing Thumbs Up from Thumbs Down).
* **Decision:** Metric world landmarks are normalized by translating the wrist (landmark 0) to origin and scaling all 3D coordinates by the palm unit ($\|L_9 - L_0\|_2$). The wrist (now [0, 0, 0]) is dropped, leaving 20 landmarks (60 values). Static distance is computed as the Mean Landmark Deviation (MLD) across the 20 landmarks: $\text{MLD}(a, b) = \frac{1}{20} \sum_{i=1}^{20} \|a_i - b_i\|_2$.
* **Reason:** Palm units provide scale-invariant units of measure with intuitive physical meaning. Orientation is preserved because rotation-invariant matching would falsely conflate opposing gestures.
* **Enforcement:** `gestures/normalizer.py`, `gestures/feature_extractor.py`, `gestures/static_matcher.py`.

---

### DEC-26: Margin Ratio Test for Ambiguity Rejection
* **Status:** Accepted (Validated in Milestone 3)
* **Context:** If a hand pose is close to two different recorded gestures, choosing the best match by distance alone risks false classification.
* **Decision:** Enforce a margin ratio test: the best candidate gesture $g_1$ is accepted if and only if $d_1 \le \text{effective\_threshold}(g_1)$ and $(g_2 \text{ is None or } d_1 / \max(d_2, 10^{-6}) \le \text{margin\_ratio})$ where default `margin_ratio` is 0.80.
* **Reason:** Rejects borderline or ambiguous poses as `AMBIGUOUS_MARGIN` instead of triggering unexpected actions.
* **Enforcement:** `gestures/static_matcher.py`, Section 7.4.

---

### DEC-27: Dynamic Threshold Calibration with Slack Clamps [0.06, 0.30]
* **Status:** Accepted (Validated in Milestone 3)
* **Context:** Hardcoding fixed thresholds fails because some hand poses have higher natural intra-user variance than others.
* **Decision:** Thresholds are dynamically derived at load time from recorded sample observations: for each sample $i$, compute $r_i = \min_{j \neq i} \text{MLD}(\text{sample}_i, \text{sample}_j)$; then $\text{base} = \text{clamp}(1.5 \times p95(r), 0.06, 0.30)$. Effective threshold is $\text{base} \times \text{global\_sensitivity} \times \text{gesture.threshold\_scale}$.
* **Reason:** Adapts automatically to the stability of the user's recorded poses while clamping to prevent overly permissive or impossibly strict thresholds.
* **Enforcement:** `gestures/calibration.py`, `gestures/template_loader.py`.

---

### DEC-28: Single Component Ownership of Time-Based Cooldowns via TriggerValidator
* **Status:** Accepted (Validated in Milestone 3)
* **Context:** Avoiding timing discrepancies between Test mode and Live mode, and preventing repeated triggers from held hand poses.
* **Decision:** `TriggerValidator` is the sole owner of all time-based stability accumulation (400 ms), tracking gap tolerance (120 ms), per-gesture cooldowns (1500 ms), rearming release (300 ms), and global event intervals (500 ms). It runs identically in Test and Live modes using monotonically increasing frame timestamps injected via the `Clock` port. Hand speed is smoothed with an 80 ms time-constant exponential moving average (EMA) filter.
* **Reason:** Ensures deterministic behavior in tests, prevents held poses from repeatedly firing actions, and guarantees Test mode accurately previews Live mode behavior.
* **Enforcement:** `gestures/trigger_validator.py`, `gestures/recognition_engine.py`, Criterion AC-06.
