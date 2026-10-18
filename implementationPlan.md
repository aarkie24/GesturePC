# Gesture PC — Detailed Implementation Plan

> **Purpose:** Build a customizable Windows desktop automation
> application in which users record static or dynamic hand gestures,
> assign configurable workflows to them, test recognition without
> executing actions, and run those workflows in real time.
>
> **Status:** Architecture and implementation plan (revision 2). This
> document describes the intended design; it is not a claim that the
> application has already been implemented.
>
> **Revision 2 summary:** resolves the revision-1 audit findings —
> contradictions between the diagram, rules and flows; open "either/or"
> decisions; missing recognition, concurrency and Windows-specific
> detail; and the absence of measurable targets. Every tunable value
> now has a default in [Appendix A](#appendix-a--default-parameters).

------------------------------------------------------------------------

## 0. How to read this document

**Normative language.** MUST / MUST NOT / SHOULD / MAY are used in the
RFC 2119 sense. A statement using MUST is a testable requirement.

**Numeric values.** Every number in this document is an *initial
default*, collected in Appendix A, unless it is explicitly marked
**hard limit**. Initial defaults are hypotheses: Milestone 0 validates
the performance ones and Milestone 8 validates the accuracy ones. A
changed default MUST be changed in Appendix A first.

**Glossary.** These terms have exactly one meaning throughout.

| Term | Meaning |
|---|---|
| **Mode** | One of `STOPPED`, `RECORDING`, `TEST`, `LIVE` (§4). UI labels: Stopped, Recording, Test mode, Live Automation. |
| **Test mode** | `TEST`. Camera and recognition run; nothing is ever executed. Also called "recognition-only mode". |
| **Live mode** | `LIVE`. Recognized gestures may execute workflows. Also called "automation mode". |
| **Gesture** | A named, user-recorded pattern. Type `STATIC` (a held pose) or `DYNAMIC` (a movement). |
| **Sample** | One recorded observation of a gesture, stored as raw tracker landmarks (§9). |
| **Palm unit** | Distance between wrist (landmark 0) and middle-finger MCP (landmark 9). All distances are expressed in palm units so they are independent of hand size and camera distance. |
| **FrameAnalysis** | Per-frame diagnostic record produced by the recognition engine (best candidate, distance, rejection reason, trigger state). UI-only; never executes anything. |
| **RecognitionEvent** | An *accepted trigger*: a gesture that passed matching **and** trigger validation (stability, cooldown, rearming). The only recognition output that can lead to execution. |
| **Workflow** | An ordered list of validated actions attached to one gesture, optionally restricted to one application. |
| **Default workflow** | A workflow whose `context_app_id` is empty. |
| **App-specific workflow** | A workflow whose `context_app_id` names one application. |
| **Context** | Snapshot of the foreground application at the moment a trigger is accepted (`AppContext`). |
| **Snapshot** | An immutable, validated, in-memory copy of templates or workflows that is swapped atomically (§3.4). |
| **Epoch / Admission** | A counter owned by the `ExecutionGate`. An admission is valid only while its epoch is current (§4.4). |

------------------------------------------------------------------------

## 1. Product goals

The finished application MUST let a user:

1.  View a live camera feed with a hand-landmark overlay.
2.  Register a **static** gesture by capturing a stable hand pose.
3.  Register a **dynamic** gesture by recording a movement
    (at least 3 repetitions, §7.5).
4.  Name, review, enable, disable, **rename, re-record** (replace the
    samples while keeping attached workflows), adjust per-gesture
    sensitivity, and **delete** (with confirmation; cascades to its
    workflows) registered gestures.
5.  Select a saved gesture in a separate Workflow Studio and assign one
    or more ordered actions.
6.  Change a workflow without re-recording its gesture.
7.  Test the real recognition engine in **Test mode**, which never
    executes workflows, and **dry-run** any workflow (validate it and
    render a step-by-step description) without touching the desktop.
8.  Run the application in **Live mode**, where recognized gestures
    trigger enabled workflows.
9.  Optionally select different workflows based on the foreground
    application.
10. View recognition and execution history, change settings, and stop
    automation immediately from anywhere on the desktop (§4.5).

### Non-goals for the first release

-   Training a neural network from scratch.
-   Arbitrary user-provided code or shell commands as workflow actions.
-   Cloud accounts or cloud synchronization.
-   Multi-user identification, two-hand gestures, or processing more than
    one hand per frame.
-   Rotation-invariant matching, and left/right mirroring of templates
    (§7.2–7.3 define the exact behavior).
-   Absolute-pixel mouse coordinates, GPU acceleration, non-Windows
    platforms.
-   Manually running a workflow outside a recognized trigger ("Run now").
    Dry-run only in v1.
-   Workflow/gesture import and export between machines.
-   Predicting future gestures or automatically preparing workspaces.
    Keep the architecture extensible for these later, but do not let
    them delay the first usable release.

## 2. Technology stack

| Area | Choice | Responsibility |
|---|---|---|
| Language | Python 3.11 | Application and runtime logic |
| Desktop UI | PySide6 / Qt 6 (per-monitor DPI aware) | Main window, tabs, forms, preview, tray icon, LIVE overlay |
| Camera | `opencv-python-headless` | Frame capture. The *headless* build avoids bundling a second Qt that can conflict with PySide6; nothing uses `cv2.imshow`. |
| Hand tracking | MediaPipe **Tasks API** `HandLandmarker`, `VIDEO` running mode | Synchronous per-frame landmark extraction on the recognition thread. The legacy `mp.solutions.hands` API is **not** used. |
| Tracker model | `assets/models/hand_landmarker.task`, bundled | Loaded from disk; SHA-256 verified at startup; the app never downloads models at runtime. |
| Numerical operations | NumPy | Normalization, distances, hand-written banded DTW. If profiling in M0 shows DTW above its budget (Appendix A), `numba` MAY be adopted as an optional accelerated path with an identical NumPy fallback. |
| Static matching | Normalized world-landmark vectors + nearest-template distance + margin test | §7.4 |
| Dynamic matching | Motion-segmented, resampled feature sequences + banded DTW | §7.5 |
| Validation schemas | Pydantic v2 (strict models) | Action parameter schemas (also drive Workflow Studio forms) and settings validation. Domain objects stay plain frozen dataclasses. |
| Persistence | SQLite via `sqlite3`, WAL mode | Gestures, samples, workflows, settings, logs (§9) |
| App-data location | `platformdirs` | `%LOCALAPPDATA%\GesturePC`; overridable with `GESTUREPC_DATA_DIR` for development and tests |
| Windows integration | `pywin32` + `ctypes` (`SendInput`, `RegisterHotKey`) | Window management, foreground-window info, input synthesis, global hotkey, session lock/sleep notifications. **PyAutoGUI is not a dependency**: it duplicates pywin32 capability, carries global failsafe/pause state, and adds nothing the adapter needs. If the `SendInput` wrapper proves costly, PyAutoGUI MAY be used *behind the same `DesktopActionAdapter`* with `FAILSAFE=True` and `PAUSE=0`. |
| Process information | `psutil` | Executable name/path for a process ID |
| Testing | `pytest`, `pytest-qt` (offscreen), `hypothesis` | Unit, property, integration, UI-smoke and architecture tests |
| Packaging (later) | PyInstaller | Optional Windows executable; MediaPipe + Qt bundling is evaluated after v1, not assumed |

**Dependency policy.** Milestone 0 verifies that the chosen MediaPipe
version provides a Python 3.11 Windows wheel and the Tasks `HandLandmarker`
API. Exact versions are then pinned in `requirements.txt` (runtime) and
`requirements-dev.txt` (test/dev). No dependency is added without
updating the stack table.

**Network policy.** The application MUST NOT make network requests.
Enforced by an architecture test (§15.4).

------------------------------------------------------------------------

## 3. Architecture and data flow

The application is separated into UI, application services, domain
logic (recognition and workflows), infrastructure adapters and
persistence. One shared camera/recognition pipeline feeds an
`EventSink`; the active runtime mode decides which sink receives
events, and only the Live sink can reach execution.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ PySide6 UI  (main thread only: no recognition, no desktop actions)           │
│ Live Monitor | Gesture Studio | Workflow Studio | Testing Studio | Settings  │
│ Persistent status bar, Stop button, LIVE overlay, system-tray Stop           │
└──────────────────────────────────────────────────────────────────────────────┘
      │
      ▼ commands down / immutable events up (QtBridge)
┌──────────────────────────────────────────────────────────────────────────────┐
│ Application services  (services/)                                            │
│ GestureService  WorkflowService  ConfigurationService  SnapshotService       │
│ RuntimeController  ExecutionGate  EventBus  EventLogger                      │
└──────────────────────────────────────────────────────────────────────────────┘
      │
      ▼ start/stop pipeline, select EventSink, publish snapshots
┌──────────────────────────────────────────────────────────────────────────────┐
│ Camera + Recognition pipeline  (shared by TEST and LIVE: one code path)      │
│ Capture thread:     CameraBackend -> frames (latest-frame mailbox)           │
│ Recognition thread: HandTracker -> HandSelector -> Normalizer ->             │
│                     Static/Dynamic matchers -> TriggerValidator              │
│ Emits FrameAnalysis (every frame) and RecognitionEvent (accepted only).      │
│ The engine never executes workflows and never imports workflows.*            │
└──────────────────────────────────────────────────────────────────────────────┘
      │
      ▼ EventSink chosen from the current mode
┌──────────────────────────────────────────────────────────────────────────────┐
│ Runtime mode policy  (RuntimeController picks the sink; gate enforces)       │
│ STOPPED / RECORDING / TEST  ->  DiagnosticSink                               │
│     UI + log only. Holds NO reference to the gate, dispatcher or executor.   │
│     May call the pure WorkflowPreview to *describe* what would run.          │
│ LIVE  ->  LiveSink                                                           │
│     1 ExecutionGate.admit()   2 capture AppContext   3 WorkflowResolver      │
│     4 rate limit check        5 ExecutionDispatcher.submit()                 │
└──────────────────────────────────────────────────────────────────────────────┘
      │
      ▼ LIVE only: ExecutionRequest + immutable workflow snapshot
┌──────────────────────────────────────────────────────────────────────────────┐
│ Execution thread  (single worker; one workflow at a time)                    │
│ WorkflowExecutor -> Action (from ActionRegistry) -> DesktopActionAdapter     │
│ Re-checks gate epoch + cancellation token before EVERY action.               │
└──────────────────────────────────────────────────────────────────────────────┘
      │
      ▼ ports (domain/ports.py) implemented by adapters/windows/*
┌──────────────────────────────────────────────────────────────────────────────┐
│ Windows adapters  (the only code that touches the OS)                        │
│ pywin32 / ctypes SendInput / RegisterHotKey / session notifications          │
└──────────────────────────────────────────────────────────────────────────────┘

SQLite repositories persist gestures, samples, workflows, settings and logs.
A dedicated log-writer thread performs all event-log inserts.
```

### 3.1 Architectural rules

Each rule is a testable requirement; §15.4 lists the architecture tests
that enforce the import-related ones.

| # | Rule |
|---|---|
| R1 | **UI code never performs recognition or desktop actions.** `ui/` MUST NOT import `workflows.workflow_executor`, `workflows.execution_dispatcher`, `adapters.*`, `win32*`, `sqlite3`, or `cv2`. |
| R2 | **The recognition engine never executes workflows.** `gestures/` and `camera/` MUST NOT import `workflows.*`, `services.*` or `adapters.*`. They only emit `FrameAnalysis` and `RecognitionEvent`. |
| R3 | **Test mode and Live mode use the same recognition engine, code path and loaded templates.** The only difference is which `EventSink` receives the output. |
| R4 | **Only `LiveSink` may call `ExecutionGate.admit()` and `ExecutionDispatcher.submit()`.** `DiagnosticSink`'s module has no import path to the gate, dispatcher, executor or adapters. |
| R5 | Workflow actions are selected from the trusted `ActionRegistry`. Database content is configuration, never code: no `eval`, `exec`, `pickle`, dynamic imports from data, or `shell=True`. |
| R6 | Camera capture, recognition, workflow execution, log writes and OS-event handling MUST NOT run on the UI thread. |
| R7 | Dependencies are injected by the composition root (`app/application.py`). No module-level mutable state, no circular imports. |
| R8 | Data crossing threads is immutable: frozen dataclasses, read-only NumPy arrays (`writeable=False`), or copies. Camera frames are copied at most once, for the preview. |
| R9 | Only `adapters/windows/` imports `pywin32`, Windows `ctypes` APIs or `psutil`. Everything else depends on ports in `domain/ports.py`. |
| R10 | Only `database/` imports `sqlite3`. |
| R11 | The application makes no network requests. |
| R12 | Every mode change goes through `RuntimeController`. No other component sets the mode, opens the gate or swaps the sink. |

### 3.2 Threads and ownership

| Thread | Owns | Consumes → produces | Must never |
|---|---|---|---|
| **UI (main)** | Widgets, `QtBridge` slots | UI events → commands to services | Block on camera, matching, execution, migrations or long queries. Heavy service calls (snapshot rebuild, migrations) run on a `QThreadPool` worker and report by signal. |
| **Capture** | `cv2.VideoCapture` (single owner, §6 `camera_manager`) | Camera → latest-frame mailbox (live) or lossless queue (recording) | Run matching or touch the database |
| **Recognition** | `HandLandmarker`, matchers, trigger-validator state, the current `TemplateSnapshot` reference | Frames → `FrameAnalysis`, `RecognitionEvent` → current `EventSink` | Call workflows, adapters, SQLite or Qt widgets |
| **Execution** | All `DesktopActionAdapter` calls; COM initialized with `pythoncom.CoInitialize()` at thread start | `ExecutionRequest` → `ExecutionResult` | Run more than one workflow at a time |
| **Log writer** | The write connection for `event_logs` | Log records (queue) → batched inserts | Block producers (queue is bounded; overflow drops the oldest *diagnostic* record and counts the loss, never an execution record) |
| **OS events** | A hidden message-only window: `RegisterHotKey`, session lock/unlock, sleep/resume notifications | OS messages → `RuntimeController.emergency_stop()` / mode events | Depend on the UI event loop |

SQLite connections are created per thread through a connection factory.
A connection is never shared across threads.

Python's GIL is not expected to limit the pipeline: MediaPipe inference
and NumPy kernels release it. If M0/M8 profiling shows recognition
contention, moving recognition to a `multiprocessing` worker is a
documented fallback, not part of v1.

### 3.3 Frame handling and backpressure

-   **Live path:** a single-slot "latest frame" mailbox. A newer frame
    replaces an unprocessed older one *before* tracking. Every frame
    carries `capture_ts_ns` (`time.monotonic_ns()` at grab time), so
    dropped frames reduce temporal resolution but never distort time.
    Dynamic matching resamples by timestamp (§7.5).
-   **Recording path:** a lossless bounded queue (300 frames). Frames are
    never silently dropped; overflow or an effective rate below
    `min_effective_fps` rejects the recording as `LOW_FPS`.
-   **HandLandmarker timestamps** must be strictly increasing
    milliseconds: `ts_ms = max(prev_ts_ms + 1, capture_ts_ns // 1_000_000)`.
-   **UI delivery:** preview frames are copied once and capped at
    `preview_fps`; `FrameAnalysis` is coalesced to 15 Hz (latest wins).
    `RecognitionEvent`, mode changes and execution results are never
    coalesced or dropped.

### 3.4 Snapshots and configuration changes

-   `SnapshotService` builds a **`TemplateSnapshot`** (enabled gestures
    whose samples are valid, with derived features and calibrated
    thresholds) and a **`WorkflowSnapshot`** (enabled, validated
    `WorkflowDefinition` objects indexed by `(gesture_id, context)`)
    on a worker thread after a debounced `ConfigChanged` event (100 ms).
-   Snapshots are published by an atomic reference swap
    (`SnapshotHolder`, lock-protected). Readers take the reference once
    per frame or per trigger and never see a half-built snapshot.
-   Items that fail validation are *excluded* and listed in a
    `SnapshotReport`; the UI shows them as "Needs re-recording" or
    "Invalid workflow: reason". They are never used silently.
-   A template swap resets trigger-validator state only for gestures
    that were removed or changed.
-   An `ExecutionRequest` carries the **immutable `WorkflowDefinition`
    resolved at admission**. Editing the workflow afterwards affects only
    later triggers. A workflow that is disabled or deleted while queued
    is skipped at dequeue (`SKIPPED_WORKFLOW_DISABLED`); one already
    running continues until it ends or the user stops automation.

### 3.5 Events

`services/event_bus.py` is a small typed publish/subscribe bus.
Subscribers MUST NOT block. Event types: `FrameAnalysis`,
`RecognitionEvent`, `ExecutionStarted`, `ExecutionFinished`,
`RuntimeStatusChanged` (mode, reason), `ConfigChanged` (kind),
`SnapshotPublished` (with `SnapshotReport`), `PipelineError`.
`ui/qt_bridge.py` converts bus events to Qt signals (queued
connections), so the UI never holds a reference to a service thread's
mutable state.

------------------------------------------------------------------------

## 4. Runtime modes and the safety boundary

`RuntimeController` (with `ExecutionGate`) is the only safety boundary
between recognition and execution. The policy is enforced in code and
by tests, never merely by hiding or disabling UI buttons.

### 4.1 Mode definitions

| Mode | Camera | Tracking | Matching + trigger validation | Sink | Gate | Desktop actions |
|---|---|---|---|---|---|---|
| `STOPPED` | off | off | off | — | closed | never |
| `RECORDING` | on (lossless queue) | on | **off** | `DiagnosticSink` | closed | never |
| `TEST` | on | on | on | `DiagnosticSink` | closed | never |
| `LIVE` | on | on | on | `LiveSink` | open | yes |

Application launch always starts in `STOPPED`, including after a crash
or unexpected restart. The only launch preference is `STOPPED` or
`TEST` (never `LIVE`).

### 4.2 Transition table

| From → To | Allowed | Conditions |
|---|---|---|
| `STOPPED` → `TEST` | yes | User clicks Start Test; camera available |
| `STOPPED` → `LIVE` | yes | User clicks Start Live Automation; §4.3 preconditions |
| `STOPPED` → `RECORDING` | yes | User starts a recording in Gesture Studio |
| `TEST` → `STOPPED` | yes | User stops, or error |
| `TEST` → `LIVE` | yes | Same preconditions and confirmation as above; pipeline keeps running; trigger-validator state is reset |
| `TEST` → `RECORDING` | yes | Test ends; recording starts |
| `LIVE` → `STOPPED` | yes | Any stop mechanism (§4.5) or automatic exit (§4.3) |
| `LIVE` → `TEST` | yes | Gate closes first; queued work is cancelled |
| `LIVE` → `RECORDING` | yes | **Only after a confirmation dialog** ("Recording stops Live Automation"); implemented as `LIVE → STOPPED → RECORDING` |
| `RECORDING` → `STOPPED` | yes | Recording finished, cancelled or failed. A recording **always returns to `STOPPED`**; Live never resumes automatically |
| `RECORDING` → `TEST` / `LIVE` | no | Must pass through `STOPPED` |
| any → `STOPPED` | yes | Emergency stop (always honored) |
| same → same | no-op | |

Any other transition raises `InvalidModeTransition`. A table-driven test
covers every cell (§15).

### 4.3 Entering and leaving Live mode

**Entry preconditions (all MUST hold, otherwise the user sees the
specific failing condition):**

1.  The user explicitly clicked Start Live Automation (no implicit entry).
2.  The camera is open and delivering frames.
3.  The global stop hotkey is registered. If registration fails (key
    already taken), Live mode is refused until the user chooses another
    hotkey in Settings.
4.  Settings validate; template and workflow snapshots are built.
5.  At least one enabled gesture has at least one enabled, valid
    workflow (otherwise there is nothing to run).
6.  The Windows session is unlocked and the execution thread is healthy.
7.  On the first Live entry after each application launch, a
    confirmation dialog states how many workflows are enabled, whether
    any contain elevated-risk actions (§8.4), and the stop hotkey.

**Automatic exits to `STOPPED`** (each logged with a visible reason;
never auto-resumed):

-   Stop hotkey, tray menu, LIVE overlay or main-window Stop.
-   Windows session lock, disconnect, sleep.
-   Camera lost, or no `FrameAnalysis` for `pipeline_stall_ms`
    (prevents acting on stale frames).
-   More than `max_executions_per_minute` accepted executions
    (runaway protection).
-   `consecutive_failure_limit` workflows in a row ending in failure.
-   Execution thread wedged (§4.5) or unhandled recognition-thread
    exception.
-   Application shutdown.

### 4.4 ExecutionGate

```text
open_for_live()   epoch += 1; new CancellationToken; open = True
close(reason)     open = False; epoch += 1; token.cancel()
admit()           -> Admission(epoch, token) if open else None
is_current(adm)   -> open and adm.epoch == epoch and not token.cancelled
```

-   All operations execute under one lock; `close()` is O(1), performs no
    I/O and is callable from any thread (including the OS-event thread).
-   An `Admission` is obtained once per accepted trigger by `LiveSink`.
-   `is_current` is checked at **three points**: when the dispatcher
    accepts the request, when the executor dequeues it, and **before
    every action**. This removes the check-then-act window between
    "still LIVE" and "action runs".

### 4.5 Stopping automation

| Mechanism | Detail |
|---|---|
| **Global hotkey** | Default `Ctrl+Alt+Shift+X`, configurable. Registered with `RegisterHotKey` on the OS-event thread, which calls `RuntimeController.emergency_stop()` directly — it does not depend on the UI event loop, window focus or visibility. |
| **LIVE overlay** | Small always-on-top frameless window with a Stop button, shown whenever the mode is `LIVE`, even if the main window is minimized. |
| **Tray icon** | `QSystemTrayIcon` with a Stop action and the current mode in its tooltip. |
| **Main window** | A Stop button in the persistent status bar, visible on every tab. |
| **Automatic exits** | §4.3. |

`emergency_stop()` order of operations: (1) `gate.close()` — from this
instant no new admission or action can start; (2) cancel and clear the
dispatcher queue (100 % of queued work); (3) set mode `STOPPED` and stop
the pipeline.

**In-flight work.** Actions are classified in the registry:
*atomic* actions are single OS calls bounded by design (≤ 250 ms) and
complete; *interruptible* actions (`delay`) poll the cancellation token
every 50 ms. Remaining actions are skipped with status `CANCELLED`.
"Where possible" in revision 1 therefore means exactly this.

**Wedged execution thread.** If a workflow exceeds
`workflow_watchdog_ms`, or the executor does not return within 2 s of
cancellation, the thread is abandoned (daemon), the controller goes to
`STOPPED` with an error, and a fresh execution thread is created before
the next Live entry. Window-moving calls use `SWP_ASYNCWINDOWPOS` so a
hung target window cannot block the executor.

**Target:** hotkey press to gate closed ≤ 100 ms at p95 (§12.3).

### 4.6 Enforcing "Test mode never executes" (defense in depth)

1.  **Wiring.** In every non-Live mode the recognition output goes to
    `DiagnosticSink`. The dispatcher, executor and adapters are
    constructed by the composition root and handed **only** to
    `LiveSink`. `DiagnosticSink` can describe what would run through the
    pure `WorkflowPreview` function, which returns names and text, never
    an executable object.
2.  **Gate.** `ExecutionDispatcher.submit()` requires a valid
    `Admission`, obtainable only while the gate is open, i.e. in `LIVE`.
3.  **Tests.** (a) An import-graph test proves `diagnostic_sink`, `ui/`,
    `gestures/` and `camera/` have no path to executor/dispatcher/gate/
    adapters (R1, R2, R4). (b) An integration test runs the full
    pipeline in `TEST` against a spy adapter and asserts zero adapter
    calls. (c) A fault-injection test attaches `LiveSink` while the gate
    is closed and asserts zero executions.

------------------------------------------------------------------------

## 5. Repository structure

```text
gesture-pc/
├── main.py
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── README.md
├── implementationPlan.md
├── .gitignore
│
├── assets/
│   └── models/
│       ├── hand_landmarker.task
│       └── MODEL_SHA256.txt
│
├── app/
│   ├── __init__.py
│   ├── application.py          # composition root
│   ├── config.py               # SettingsSchema (defaults, ranges, validation)
│   ├── constants.py
│   ├── logging_config.py
│   └── paths.py                # app-data dir, single-instance lock path
│
├── domain/                     # no Qt, SQLite, OpenCV or Windows imports
│   ├── __init__.py
│   ├── models.py
│   ├── events.py
│   ├── enums.py
│   ├── exceptions.py
│   └── ports.py                # Protocols implemented by adapters/camera
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py
│   ├── qt_bridge.py
│   ├── tray.py
│   ├── styles.py
│   ├── view_models.py
│   ├── components/
│   │   ├── camera_view.py
│   │   ├── status_badge.py
│   │   ├── event_table.py
│   │   ├── live_overlay.py
│   │   └── action_card.py
│   └── tabs/
│       ├── live_monitor_tab.py
│       ├── gesture_studio_tab.py
│       ├── workflow_studio_tab.py
│       ├── testing_tab.py
│       └── settings_tab.py
│
├── camera/
│   ├── __init__.py
│   ├── camera_manager.py
│   ├── capture_worker.py
│   ├── opencv_backend.py       # CameraBackend implementation
│   ├── hand_tracker.py
│   ├── mediapipe_backend.py    # HandTrackerBackend implementation
│   └── frame_types.py
│
├── gestures/
│   ├── __init__.py
│   ├── hand_selector.py
│   ├── normalizer.py
│   ├── feature_extractor.py
│   ├── resampler.py
│   ├── segmenter.py
│   ├── recorder.py
│   ├── recording_validator.py
│   ├── calibration.py          # thresholds + registration collision check
│   ├── static_matcher.py
│   ├── dynamic_matcher.py
│   ├── recognition_engine.py
│   ├── trigger_validator.py
│   └── template_loader.py
│
├── workflows/
│   ├── __init__.py
│   ├── workflow_resolver.py    # pure function
│   ├── workflow_preview.py     # pure function (dry-run / "would run")
│   ├── workflow_executor.py
│   ├── execution_dispatcher.py
│   ├── action_registry.py
│   ├── action_context.py
│   └── actions/
│       ├── __init__.py
│       ├── base.py
│       ├── window_actions.py
│       ├── application_actions.py
│       ├── keyboard_actions.py
│       ├── mouse_actions.py
│       └── utility_actions.py
│
├── context/
│   ├── __init__.py
│   └── active_application.py
│
├── services/
│   ├── __init__.py
│   ├── gesture_service.py
│   ├── workflow_service.py
│   ├── configuration_service.py
│   ├── snapshot_service.py
│   ├── runtime_controller.py
│   ├── execution_gate.py
│   ├── diagnostic_sink.py      # TEST / RECORDING / STOPPED sink
│   ├── live_sink.py            # LIVE sink (only path to execution)
│   ├── event_bus.py
│   └── event_logger.py
│
├── adapters/
│   ├── __init__.py
│   └── windows/
│       ├── __init__.py
│       ├── desktop_actions.py  # DesktopActionAdapter implementation
│       ├── foreground_window.py
│       ├── global_hotkey.py
│       └── session_events.py
│
├── database/
│   ├── __init__.py
│   ├── connection.py
│   ├── codecs.py               # landmark BLOB (de)serialization
│   ├── migrator.py
│   ├── migrations/
│   │   ├── 0001_initial.sql    # the schema; single source of truth
│   │   └── README.md
│   └── repositories/
│       ├── __init__.py
│       ├── gesture_repository.py
│       ├── workflow_repository.py
│       ├── application_repository.py
│       ├── settings_repository.py
│       └── log_repository.py
│
├── tools/
│   ├── benchmark_pipeline.py   # FPS / latency / DTW cost measurement
│   ├── record_fixture.py       # capture landmark-only fixtures (no video)
│   └── evaluate_recognition.py # accuracy + false-trigger metrics
│
└── tests/                      # see §15 for the full file list
    ├── conftest.py
    ├── fakes/
    ├── fixtures/
    ├── unit/
    ├── integration/
    ├── architecture/
    └── manual/
```

Changes from revision 1: `adapters/` and `domain/ports.py` exist so
"Windows-first adapters behind interfaces" and "fake adapters in tests"
are real modules; `workflow_service.py` moved to `services/` next to
`gesture_service.py`; `execution_queue.py` became
`execution_dispatcher.py` (it admits and runs one workflow at a time; it
is not a multi-item queue); `schema.sql` was replaced by numbered
migrations; the `data/` placeholder was removed.

The database lives in the per-user application-data directory
(`%LOCALAPPDATA%\GesturePC`, or `GESTUREPC_DATA_DIR`), never in the
repository. `.gitignore` excludes `*.db`, `*.db-wal`, `*.db-shm`,
backups, logs, recordings and local settings. Do not commit user
recordings, personal paths, logs or machine-specific settings.

## 6. File-by-file responsibilities

### Root files and assets

| File | What it contains and does |
|---|---|
| `main.py` | Minimal entry point: acquire the single-instance lock, configure logging, build the application via the composition root, show the main window, shut down cleanly. No business logic. |
| `requirements.txt` | Pinned runtime dependencies (after Milestone 0 compatibility testing). |
| `requirements-dev.txt` | Pinned test/dev dependencies. |
| `pyproject.toml` | Project metadata, pytest/coverage configuration, formatting/linting settings. |
| `README.md` | Overview, demo, architecture summary, installation, camera permissions, usage, limitations, testing instructions. |
| `implementationPlan.md` | This specification. |
| `assets/models/hand_landmarker.task` | Bundled tracker model. `MODEL_SHA256.txt` holds its hash, verified at startup; a mismatch blocks the pipeline with a clear error. |

### `app/`

| File | Responsibility |
|---|---|
| `application.py` | Composition root. Constructs database, repositories, services, camera pipeline, recognition engine, gate, sinks, dispatcher/executor (given **only** to `LiveSink`) and runtime controller; injects them into the UI. Owns startup and shutdown ordering (§11-H). |
| `config.py` | `SettingsSchema`: the single source of truth for every setting — key, type, range, default, owner. Loads DB values, validates them, and falls back to the default (with a warning log) for any invalid stored value. Precedence: **schema default < validated stored value**. There are no other override layers except `gestures.threshold_scale`. |
| `constants.py` | Non-user-configurable constants: supported normalizer/feature versions, compatible tracker-model hashes, sensitive-chord list, event identifiers. |
| `logging_config.py` | Structured, rotated application logs (5 files × 1 MB) with redaction. Logs never contain frames, window titles or raw action arguments. |
| `paths.py` | Resolves the data directory, backups directory and lock-file path. |

### `domain/`

| File | Responsibility |
|---|---|
| `models.py` | Frozen dataclasses: `Gesture`, `GestureSample`, `Workflow`, `WorkflowAction`, `WorkflowDefinition` (immutable executable form), `AppContext`, `FrameAnalysis`, `RecognitionResult`, `ExecutionRequest`, `ExecutionResult`, `ActionResult`, `TemplateSnapshot`, `WorkflowSnapshot`, `SnapshotReport`. No Qt or SQLite dependency. |
| `events.py` | Bus events (§3.5) with IDs and UTC timestamps. |
| `enums.py` | `GestureType`, `Hand`, `RuntimeMode`, `RiskTier`, `ActionType`, `RejectReason`, `TriggerState`, `ExecutionStatus` (values in Appendix B). |
| `exceptions.py` | `InvalidRecording`, `DuplicateGestureName`, `InvalidWorkflow`, `InvalidModeTransition`, `CameraUnavailable`, `SnapshotInvalid`, `ActionRejected`. |
| `ports.py` | `Protocol` interfaces: `CameraBackend`, `HandTrackerBackend`, `ForegroundWindowProvider`, `DesktopActionAdapter`, `GlobalHotkeyService`, `SessionEventSource`, `Clock`, `EventSink`. Real implementations live in `adapters/` and `camera/`; fakes live in `tests/fakes/`. |

Domain model fields (stable IDs are used for every relationship; names
may change):

-   `Gesture`: `id`, `name`, `gesture_type`, `hand`, `enabled`,
    `threshold_scale`, `template_revision`, `created_at`, `updated_at`.
-   `GestureSample`: `id`, `gesture_id`, `sample_index`,
    `landmarks_image` and `landmarks_world` (`float32`, shape
    `(frames, 21, 3)`), `timestamps_ms` (dynamic only), `frame_aspect_ratio`,
    `tracker_model_id`, `preprocess` flags.
-   `Workflow`: `id`, `gesture_id`, `name`, `context_app_id` (nullable =
    default workflow), `enabled`, `risk_acknowledged_at`, timestamps.
-   `WorkflowAction`: `id`, `workflow_id`, `position`, `action_type`,
    validated `parameters` object.
-   `AppContext`: `app_id`, `pid`, `hwnd`, `is_elevated`, `captured_at`,
    `title` (in memory only; never persisted unless `log_window_titles`).

### `ui/`

| File | Responsibility |
|---|---|
| `main_window.py` | Application shell: tabs, **persistent status bar** (mode badge, camera status, hotkey status, foreground app) and an always-visible Stop button. Connects tabs to injected services. |
| `qt_bridge.py` | Converts `EventBus` events to Qt signals (queued connections). The only place UI code touches bus internals. |
| `tray.py` | System-tray icon: current mode tooltip, Stop action, show/hide window. |
| `styles.py` | Colors, spacing, fonts, reusable styles (§14.2). |
| `view_models.py` | Converts service/domain state into UI-friendly state. No matching or action logic. |
| `components/camera_view.py` | Displays preview frames and optional landmark overlay; converts to Qt images safely; never owns the camera. |
| `components/status_badge.py` | Reusable status display (mode, camera, hotkey). Always text + icon + color, never color alone. |
| `components/event_table.py` | Reusable table for recognition and execution history. |
| `components/live_overlay.py` | Always-on-top LIVE indicator with a Stop button (§4.5). |
| `components/action_card.py` | Workflow action editor card: parameter form generated from the registry's JSON schema, risk badge, reorder/remove controls. |
| `tabs/*` | Specified in §14. Tabs call application services; they never issue SQL, touch matcher internals, or call Windows APIs. `testing_tab.py` has **no dependency** on the dispatcher, executor, gate or adapters. |

### `camera/`

| File | Responsibility |
|---|---|
| `camera_manager.py` | Owns camera open/release, device probing and availability errors (`CAMERA_NOT_FOUND`, `CAMERA_BUSY`, `CAMERA_NO_FRAMES`). Guarantees a single capture owner. Tries the configured backend first, then the other (DSHOW ↔ MSMF). |
| `capture_worker.py` | Capture thread: grab frames, flip horizontally (selfie view), stamp `capture_ts_ns`, feed the latest-frame mailbox (live) or the lossless queue (recording). |
| `opencv_backend.py` | `CameraBackend` implementation over `cv2.VideoCapture`. |
| `hand_tracker.py` | Wraps a `HandTrackerBackend` and returns a typed `TrackingResult` (all detected hands, handedness + score, image and world landmarks, status). No matching, no actions. |
| `mediapipe_backend.py` | `HandTrackerBackend` implementation over the Tasks `HandLandmarker` in `VIDEO` mode (`num_hands = 2` so ambiguity can be detected). |
| `frame_types.py` | Lightweight frame/tracking structures; documents the coordinate conventions of §7.1. |

### `gestures/`

| File | Responsibility |
|---|---|
| `hand_selector.py` | Applies the `tracked_hand` setting to a `TrackingResult` and yields one `SelectedHand` or a status (`NO_HAND`, `WRONG_HAND`, `AMBIGUOUS_HANDS`). |
| `normalizer.py` | Raw landmarks → normalized representation (§7.3). `NORMALIZER_VERSION` constant. |
| `feature_extractor.py` | Normalized landmarks → static vector or dynamic per-step vector (§7.3). `FEATURE_VERSION` constant. |
| `resampler.py` | Timestamp-based linear resampling and bounded gap interpolation (§7.5). |
| `segmenter.py` | `MotionSegmenter`: detects start/end of a movement from hand speed (§7.5). Used identically by recording and live recognition. |
| `recorder.py` | Recording sessions: countdown, static burst, dynamic window with auto-stop, cancel, timeout, clean reset. Runs only in `RECORDING` mode. |
| `recording_validator.py` | Rejects recordings per the numeric rules of §7.4/§7.5 and returns actionable feedback. |
| `calibration.py` | Derives per-gesture thresholds from samples and performs the registration collision check (§7.4, §7.5). |
| `static_matcher.py` | Distance to every static template; returns best and second-best candidates with distances. Never triggers anything. |
| `dynamic_matcher.py` | Banded DTW with length pre-filter and early abandoning (§7.5). |
| `recognition_engine.py` | Orchestrates hand selection → normalization → matching → trigger validation. `process(tracking_result) -> (FrameAnalysis, RecognitionEvent | None)`. Pure with respect to the outside world: no I/O, no workflows. |
| `trigger_validator.py` | Stability, motion gating, per-gesture cooldown, global cooldown, rearming (§7.6). The **only** owner of time-based cooldown logic. |
| `template_loader.py` | Reads samples from the repository, validates versions and shapes, derives features and thresholds, and returns a `TemplateSnapshot` plus a `SnapshotReport`. |

### `workflows/`

| File | Responsibility |
|---|---|
| `workflow_resolver.py` | Pure function: `(gesture_id, AppContext, WorkflowSnapshot, settings) → Resolution` using the deterministic algorithm of §8.3. |
| `workflow_preview.py` | Pure function that validates a definition and renders an ordered, human-readable description with risk flags. Backs Workflow Studio dry-run and the Testing tab's "would run" line. Returns text, never executable objects. |
| `workflow_executor.py` | Runs a `WorkflowDefinition` sequentially with the gate/cancellation checks of §4.4, the failure policy of §8.6 and a watchdog. No recognition or UI code. |
| `execution_dispatcher.py` | Admission control for execution: validates the `Admission`, applies the overlap policy (`DROP_WHILE_BUSY`), request TTL and rate limit, and hands the request to the single execution thread. |
| `action_registry.py` | Registers action implementations with their Pydantic parameter models, risk tier and interruptibility. Rejects unknown types and invalid parameters. `describe()` exposes labels and JSON schemas to the UI. |
| `action_context.py` | Controlled runtime context for actions: cancellation token, logger, `AppContext` snapshot, the `DesktopActionAdapter` port and nothing else. |
| `actions/base.py` | Action interface: `ParamsModel`, `risk_tier`, `interruptible`, `validate(params)`, `execute(ctx, params) → ActionResult`. |
| `actions/window_actions.py` | `window_state` (maximize/minimize/restore), `snap_window` (left/right). |
| `actions/application_actions.py` | `launch_application` using an `app_ref` from the approved-applications list; arguments as a list; never a shell string. |
| `actions/keyboard_actions.py` | `send_shortcut` (validated key vocabulary; sensitive chords need per-action acknowledgement) and `media_key`. |
| `actions/mouse_actions.py` | `mouse_click` (relative targets only) and `scroll`. |
| `actions/utility_actions.py` | `delay` (interruptible, 50–10 000 ms). |

Actions contain **no OS calls**; they call the `DesktopActionAdapter`
port, which is why automated tests can run every action against a fake.

### `context/`

| File | Responsibility |
|---|---|
| `active_application.py` | Uses the `ForegroundWindowProvider` port to produce an `AppContext` with a normalized `app_id` (§8.2). Handles inaccessible, elevated and transient windows by returning `app_id = "unknown"` plus a reason, never raising into the pipeline. |

### `services/`

| File | Responsibility |
|---|---|
| `gesture_service.py` | Gesture registration, name validation (case-insensitive unique), recording results, collision check, re-record (transactional sample replacement, `template_revision += 1`), rename, enable/disable, sensitivity, delete (cascade after confirmation). Emits `ConfigChanged`. |
| `workflow_service.py` | Workflow CRUD and validation: referenced gesture exists, unique (gesture, context), actions valid, limits respected (§8.5), risk acknowledgement set/cleared (§8.4). Replaces a workflow's action list as a single transaction. |
| `configuration_service.py` | Reads/writes settings through `SettingsSchema`, publishes `ConfigChanged`. Also manages the approved-applications list (refuses to delete one still referenced by a workflow). |
| `snapshot_service.py` | Builds and publishes template/workflow snapshots (§3.4). |
| `runtime_controller.py` | Owns the mode state machine (§4.2), preconditions and automatic exits (§4.3), starts/stops the pipeline, selects the sink, drives `ExecutionGate`, and implements `emergency_stop()`. **The only component that changes mode** (R12). |
| `execution_gate.py` | The gate of §4.4. |
| `diagnostic_sink.py` | Sink for non-Live modes: publishes `FrameAnalysis` and `RecognitionEvent` to the bus and logger, and may attach a `WorkflowPreview` text. No imports of dispatcher/executor/gate/adapters. |
| `live_sink.py` | Sink for Live mode, steps 1–5 of the §11-E flow. The only caller of `ExecutionGate.admit()` and `ExecutionDispatcher.submit()`. |
| `event_bus.py` | Typed pub/sub (§3.5). |
| `event_logger.py` | Bounded queue to the log-writer thread; retention pruning; verbose-recognition logging is off by default and rate-limited to 5 rows/s. |

### `adapters/windows/`

| File | Responsibility |
|---|---|
| `desktop_actions.py` | `DesktopActionAdapter`: window placement (`SetWindowPos` with `SWP_ASYNCWINDOWPOS`, work-area math per monitor), `SendInput` keyboard/mouse, process launch (`subprocess.Popen`, `shell=False`), elevation check of the target window. |
| `foreground_window.py` | `ForegroundWindowProvider`: foreground `hwnd`, `pid`, executable name, elevation flag, optional title; resolves the real app behind `ApplicationFrameHost.exe` where possible. |
| `global_hotkey.py` | `GlobalHotkeyService` over `RegisterHotKey`, running on the OS-event thread; reports registration failure explicitly. |
| `session_events.py` | `SessionEventSource`: lock/unlock/disconnect (`WTSRegisterSessionNotification`) and sleep/resume. |

### `database/`

| File | Responsibility |
|---|---|
| `connection.py` | Per-thread connection factory. Every connection runs: `PRAGMA foreign_keys=ON; journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000`. Transaction helper. Connections are never shared across threads. |
| `codecs.py` | Landmark BLOB encode/decode (`float32` little-endian, C-order) with length/shape validation (§9.2). |
| `migrator.py` | Applies numbered migrations by `PRAGMA user_version`; backs up before each migration; refuses to open a database newer than the application supports (§9.4). |
| `migrations/0001_initial.sql` | The initial schema (§9.1). |
| `repositories/gesture_repository.py` | Gestures and samples: list, create, rename, enable/disable, replace samples, delete. |
| `repositories/workflow_repository.py` | Workflows and ordered actions; lookup by gesture and context; replace action list in one transaction. |
| `repositories/application_repository.py` | Approved applications. |
| `repositories/settings_repository.py` | Key/value settings (validation happens in `SettingsSchema`). |
| `repositories/log_repository.py` | Insert, paginated query, retention pruning (§9.5). |

### `tools/`

| File | Responsibility |
|---|---|
| `benchmark_pipeline.py` | Measures capture FPS, tracking time, end-to-end latency, DTW cost per template, and UI-thread stalls on the target machine (§12.3). |
| `record_fixture.py` | Records landmark-only fixtures (never video) from a webcam with an explicit consent prompt. |
| `evaluate_recognition.py` | Replays labeled landmark recordings through the real engine and reports accept rate, confusion, and false triggers per hour (§17 AC-04…AC-08). |

------------------------------------------------------------------------

## 7. Gesture recognition specification

### 7.1 Coordinate conventions and preprocessing

-   Every captured frame is flipped horizontally (selfie view) **before**
    tracking and preview. Recording and live recognition use identical
    preprocessing, and `preprocess.flip_h = true` is stored with every
    sample. The Tasks API assumes mirrored input when assigning
    handedness, so labels match the user's real left/right hand.
-   The tracker returns two landmark sets per detected hand:
    **image landmarks** (`x, y` normalized to the frame width/height;
    `z` relative depth with the wrist at 0) and **world landmarks**
    (metres, origin at the hand's geometric center). Both are stored raw.
    No derived data is persisted (§9.2).
-   **Aspect correction** for image landmarks: `x' = x · (width / height)`,
    `y' = y`, so image-space units are "frame heights".
-   Landmark indices used: 0 wrist, 9 middle-finger MCP (palm unit),
    4/8/12/16/20 fingertips.
-   Timestamps are monotonic (`capture_ts_ns`), never wall-clock.

### 7.2 Hand selection

`tracked_hand ∈ {RIGHT, LEFT, EITHER}` (default `RIGHT`). The recognition
engine processes **exactly one hand per frame**:

| Setting | Frame contains | Result |
|---|---|---|
| `RIGHT` / `LEFT` | exactly one detection with that label | that hand is selected; other hands ignored |
| `RIGHT` / `LEFT` | only a hand with the other label | `WRONG_HAND` |
| `RIGHT` / `LEFT` | two detections with the tracked label | `AMBIGUOUS_HANDS` |
| `EITHER` | one detection | selected |
| `EITHER` | two detections | `AMBIGUOUS_HANDS` |
| any | none | `NO_HAND` |

A gesture stores the hand it was recorded with and is matched only
against frames whose selected hand equals it. **There is no mirroring in
v1.** All samples of one gesture must share the same hand label
(`RecordingValidator` enforces it). Handedness-label flicker during a
sequence is treated as a tracking gap.

### 7.3 Normalization and features

Orientation is **preserved**: thumbs-up and thumbs-down differ only by
orientation, so rotation-invariant matching would conflate them. v1 is
translation- and scale-invariant, orientation-sensitive and
hand-specific. `NORMALIZER_VERSION = 1`, `FEATURE_VERSION = 1`.

**Static feature vector** (from world landmarks):

1.  Subtract the wrist (landmark 0).
2.  Divide by the palm unit `‖L9 − L0‖`. A palm unit below `1e-6`
    marks the frame invalid (`DEGENERATE_HAND`).
3.  Drop the wrist (now zero): 20 landmarks × 3 = 60 values.

**Static distance** — *mean landmark deviation* (MLD), in palm units:
`MLD(a, b) = mean over the 20 landmarks of ‖aᵢ − bᵢ‖₂`.

**Dynamic per-step vector** (17 values):

-   *Shape (15):* fingertips 4, 8, 12, 16, 20 from the normalized
    world representation above.
-   *Trajectory (2):* wrist position from aspect-corrected **image**
    landmarks, relative to the wrist at the first step of the segment,
    divided by `segment_palm_scale` (the median image-space palm size
    over the segment). `z` is not used.

**Dynamic step cost** between two steps:
`w_shape · mean_tip ‖Δtip‖ + w_traj · ‖Δwrist‖`, with `w_shape = 1.0`
and `w_traj = 2.0` (trajectory is usually more discriminative). Both
terms are palm units.

Property tests (hypothesis) cover: translation invariance, uniform scale
invariance, determinism, and that a 180° rotation changes the distance
beyond the default threshold.

### 7.4 Static gestures

**Recording.**

1.  Countdown (`static_countdown_ms`, 3000) with live landmarks and a
    quality indicator (hand present, hand still).
2.  Capture for `static_capture_window_ms` (1500). A frame is *valid*
    only if exactly one hand is selected, hand speed is below
    `static_max_speed`, and its distance to the running median pose is at
    most `static_capture_max_deviation` (0.10 palm units).
3.  Accept if there are at least `static_min_valid_frames` (20) valid
    frames; keep up to `static_max_samples` (30), evenly spaced. Every
    kept frame is stored as a sample (raw landmarks).
4.  Rejections carry a specific `RejectReason`: `NO_HAND`,
    `AMBIGUOUS_HANDS`, `TOO_FEW_VALID_FRAMES`, `HAND_MOVING`, `LOW_FPS`.
5.  **Collision check before saving.** Compute the smallest MLD between
    the new samples and the samples of every enabled static gesture with
    the same hand. If it is `≤ max(threshold_new, threshold_existing)`,
    block the save and show the conflicting gesture and distance. The
    user may re-record or "Save anyway"; the margin test (below) still
    protects against misfires.

**Thresholds** are computed at load time from the samples (not stored,
so they follow code changes). For each sample *i*,
`rᵢ = min over j≠i of MLD(sample_i, sample_j)`;
`base = clamp(1.5 · p95(r), 0.06, 0.30)`;
`effective = base · sensitivity · gesture.threshold_scale`.

**Matching, per processed frame** (only when a hand is selected and the
motion gate of §7.5 is idle):

1.  For every enabled static gesture whose hand equals the selected hand,
    `d_g = min over its samples of MLD(live, sample)`.
2. Sort ascending: best `(g1, d1)`, second `(g2, d2)`.
3.  The frame-level candidate is **accepted** iff
    `d1 ≤ effective(g1)` **and** (there is no `g2` or
    `d1 / max(d2, ε) ≤ margin_ratio` (0.80)). Otherwise it is rejected
    with `ABOVE_THRESHOLD` or `AMBIGUOUS_MARGIN`.

"No match" is the normal outcome; a pose is never forced onto the
nearest gesture.

**Displayed metric.** The UI shows *Distance (mean landmark deviation,
palm units)*, the threshold and the margin ratio. It never shows a
percentage or "confidence". An optional bar shows
`closeness = clamp(1 − d / threshold, 0, 1)` labeled "closeness to
threshold — not a probability".

### 7.5 Dynamic gestures

**Recording.**

1.  The user sets a maximum window (`dynamic_max_window_ms`,
    1000–5000, default 3000), then a countdown (3000 ms).
2.  The recorder runs the same `MotionSegmenter` used live and
    **auto-stops** when a movement ends (below) or the window expires.
3.  The sequence is trimmed to the segment plus the lookback padding.
4.  Validation (all numeric, Appendix A): duration ≥
    `dynamic_min_duration_ms` (400); wrist path length ≥
    `min_motion_path_palm` (1.5 palm units); missing-frame ratio ≤
    `max_missing_ratio` (0.20); no gap longer than `max_interp_gap_ms`
    (150); effective frame rate ≥ `min_effective_fps` (15); one hand
    label throughout.
5.  The user records **`dynamic_samples_required` (3) repetitions**
    (up to 5) in one session. At least 3 must be valid.
6.  **Consistency check:** pairwise DTW distances among the samples; if
    the maximum exceeds `dynamic_d_max` (0.5) the session is rejected as
    `INCONSISTENT_SAMPLES` ("your repetitions differ too much").
7.  **Collision check** against existing dynamic gestures of the same
    hand: if any new sample is within the existing gesture's effective
    threshold (or vice versa), block the save with the same override
    rule as static gestures.

**Resampling.** Each sample and each live segment is converted to a fixed
grid of `match_rate_hz` (15 Hz) by linear interpolation of the step
vectors over their real timestamps. Gaps up to `max_interp_gap_ms` are
interpolated; longer gaps invalidate the sequence. This makes live
matching independent of the frame rate achieved under load and of frames
dropped by the live mailbox.

**MotionSegmenter** (identical for recording and live):

-   *Speed:* finite-difference wrist speed in aspect-corrected image
    space divided by the running-median palm size (1 s window), smoothed
    with a 80 ms time constant → **palm units per second**.
-   *States:* `IDLE → ACTIVE` when speed ≥ `motion_start_speed` (0.8)
    continuously for `motion_start_ms` (100). `ACTIVE → ENDED` when
    speed ≤ `motion_end_speed` (0.3) for `end_idle_ms` (250), or the
    segment reaches `max_segment_ms` (1.5 × `dynamic_max_window_ms`,
    hard cap 6000). `ABORTED` on a tracking gap above
    `max_interp_gap_ms` or a hand-label change.
-   A ring buffer of the last `segment_lookback_ms` (300) lets the
    segment include the frames just before motion was detected.

**Banded DTW.** `D[i,j] = cost(i,j) + min(D[i−1,j], D[i,j−1], D[i−1,j−1])`
inside a Sakoe–Chiba band of width `dtw_band_fraction` (0.25) of the
longer sequence. The distance is `D[n,m] / (n + m)` — an average
weighted-palm-unit cost, independent of duration. A length-ratio
pre-filter (0.5–2.0×) skips impossible candidates, and **early
abandoning** stops a comparison when the row minimum divided by
`(n + m)` already exceeds the threshold (valid because cumulative cost is
non-decreasing).

**Thresholds** (computed at load): `effective = clamp(1.3 · max
pairwise sample DTW, dynamic_d_min 0.08, dynamic_d_max 0.5) · sensitivity
· threshold_scale`.

**Live matching.** Matching happens **once per completed segment**, not
per frame. At `ENDED`, the segment is resampled and compared against
every enabled dynamic gesture of the selected hand (each gesture's
distance is the minimum over its samples). Acceptance uses the same
two-part rule as static matching with `dynamic_margin_ratio` (0.85). Cost
is bounded: at most (templates × ≤ 5 samples) banded DTWs of roughly
45 × 45 cells, budgeted at ≤ 20 ms for 10 gestures (validated in M0).

**Static/dynamic arbitration.**

-   A static candidate is considered only while the segmenter is `IDLE`
    and hand speed is below `static_max_speed` (0.35); otherwise the
    frame's outcome is `MOVING`. A swipe therefore cannot fire a static
    gesture mid-motion.
-   When any segment ends (matched or not), static accumulation restarts
    from zero: the resting pose must be held for the full
    `stable_duration_ms` afterwards.
-   A segment that ends with no match produces `SEGMENT_NO_MATCH` and
    nothing else.

**Tracking loss.** A gap ≤ `max_interp_gap_ms` is interpolated. A longer
gap aborts the active segment (`TRACKING_LOST`). Static accumulation
tolerates gaps up to `max_gap_ms` (120) and otherwise resets.

### 7.6 Trigger validation (shared by static and dynamic)

`TriggerValidator` is the **only** component that owns time-based
cooldown logic. It runs identically in Test and Live mode, so Test mode
shows exactly what Live mode would trigger.

**Static gestures** — per-gesture state machine
`IDLE → ACCUMULATING → FIRED → COOLDOWN → REARMING → IDLE`:

-   Accumulate while the same gesture is the accepted frame-level
    candidate. Rejections or tracking gaps shorter than `max_gap_ms` do
    not reset the accumulator.
-   When accumulated time reaches `stable_duration_ms` (400), emit
    **one** `RecognitionEvent` and enter `COOLDOWN`.
-   The gesture can fire again only after **both**
    `cooldown_ms` (1500) has elapsed **and** a *release* has been
    observed: it was not the candidate (hand absent, moved, or another
    candidate) for `rearm_release_ms` (300). A held pose fires once.

**Dynamic gestures:** the event is emitted immediately when a completed
segment is accepted; the per-gesture `cooldown_ms` starts at emission.
No rearm step is needed because the next segment is a new movement.

**Global interval:** no two events (any gestures) closer than
`global_cooldown_ms` (500).

All durations use frame capture timestamps via the injected `Clock`
port, so tests can replay recorded sequences deterministically.

**State resets:** mode change, `tracked_hand` change, camera restart, and
a snapshot change affecting that gesture.

`FrameAnalysis.trigger_state ∈ {IDLE, ACCUMULATING, FIRED, COOLDOWN,
REARMING}` together with `accumulated_ms` is published every frame, so
the Testing tab can show why a pose has not fired yet.

### 7.7 Evaluation and tuning protocol

The defaults in Appendix A are starting points. They become trustworthy
only through this protocol:

1.  `tools/evaluate_recognition.py` replays **labeled landmark
    recordings** through the real engine (no camera). It reports, per
    gesture: true-accept rate with a Wilson 95 % interval; a confusion
    matrix; trigger latency; and, for negative data, false triggers per
    hour.
2.  **Evaluation set (landmarks only; no video is stored):** ≥ 3
    volunteers who gave consent; ≥ 5 static and ≥ 3 dynamic gestures;
    ≥ 20 repetitions each; ≥ 3 lighting conditions (daylight, warm
    indoor, low light); **≥ 3 hours of negative data** (idle hand in
    view, typing, mouse use, talking with hands, other gestures).
    Three hours with zero false triggers bounds the rate below 1 per hour
    at 95 % confidence (rule of three).
3.  Any change to a recognition default needs a before/after report from
    this tool recorded in the pull request.
4.  Fixture provenance (who, when, conditions, consent) is documented in
    `tests/fixtures/README.md`.

------------------------------------------------------------------------

## 8. Workflow specification

### 8.1 Model and cardinality

-   A gesture has 0..N workflows: **at most one default workflow**
    (`context_app_id` empty) and **at most one per application id**.
    Enforced in SQL by a unique index on
    `(gesture_id, COALESCE(context_app_id, ''))` (§9.1).
-   A workflow has 1–20 ordered actions.
-   In v1 a context rule is an **exact match on `app_id`**. The domain
    field is `context_app_id` (not a rule object); richer rules such as
    window-title patterns are out of scope. "Most specific" therefore
    means two levels: app-specific beats default.
-   A disabled gesture keeps its workflows; they are dormant and
    Workflow Studio shows a badge. Re-recording a gesture keeps its
    workflows.

### 8.2 Application identity (`app_id`)

-   `app_id` is the **lowercase executable file name** of the foreground
    window's process, e.g. `chrome.exe`. Validation:
    `^[a-z0-9][a-z0-9._ \-]*\.exe$`.
-   Windows hosted by `ApplicationFrameHost.exe` (packaged/UWP apps):
    resolve to the process of the hosted `CoreWindow` child; if that
    fails, the id is `applicationframehost.exe` and Workflow Studio warns
    that context matching is imprecise.
-   Reserved values: **`unknown`** (foreground not inspectable: access
    denied, transient window, no window) and **`self`** (the foreground
    window belongs to Gesture PC).
-   Matching is exact string equality. Workflow Studio's picker lists
    currently running applications and also accepts a typed id.
-   Known limitation: two instances or profiles of the same executable
    are indistinguishable in v1.
-   The context is captured **when the trigger is accepted**, including
    `hwnd` and `pid` (used by §8.6).

### 8.3 Resolution (pure, deterministic)

Inputs: gesture id, `AppContext`, `WorkflowSnapshot`, settings.

0.  If `app_id == self` and `suppress_when_self_foreground` (default
    true), `LiveSink` logs `SUPPRESSED_SELF_FOREGROUND` and stops; nothing
    runs (this prevents accidental actions while editing in the app).
1.  If the gesture is not in the current `TemplateSnapshot` →
    `GESTURE_DISABLED`.
2.  If `app_id ∉ {unknown, self}` and the snapshot holds an **enabled**
    workflow for `(gesture_id, app_id)` → return it.
3.  Else if `use_default_when_no_app_match` (default **true**) and an
    enabled default workflow exists → return it.
4.  Else `NO_WORKFLOW`.

A *disabled* app-specific workflow is treated as nonexistent, so step 3
applies. `use_default_when_no_app_match = false` is a "strict per-app"
switch: gestures then fire only in applications that have an explicit
workflow, and default workflows are ignored. It lives in Settings →
Workflows, with that explanation. At most one workflow can match at each
level (unique index), so the result is deterministic.

### 8.4 Action catalog and risk tiers

| `action_type` | Parameters | Tier | Execution | Context-bound |
|---|---|---|---|---|
| `window_state` | `state`: maximize / minimize / restore | SAFE | atomic | yes |
| `snap_window` | `position`: left / right | SAFE | atomic | yes |
| `media_key` | `key`: play_pause / next / previous / volume_up / volume_down / mute | SAFE | atomic | no |
| `scroll` | `direction`: up / down; `notches`: 1–10 | SAFE | atomic | yes |
| `delay` | `ms`: 50–10 000 | SAFE | interruptible | no |
| `send_shortcut` | `keys`: 1–4 from the key vocabulary; `confirm_sensitive` | ELEVATED | atomic | yes |
| `mouse_click` | `target`: `{relative_to: foreground_window or monitor, x_frac, y_frac ∈ [0,1]}`; `button`; `clicks`: 1–2 | ELEVATED | atomic | when relative to the window |
| `launch_application` | `app_ref` (an approved application); `args`: ≤ 5 strings of ≤ 256 characters | ELEVATED | atomic (`Popen` returns immediately) | no |

Example stored configuration:

```json
{
  "action_type": "snap_window",
  "parameters": { "position": "right" }
}
```

The registry validates it with the action's Pydantic model and maps
`snap_window` to a trusted implementation. Stored strings are never
evaluated.

**Key vocabulary (allowlist of keys):** `a–z`, `0–9`, `F1–F12`, arrow
keys, `home end pageup pagedown`, `enter tab space escape backspace
delete insert`, and the modifiers `ctrl alt shift win`. A chord has at
most 4 keys and at least one non-modifier. `Ctrl+Alt+Delete` cannot be
synthesized and is rejected. **Sensitive chords** (`constants.py`:
Alt+F4, Win+R, Win+X, Win+L, Ctrl+Shift+Esc, Ctrl+W, Ctrl+Q, Delete,
Shift+Delete) require `confirm_sensitive = true` on that action. This
replaces revision 1's ambiguous "allowlisted shortcuts / validated key
names".

**Mouse targets are relative only** (fractions of the foreground window
client area or of a monitor). Absolute pixel coordinates are not
supported because they break under DPI scaling, multi-monitor layouts and
window moves.

**Approved applications.** Settings → Approved applications holds
executables the user added with a file picker. Validation at add time and
re-verified at run time: absolute local path (no UNC), exists, is a file,
extension `.exe`. Workflows reference an `app_ref` id, never a raw path.
Deleting an application still referenced by a workflow is refused, with
the list of dependent workflows.

**Risk acknowledgement.** A workflow containing any ELEVATED action can be
saved, but it is **excluded from the `WorkflowSnapshot` (cannot run)**
until `risk_acknowledged_at` is set through an explicit checkbox ("This
workflow sends keyboard/mouse input or launches programs"). Adding or
changing an ELEVATED action clears the acknowledgement; reordering and
editing SAFE actions does not.

### 8.5 Limits (hard limits)

-   ≤ 20 actions per workflow; names ≤ 64 characters.
-   Sum of declared `delay` durations ≤ 30 000 ms.
-   Whole-workflow watchdog: `workflow_watchdog_ms` (60 000).
-   Per-action timeout: `action_timeout_ms` (5 000) for atomic actions.
-   `max_executions_per_minute` (20) and `consecutive_failure_limit` (3)
    guard against runaway automation (§4.3).

### 8.6 Execution semantics

**Dispatcher** (`submit`):

1.  `gate.is_current(admission)` else drop with `DROPPED_NOT_LIVE`.
2.  Overlap policy **`DROP_WHILE_BUSY`**: if a workflow is executing, the
    new trigger is dropped and logged `DROPPED_BUSY`. There is no waiting
    line; at most one request sits in the hand-off slot to the execution
    thread. A request that has not started within `request_ttl_ms`
    (1500) is discarded as `EXPIRED`.

**Executor** (`run`), on the execution thread:

1.  Verify `is_current` and that the workflow is still enabled in the
    current snapshot (`SKIPPED_WORKFLOW_DISABLED`).
2.  Re-validate every action's parameters through the registry (defense in
    depth). An unknown type or invalid parameters → the workflow does
    not start (`FAILED`, `ACTION_REJECTED`).
3.  For each action in order:
    -   Check `gate.is_current` and the cancellation token → `CANCELLED`.
    -   **Context binding:** for *context-bound* actions that come before
        any `launch_application` in the workflow, verify the foreground
        window still has the captured `hwnd` and `pid`; otherwise stop
        with `SKIPPED_CONTEXT_CHANGED`. After a `launch_application`
        the workflow is "context-detached": later context-bound actions
        act on whatever window is then in the foreground, which the risk
        acknowledgement covers.
    -   **Elevated target:** before a context-bound input action, if the
        target process is elevated and Gesture PC is not, stop with
        `SKIPPED_ELEVATED_TARGET` (Windows would silently drop the input).
    -   Execute through the `DesktopActionAdapter`; record an
        `ActionResult`.
4.  **Failure policy (v1): `ABORT`.** The first failed action aborts the
    remaining actions. No retries, no rollback. The result records the
    failed position, an error code and a safe summary.
5.  The watchdog cancels a workflow exceeding `workflow_watchdog_ms`
    (`TIMED_OUT`).

**At-most-once.** Each accepted trigger produces at most one execution
attempt. A failure, crash, stop or timeout is never retried
automatically. (Revision 1's "exactly once" cannot be guaranteed across
crashes and failures.)

**Logging.** `ExecutionResult` is persisted with action types and
statuses; parameters are not logged except the display name of an
approved application.

### 8.7 Dry-run and preview

`WorkflowPreview.describe(definition)` is a pure function returning:
validity, validation errors, an ordered list of human-readable steps
(for example "1. Snap the foreground window to the right — SAFE"), the
total declared delay and a risk summary. It never calls an adapter and
may run in any mode.

-   **Workflow Studio "Dry run"** renders it (this is what "test a
    workflow safely" means; there is no real-execution test in v1).
-   **Testing tab "would run"** line: when a trigger is accepted in Test
    mode, `DiagnosticSink` runs the pure resolver for the *simulated
    foreground application* and shows the preview text. A selector offers
    "Auto (actual foreground)" or any application id. Because the
    foreground while viewing the tab is Gesture PC (`self`), "Auto"
    explains that Live mode would suppress the trigger and invites the
    user to simulate an application.

------------------------------------------------------------------------

## 9. Data model

### 9.1 Schema (`database/migrations/0001_initial.sql`)

The migration file is the single source of truth for the schema. The
migrator sets `PRAGMA user_version = 1` after applying it.

```sql
CREATE TABLE gestures (
    id                INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL COLLATE NOCASE
                              CHECK (length(trim(name)) BETWEEN 1 AND 64),
    gesture_type      TEXT    NOT NULL CHECK (gesture_type IN ('STATIC', 'DYNAMIC')),
    hand              TEXT    NOT NULL CHECK (hand IN ('LEFT', 'RIGHT')),
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    threshold_scale   REAL    NOT NULL DEFAULT 1.0
                              CHECK (threshold_scale BETWEEN 0.5 AND 1.5),
    template_revision INTEGER NOT NULL DEFAULT 1 CHECK (template_revision >= 1),
    created_at        TEXT    NOT NULL,   -- ISO-8601 UTC
    updated_at        TEXT    NOT NULL,
    UNIQUE (name)                         -- case-insensitive via column collation
);
CREATE INDEX ix_gestures_enabled ON gestures (enabled);

CREATE TABLE gesture_samples (
    id                 INTEGER PRIMARY KEY,
    gesture_id         INTEGER NOT NULL REFERENCES gestures(id) ON DELETE CASCADE,
    sample_index       INTEGER NOT NULL CHECK (sample_index >= 0),
    frame_count        INTEGER NOT NULL CHECK (frame_count >= 1),
    duration_ms        INTEGER NOT NULL DEFAULT 0,
    landmarks_image    BLOB    NOT NULL,  -- float32 LE, shape (frame_count, 21, 3)
    landmarks_world    BLOB    NOT NULL,  -- float32 LE, shape (frame_count, 21, 3)
    timestamps_ms      BLOB,              -- int32 LE, shape (frame_count,); NULL if static
    frame_aspect_ratio REAL    NOT NULL,  -- width / height at capture
    tracker_model_id   TEXT    NOT NULL,  -- 'hand_landmarker.task@<12 hex of SHA-256>'
    preprocess_json    TEXT    NOT NULL,  -- e.g. {"flip_h": true}
    created_at         TEXT    NOT NULL,
    UNIQUE (gesture_id, sample_index)
);

CREATE TABLE approved_applications (
    id           INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL COLLATE NOCASE UNIQUE
                      CHECK (length(trim(display_name)) BETWEEN 1 AND 64),
    exe_path     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE workflows (
    id                   INTEGER PRIMARY KEY,
    gesture_id           INTEGER NOT NULL REFERENCES gestures(id) ON DELETE CASCADE,
    name                 TEXT    NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 64),
    context_app_id       TEXT    CHECK (context_app_id IS NULL
                                        OR context_app_id = lower(context_app_id)),
    enabled              INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    risk_acknowledged_at TEXT,
    created_at           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL
);
-- one default workflow and at most one per app, per gesture
CREATE UNIQUE INDEX ux_workflows_gesture_context
    ON workflows (gesture_id, COALESCE(context_app_id, ''));

CREATE TABLE workflow_actions (
    id              INTEGER PRIMARY KEY,
    workflow_id     INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL CHECK (position >= 0),
    action_type     TEXT    NOT NULL,
    parameters_json TEXT    NOT NULL,
    UNIQUE (workflow_id, position)
);

CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE event_logs (
    id             INTEGER PRIMARY KEY,
    timestamp_utc  TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    status         TEXT NOT NULL,
    correlation_id TEXT,
    gesture_id     INTEGER,   -- intentionally NO foreign key: history outlives deletions
    gesture_name   TEXT,      -- name snapshot at event time
    workflow_id    INTEGER,   -- intentionally NO foreign key
    workflow_name  TEXT,
    details_json   TEXT CHECK (details_json IS NULL OR length(details_json) <= 2048)
);
CREATE INDEX ix_event_logs_time        ON event_logs (timestamp_utc);
CREATE INDEX ix_event_logs_correlation ON event_logs (correlation_id);
```

**Deletion behavior (decided).**

-   Deleting a **gesture** is a hard delete after a confirmation dialog
    that lists the workflows that will be removed. `ON DELETE CASCADE`
    removes its samples, workflows and actions, so nothing is orphaned.
    Log rows remain readable through their name snapshots.
-   Deleting a **workflow** cascades to its actions.
-   Deleting an **approved application** referenced by a workflow is
    refused by `ConfigurationService` (SQLite cannot enforce a reference
    inside `parameters_json`). Snapshot building additionally excludes any
    workflow whose `app_ref` no longer resolves and reports it.
-   Reordering or editing actions **replaces the workflow's action list
    in one transaction** (delete + insert), because SQLite cannot defer
    the `UNIQUE (workflow_id, position)` check.

### 9.2 Landmark storage

| Column | Encoding |
|---|---|
| `landmarks_image` | `float32`, little-endian, C-order, shape `(frame_count, 21, 3)`: `x, y` normalized by frame width/height (**not** aspect-corrected), `z` relative depth |
| `landmarks_world` | same shape; metres, origin at the hand's geometric center |
| `timestamps_ms` | `int32`, little-endian, shape `(frame_count,)`, milliseconds since the first frame; `NULL` for static samples |

-   A static gesture stores up to 30 rows with `frame_count = 1`; a
    dynamic gesture stores 3–5 rows, each a full sequence.
-   `database/codecs.py` validates on decode: `len(blob) ==
    frame_count · 21 · 3 · 4`, all values finite, timestamps strictly
    increasing. Any failure excludes the gesture from the snapshot and
    marks it "Needs re-recording"; the application does not crash.
-   Size: about 504 bytes per frame (both landmark sets); a 90-frame
    dynamic sample ≈ 45 kB, 30 static samples ≈ 15 kB.
-   **Why raw landmarks rather than derived features:** normalization and
    feature definitions can change (new `NORMALIZER_VERSION` or
    `FEATURE_VERSION`) without forcing users to re-record, because
    features are recomputed from the stored landmarks at load time.
    Landmarks are not images and no video is stored, but hand geometry is
    personal data: it stays local and is never transmitted (R11).

### 9.3 Versioning

| Version | Where | Purpose | On mismatch |
|---|---|---|---|
| **Schema version** | `PRAGMA user_version` | Database structure | Migrate (after backup); refuse a newer database |
| **`NORMALIZER_VERSION`**, **`FEATURE_VERSION`** | Code constants | How normalized landmarks and feature vectors are derived. **Not stored**: recomputed from raw landmarks at load | Nothing to migrate. Changing either requires updated tests and a §7.7 re-evaluation |
| **`tracker_model_id`** | Per sample | Landmark geometry can differ between tracker models | Not in `COMPATIBLE_TRACKER_MODELS` → gesture excluded, "Needs re-recording". Compatible but different → allowed with a diagnostics warning |
| **`template_revision`** | `gestures` | Incremented on re-record; for cache invalidation and log context | Not a format version |

Revision 1's `gestures.template_version` is removed; its three
overlapping meanings are now the four distinct rows above.

### 9.4 Migrations, backups, integrity

-   Migrations are numbered (`NNNN_description.sql`, or `.py` for data
    migrations), applied in order, each in a transaction that ends by
    setting `user_version`.
-   **Before any migration** the migrator uses `Connection.backup()` to
    write `backups/gesturepc-v{old}-{YYYYMMDD-HHMMSS}.db`. The newest 5
    backups are kept. A backup is also taken at startup if the newest is
    older than 7 days.
-   A database with `user_version` greater than the application supports
    is not opened; the user sees "created by a newer version".
-   Startup runs `PRAGMA quick_check`. On failure the user is offered
    restoration from the newest backup; the application never silently
    recreates the database.
-   Destructive operations run inside transactions. There is no
    import/export in v1.

### 9.5 Logging and retention

-   **Persisted:** accepted `RecognitionEvent`s; dynamic
    `SEGMENT_NO_MATCH` (rate-limited); execution results; drops and
    suppressions (`DROPPED_*`, `SUPPRESSED_*`, `NO_WORKFLOW`); mode
    changes with their reason; errors.
-   **Not persisted:** per-frame `FrameAnalysis`. It lives in a UI ring
    buffer of 500 entries. The optional `verbose_recognition_log`
    setting (off by default) persists candidates at ≤ 5 rows/s.
-   **Retention:** keep the newest 10 000 rows and at most 30 days,
    pruned at startup and hourly.
-   **Redaction:** window titles are never persisted unless
    `log_window_titles` is enabled; action parameters are never logged
    except the display name of an approved application. `details_json` is
    capped at 2 048 bytes by a `CHECK` constraint.
-   All inserts go through the single log-writer thread in batches (WAL
    mode), so recognition and execution threads never block on SQLite.

------------------------------------------------------------------------

## 10. Data contracts between modules

Keep interfaces stable so each subsystem can be developed and tested
independently. All contract objects are frozen dataclasses; array fields
are read-only NumPy arrays (R8).

| Contract | Fields |
|---|---|
| **TrackingResult** | `frame_id`, `capture_ts_ns`, `frame_size`, `status` (`OK`, `NO_HAND`, `TRACKER_ERROR`), `hands`: tuple of `HandObservation` (`label`, `label_score`, `presence_score`, `landmarks_image`, `landmarks_world`). No workflow information. |
| **RecordingResult** | `gesture_type`, `hand`, `samples`, `duration_ms`, `effective_fps`, `valid`, `reject_reason`, `feedback_key`, `collisions` (conflicting gesture, distance). A failed recording always carries a displayable reason. |
| **FrameAnalysis** | `frame_id`, `capture_ts_ns`, `hand_status`, `motion_state`, `hand_speed`, `best_gesture_id`, `best_distance`, `second_gesture_id`, `second_distance`, `threshold`, `margin_ratio`, `outcome` (`CANDIDATE_ACCEPTED`, `REJECTED`, `MOVING`, `NO_HAND`, `SEGMENT_NO_MATCH`, …), `reject_reason`, `trigger_state`, `accumulated_ms`. UI/diagnostics only. |
| **RecognitionEvent** | `event_id` (UUID4), `gesture_id`, `gesture_name`, `gesture_type`, `hand`, `capture_ts_ns`, `timestamp_utc`, `distance`, `threshold`, `margin_ratio`. Emitted **only after trigger validation**. Carries no executable content, no action command and no epoch. |
| **Admission** | `epoch`, `token`. Issued by `ExecutionGate.admit()` while open. |
| **ExecutionRequest** | `correlation_id` (= `event_id`), `gesture_id`, `workflow` (the immutable `WorkflowDefinition` resolved at admission), `context` (`AppContext`), `admission`, `created_ns`. |
| **ExecutionResult** | `correlation_id`, `workflow_id`, `workflow_name`, `status` (Appendix B), `started_utc`, `ended_utc`, `actions` (tuple of `ActionResult`), `failed_position`, `error_code`, `safe_summary`. |
| **ActionResult** | `position`, `action_type`, `status`, `error_code`, `duration_ms`. |
| **SnapshotReport** | Per excluded gesture/workflow: id, name, reason (`NEEDS_RERECORDING`, `INVALID_LANDMARKS`, `UNSUPPORTED_TRACKER_MODEL`, `INVALID_WORKFLOW`, `RISK_NOT_ACKNOWLEDGED`, `MISSING_APP_REF`). |

These contracts prevent UI, recognition and execution from becoming
tightly coupled: the executor receives a validated definition, never a
database row or UI object.

------------------------------------------------------------------------

## 11. Complete runtime flows

### A. Register a static gesture

1.  User opens Gesture Studio and chooses Static, then presses Record.
    If the mode is `LIVE`, a confirmation dialog states that recording
    stops Live Automation.
2.  `GestureService` asks `RuntimeController` for a `RECORDING` session
    (via `STOPPED` if needed). The pipeline starts with the lossless
    queue.
3.  Countdown runs while `CameraManager` supplies frames and
    `HandTracker` + `HandSelector` produce the selected hand.
4.  `recorder.py` collects valid frames per §7.4.
5.  `recording_validator.py` checks the result and returns feedback.
6.  `calibration.py` runs the collision check.
7.  The UI previews the capture (median pose, sample count, quality) and
    collects a name; the service validates it (case-insensitive unique).
8.  `GestureService` writes the gesture and its samples in one
    transaction.
9.  `ConfigChanged` → `SnapshotService` rebuilds and swaps the
    `TemplateSnapshot` off the UI thread. The mode returns to `STOPPED`.

### B. Register a dynamic gesture

1.  User chooses Dynamic and sets the maximum window (1–5 s).
2.  After the countdown the recorder runs the `MotionSegmenter`; each
    repetition auto-stops when the movement ends.
3.  The validator applies the numeric rules of §7.5 per repetition.
4.  After at least 3 valid repetitions the consistency check and the
    collision check run.
5.  The UI previews the sequence (landmark playback) and collects a name.
6.  The service stores the samples (with timestamps) transactionally.
7.  The snapshot is rebuilt and swapped; no application restart.

### C. Re-record a gesture

1.  User selects an existing gesture and chooses Re-record (type and
    name are kept).
2.  Steps 2–6 of flow A or B run. Nothing is written until the user
    confirms.
3.  `GestureService` replaces the samples in one transaction,
    increments `template_revision` and `updated_at`. **Attached workflows
    are untouched.** Cancelling leaves the existing gesture unchanged.

### D. Create or update a workflow

1.  Workflow Studio loads gestures and their workflows through the
    services.
2.  User selects a gesture and a context (default or a specific
    application).
3.  Action cards are generated from `ActionRegistry.describe()`; each
    edit is validated live and summarized by `WorkflowPreview`.
4.  User may press Dry run; for workflows with ELEVATED actions the
    acknowledgement checkbox appears.
5.  `WorkflowService` validates limits, the unique (gesture, context)
    rule and parameters, then writes the workflow and its action list in
    one transaction.
6.  `ConfigChanged` → the workflow snapshot is rebuilt. An ELEVATED
    workflow without acknowledgement is excluded and shown with a badge.
7.  The Testing tab can show the workflow that *would* run (text only).

### E. Test recognition safely

1.  User explicitly starts Test mode (`STOPPED → TEST`).
2.  `RuntimeController` selects `DiagnosticSink` and starts the pipeline.
3.  The recognition engine processes frames using the same
    `TemplateSnapshot` as Live mode.
4.  Every frame yields a `FrameAnalysis`; the trigger validator emits a
    `RecognitionEvent` when a gesture is accepted.
5.  `DiagnosticSink` forwards both to the Testing tab, the bus and the
    logger, and attaches the "would run" preview text (§8.7).
6.  **No gate admission, no dispatcher call and no adapter call is
    possible in this mode** (§4.6).

### F. Run live automation

1.  User clicks Start Live Automation. Preconditions (§4.3) are
    checked; the first entry per launch shows the confirmation dialog.
2.  `RuntimeController` opens the gate (new epoch), selects `LiveSink`
    and starts or continues the pipeline.
3.  A candidate passes matching and trigger validation → a
    `RecognitionEvent`.
4.  `LiveSink` calls `gate.admit()`; `None` → logged
    `DROPPED_NOT_LIVE`.
5.  `LiveSink` captures the `AppContext`. If the foreground is Gesture
    PC itself and suppression is enabled → `SUPPRESSED_SELF_FOREGROUND`.
6.  `WorkflowResolver` (§8.3) selects the workflow from the current
    snapshot; none → logged `NO_WORKFLOW`.
7.  Rate limit check; exceeding `max_executions_per_minute` triggers an
    automatic exit to `STOPPED`.
8.  `ExecutionDispatcher.submit` re-checks the gate, applies
    `DROP_WHILE_BUSY` and the TTL, and hands the request to the
    execution thread.
9.  `WorkflowExecutor` runs the actions per §8.6, checking the gate
    before every action.
10. The `ExecutionResult` goes to the bus, the UI and the log; the
    consecutive-failure counter is updated.

### G. Stop automation

1.  Any stop mechanism fires (hotkey, overlay, tray, main window,
    automatic exit).
2.  `RuntimeController.emergency_stop()` calls `gate.close()`.
3.  The hand-off slot is cleared; in-flight atomic actions finish,
    interruptible ones stop within 50 ms, the remaining actions are
    marked `CANCELLED`.
4.  The mode becomes `STOPPED`, the pipeline stops, and
    `RuntimeStatusChanged(reason)` is published.

### H. Startup and shutdown

**Startup:**

1.  Acquire the single-instance lock (`QLockFile` in the data directory).
    A second instance shows "already running" and exits, so two
    instances can never execute the same gesture or fight over the
    camera and hotkey.
2.  Configure logging; resolve paths.
3.  Database: `quick_check`, back up if due, migrate.
4.  Load and validate settings (invalid values fall back to defaults with
    a warning).
5.  Verify the tracker model SHA-256.
6.  Build snapshots; construct components in mode `STOPPED`.
7.  Register the global hotkey (failure is shown; Live mode stays
    refused until fixed).
8.  Show the window; if the launch preference is `TEST`, start Test mode.

**Shutdown:**

1.  Set `STOPPED` through the controller (`gate.close()` first); wait up
    to 2 s for the execution thread.
2.  Stop the recognition thread, then the capture thread; release the
    camera.
3.  Unregister the hotkey and session notifications.
4.  Flush the log writer; close all database connections.
5.  Release the single-instance lock.

------------------------------------------------------------------------

## 12. Performance and concurrency

### 12.1 Targets

**Reference machine (initial):** Windows 10/11 x64, ≥ 4 physical cores,
≥ 8 GB RAM, integrated graphics only, a built-in or USB webcam captured
at 640 × 480, 30 fps. These are starting targets, validated in
Milestone 0 and Milestone 8.

| Metric | Target |
|---|---|
| Sustained processed frame rate (tracking + matching) | ≥ 20 fps (goal 30) |
| Capture → `FrameAnalysis` latency | p95 ≤ 100 ms |
| Static trigger latency (pose held → event) | p95 ≤ `stable_duration_ms` + 150 ms |
| Dynamic trigger latency (movement ends → event) | p95 ≤ `end_idle_ms` + 150 ms |
| DTW cost | ≤ 5 ms per comparison (45 × 45 band); ≤ 20 ms per segment for 10 gestures |
| UI event-loop stalls under full pipeline load | p99 ≤ 50 ms |
| Stop latency (hotkey → gate closed) | p95 ≤ 100 ms |
| Camera released after shutdown request | ≤ 2 s |
| Memory growth, 1 hour of idle Live mode | ≤ 50 MB |
| Average CPU, Live mode, reference machine | ≤ 30 % of total |

If a target is missed, the levers are applied in this order and
re-measured: reduce `preview_fps`; raise `min_hand_detection_confidence`
to cut re-detections; process every second frame for static matching
only; adopt the optional `numba` DTW path; move recognition to a worker
process (§3.2). Algorithms are not changed before measurement.

### 12.2 Concurrency and lifecycle rules

-   One camera owner (`CameraManager`, driven by `RuntimeController`).
    Tabs never open camera handles, so switching tabs cannot create a
    second one.
-   Bounded queues everywhere (§3.3). Stale live frames are dropped; the
    recording path never drops frames; execution and log records are
    never dropped silently.
-   One hand per frame and one workflow at a time (`DROP_WHILE_BUSY`).
    Concurrency is added only if a tested use case requires it.
-   Shutdown follows §11-H: stop accepting events, close the gate, cancel
    the hand-off slot, stop workers, release the camera, flush logs,
    close the database.
-   **Camera loss:** read failures lasting longer than
    `pipeline_stall_ms` publish `PipelineError(CAMERA_LOST)`; the
    controller goes to `STOPPED` and shows a Retry button. There is no
    automatic resume.

### 12.3 Measurement and verification

-   `tools/benchmark_pipeline.py` reports FPS, tracking time, end-to-end
    latency, DTW cost and UI stalls (a heartbeat `QTimer` measures event
    loop delay). It runs in M0 (feasibility) and M8 (release).
-   **Stop latency in real use:** `RuntimeStatusChanged` details record
    `hotkey_pressed_ns` and `gate_closed_ns`, so the target is measurable
    from logs. Automated tests verify the gate logic with a fake clock.
-   Benchmarks are not part of CI pass/fail (hardware-dependent); their
    reports are archived with each release.

------------------------------------------------------------------------

## 13. Safety, privacy and threat model

### 13.1 Threats and controls

| Threat | Example | Controls |
|---|---|---|
| **T1 Accidental trigger** | Talking with your hands, reaching for the mouse | Per-gesture threshold, margin test, stability time, motion gating, cooldown + rearming, self-foreground suppression, ELEVATED-action acknowledgement, rate limit, evaluation target of ≤ 1 false trigger/hour (§7.7, AC-08) |
| **T2 Other people or screens** | A colleague, a video call or TV in view | Single-hand selection with `tracked_hand`, `AMBIGUOUS_HANDS` rejection, always-visible LIVE indicator. No person identification in v1 (documented limitation) |
| **T3 Runaway automation** | Trigger loop, stuck action | `DROP_WHILE_BUSY`, `max_executions_per_minute`, `consecutive_failure_limit`, per-workflow watchdog, global stop hotkey, automatic exits (§4.3) |
| **T4 Local tampering** | Someone edits the SQLite file | **Not a security boundary.** An attacker with user-level file access can already run programs as that user, so v1 claims no integrity protection. The acknowledgement flag and approved-application list are guardrails against *mistakes*. The data directory uses default per-user ACLs. There is no import/export, so no shared-workflow vector; if one is added later, imported workflows must open in a review screen with every ELEVATED acknowledgement cleared |
| **T5 Privilege boundaries** | Elevated windows, UAC secure desktop, lock screen | Elevated-target detection (`SKIPPED_ELEVATED_TARGET`), session lock → `STOPPED`, no attempt to self-elevate |
| **T6 Privacy** | Camera frames, hand geometry | Frames live in memory only; only landmarks are stored; no network access (R11); deleting a gesture deletes its samples; camera status always visible; log redaction (§9.5) |
| **T7 Supply chain** | A malicious dependency release | Exact version pins; hash-pinned install (`pip --require-hashes`) once versions are frozen; minimal dependency set; tracker model hash verified at startup |
| **T8 Crashes and hangs** | Camera driver hang, thread exception | Thread isolation, watchdogs, `PipelineError`, the UI never crashes on camera or workflow failure, launch always in `STOPPED` |

### 13.2 Required safety behavior

-   An always-visible global **Stop** control, plus the OS-level hotkey,
    overlay and tray entries of §4.5.
-   Start in `STOPPED` after installation and after any unexpected
    restart; never execute on launch.
-   Test mode is execution-free by design (§4.6), not by convention.
-   Allowlisted action registry; never `eval`, `exec`, `pickle` or run
    arbitrary database content.
-   Validate executable paths, key names, relative coordinates, delays
    and every action parameter at save time, at snapshot time and again
    at execution time.
-   Bound workflow length, delay duration and total execution time
    (§8.5).
-   Camera frames stay in memory. Persist landmarks only (§9.2); no raw
    video unless a future feature explicitly asks and the user consents.
-   Keep logs bounded; do not log window titles or action arguments
    (§9.5).
-   Use transactions, and back up the database before migrations and
    periodically (§9.4).

### 13.3 Error conditions and user-visible behavior

| Condition | Behavior | Message (summary) |
|---|---|---|
| Camera not found | Stay `STOPPED`; offer re-probe and device selection | "No camera found at the selected device." |
| Camera busy (another app) | Stay `STOPPED`; Retry | "The camera is in use by another application." |
| Camera opens but gives no frames | Stay `STOPPED` | "No video received. Check Windows Settings → Privacy & security → Camera." |
| Camera lost while running | Auto-exit to `STOPPED` | "Camera disconnected. Automation stopped." |
| Tracker model missing or hash mismatch | Block the pipeline | "Hand-tracking model is missing or damaged. Reinstall." |
| Invalid recording | Show the `RejectReason` and a tip; allow retry | e.g. "Hold still: your hand was moving." |
| Duplicate gesture name | Block save | "A gesture named 'X' already exists." |
| Gesture collision | Block save unless overridden | "Looks similar to 'X' (distance 0.05). Re-record or save anyway." |
| Gesture or workflow excluded from snapshot | Badge in the relevant tab | "Needs re-recording" / "Invalid: reason" / "Won't run until acknowledged" |
| Hotkey registration failed | Warn; refuse Live mode | "Stop hotkey is taken. Choose another in Settings." |
| Action skipped (elevated target, context changed) | Log; one-time toast | "Skipped: the target window is running as administrator." |
| Workflow failure | Log; consecutive-failure counter | "Workflow 'X' failed at step N." |
| Session locked or system sleeping | Auto-exit to `STOPPED` | "Automation stopped because the session was locked." |
| Database newer than the application | Do not open | "This data was created by a newer version." |

### 13.4 Windows edge cases

| Situation | Handling |
|---|---|
| Elevated (administrator) target window | Windows blocks input from a non-elevated process (UIPI). Detect and skip (`SKIPPED_ELEVATED_TARGET`). The application never self-elevates. |
| Packaged/UWP apps | `ApplicationFrameHost` resolution of §8.2; documented imprecision if it fails. |
| High-DPI and mixed-DPI monitors | Qt 6 per-monitor DPI awareness; mouse targets are fractions of a window or monitor; window placement uses the monitor work area in physical pixels. |
| Multiple monitors | "Monitor" means the monitor containing the captured foreground window. |
| Virtual desktops | Actions affect only the current desktop. |
| Full-screen or exclusive-mode games | Input synthesis may not reach them; documented limitation. |
| UAC prompt / secure desktop | Foreground is not readable → `app_id = unknown`; input is blocked; session lock still stops Live mode. |
| Another app holds the camera (Teams, Zoom) | `CAMERA_BUSY`, never a crash. |
| Sleep / resume | Live → `STOPPED` on suspend; stays `STOPPED` after resume; the camera is re-opened on the next start. |
| Camera selection | OpenCV exposes only indices. `CameraManager` probes indices 0–4 (with a timeout) and stores `backend + index`; names from `QMediaDevices` are shown best-effort only. If the stored device fails to open, the user re-selects. |
| Camera backend | Default `DSHOW` with fallback to `MSMF` (configurable). Verified on target hardware in M2. |
| Security software | Input synthesis can trigger EDR/antivirus heuristics; noted in the README. |

------------------------------------------------------------------------

## 14. UI specification

### 14.1 Primary user flow

**Entry → Gesture Studio (record) → Workflow Studio (assign) → Testing
Studio (verify) → Live Monitor (run).** Alternatives: edit a workflow
only; re-record only; run Test mode repeatedly while tuning sensitivity.
On first launch the empty states form an onboarding path ("1 Record a
gesture → 2 Assign actions → 3 Test → 4 Go Live"), shown as a readiness
checklist on Live Monitor.

### 14.2 Shell and visual direction

-   **Persistent status bar** on every tab: mode badge, camera status,
    stop-hotkey status, foreground application. A red **Stop** button
    stays visible in the top-right corner.
-   Mode badges always combine **text + icon + color** (never color
    alone): Stopped (grey, ■), Recording (purple, ●), Test mode (blue,
    ◆), Live Automation (red-orange, ▶). Motion respects the OS
    reduced-motion setting.
-   Follows the system light/dark theme; high contrast; scales with
    system text size. Minimum window size 1100 × 700; layouts use
    splitters and reflow between 1100 and 1920 px wide. Desktop-only
    (no tablet/mobile layouts).
-   Fully keyboard-navigable with logical focus order; every control has
    an accessible name; nothing depends on hover alone.
-   Destructive or risky actions (delete, enter Live, record while Live)
    use explicit confirmation dialogs that name the consequence.

### 14.3 Mode-gated controls

| Control | `STOPPED` | `RECORDING` | `TEST` | `LIVE` |
|---|---|---|---|---|
| Start Test | enabled | disabled | (Stop Test) | disabled — "Stop Live first" |
| Start Live Automation | enabled | disabled | enabled | (Stop) |
| Record (Gesture Studio) | enabled | (Cancel) | enabled (ends Test) | enabled **with confirmation** |
| Edit workflows and gestures | enabled | enabled except the gesture being recorded | enabled | enabled (applies to later triggers, §3.4) |
| Settings that change recognition | enabled | locked | enabled (resets trigger state) | enabled (resets trigger state) |
| Stop | hidden | Cancel | enabled | always enabled |

### 14.4 Tabs

| Tab | Purpose and primary action | Content, in priority order | States |
|---|---|---|---|
| **Live Monitor** | Operate and observe automation. **Start / Stop Live Automation.** | Mode + stop-hotkey reminder; camera preview with optional overlay; current trigger state; foreground app and the workflow that would run; recent executions (status, workflow, duration); readiness checklist and snapshot warnings | *Empty:* onboarding checklist with links. *Loading:* "Starting camera…" with Cancel. *Error:* banner with Retry. *Blocked:* names the failing precondition (§4.3) |
| **Gesture Studio** | Create and manage gestures. **Record.** | List (name, type, hand, enable toggle, status badge, workflow count); recording panel (type, window length for dynamic, preview with countdown, quality indicator, Record/Cancel); result panel (feedback, collisions, name field, Save); details (rename, sensitivity slider 0.5–1.5 with explanation, Re-record, Delete) | *Empty:* "No gestures yet — record your first." *Recording:* controls locked, large countdown. *Invalid:* specific reason + tip + Retry. *Camera error:* banner |
| **Workflow Studio** | Define what each gesture does. **Save workflow.** | Gesture picker with badges (disabled, needs re-recording); per-gesture workflow list (Default + per-app); editor (name, context picker listing running apps, enable toggle); action cards (add, reorder, remove, parameter form from the registry schema, risk badge); acknowledgement checkbox for ELEVATED actions; validation summary; **Dry run** panel | *Empty:* link to Gesture Studio. *No workflows:* "Create the default workflow". *Invalid:* inline errors, Save disabled. *Excluded:* "Won't run until acknowledged" badge |
| **Testing Studio** | Verify recognition safely and tune. **Start / Stop Test.** | Banner "Test mode — nothing is executed"; preview with overlay; diagnostics (hand status, motion state, best candidate, distance, threshold, margin, trigger state with progress toward `stable_duration_ms`); event history; "would run" line with *Simulate foreground* selector | *Not started.* *No gestures:* link. *Camera error:* banner |
| **Settings** | Configure the application. **Apply.** | Camera (probe, backend, resolution); Recognition (tracked hand, sensitivity; Advanced, collapsed, with timing values and Restore defaults); Workflows (default-fallback switch, suppress-when-self, rate limit); Safety (stop hotkey, launch mode `STOPPED`/`TEST`); Approved applications; Logging (verbose log, window titles, retention); Data (open folder, reset); About (model hash, versions) | Inline validation with ranges and units; Apply/Reset per section; recognition changes reset trigger state |

------------------------------------------------------------------------

## 15. Testing strategy

### 15.1 Principles

-   Every external dependency is a port (`domain/ports.py`) with a fake in
    `tests/fakes/`: `fake_camera.py` (replays recorded landmark/frame
    sequences with timestamps and injects failures: busy, no frames,
    loss), `fake_tracker.py`, `fake_desktop_adapter.py` (records calls;
    configurable failures, elevation and foreground), `fake_foreground.py`,
    `fake_hotkey.py`, `fake_session_events.py`, `fake_clock.py`.
-   Time is injected through the `Clock` port, so cooldowns, stability
    and DTW segmentation are tested deterministically by replay.
-   **Automated tests never open a camera and never perform real desktop
    actions or launch applications.** An autouse fixture makes the real
    `adapters.windows` constructors raise inside the test suite.
-   Coverage gates (initial): `domain/`, `gestures/`, `workflows/` and
    `services/` ≥ 85 % line coverage; overall ≥ 75 %.
-   Unit-test fixtures are **synthetic** (generated by
    `tests/fixtures/generate.py` with a fixed seed: parametric hand poses
    with controlled noise). The *evaluation* set of §7.7 is real,
    consented, landmarks-only data kept outside unit tests.

### 15.2 Test files

| File | Verifies |
|---|---|
| `unit/test_normalizer.py` | Translation and scale invariance (hypothesis), orientation sensitivity, degenerate hands, determinism |
| `unit/test_feature_extractor.py` | Static (60) and dynamic (17) vector layouts; version constants |
| `unit/test_hand_selector.py` | Every row of the §7.2 table |
| `unit/test_resampler.py` | Timestamp-based resampling, gap interpolation, over-limit gaps |
| `unit/test_segmenter.py` | Start/end thresholds, lookback, max length, abort on tracking loss |
| `unit/test_recording_validator.py` | Each rejection rule with its numeric threshold |
| `unit/test_calibration.py` | Threshold derivation and clamps; collision detection with synthetic pairs |
| `unit/test_static_matcher.py` | Known match, unknown pose, threshold edge, margin test |
| `unit/test_dynamic_matcher.py` | Speed variation, mismatch, missing frames, band, early-abandon result equal to full DTW, length filter |
| `unit/test_trigger_validator.py` | Stability, gap tolerance, cooldown, rearming, global interval, dynamic path, resets |
| `unit/test_recognition_engine.py` | Static/dynamic arbitration, `MOVING`, post-segment restart |
| `unit/test_workflow_resolver.py` | All four resolution steps, disabled workflows, `unknown`/`self`, strict-per-app switch |
| `unit/test_workflow_preview.py` | Descriptions, errors, risk summary; no adapter access |
| `unit/test_action_registry.py` | Parameter models, key vocabulary, sensitive chords, unknown types, risk tiers |
| `unit/test_actions.py` | Each action against the fake adapter; context-bound vs detached rules |
| `unit/test_workflow_executor.py` | `ABORT` policy, cancellation, watchdog, `SKIPPED_CONTEXT_CHANGED`, `SKIPPED_ELEVATED_TARGET` |
| `unit/test_execution_dispatcher.py` | `DROP_WHILE_BUSY`, TTL, gate checks |
| `unit/test_execution_gate.py` | Epoch semantics; multithreaded stress |
| `unit/test_runtime_controller.py` | Table-driven transitions including every illegal one, preconditions, every automatic exit, rate and failure limits |
| `unit/test_active_application.py` | `app_id` normalization, `unknown`/`self`, UWP resolution |
| `unit/test_settings_schema.py` | Ranges, defaults, fallback for invalid stored values |
| `unit/test_codecs.py` | BLOB round trip, corruption and shape errors |
| `unit/test_migrator.py` | Upgrade from fixture databases, backup creation, refusal of a newer database |
| `unit/test_snapshot_service.py` | Exclusion reasons, atomic swap, debounce |
| `unit/test_event_logger.py` | Retention, bounds, redaction, rate limit |
| `integration/test_gesture_persistence.py` | Create/load/rename/delete (cascade, `foreign_key_check` clean), transactional re-record, sample round trip, case-insensitive uniqueness |
| `integration/test_workflow_persistence.py` | Ordered actions, unique (gesture, context) index, atomic reorder, acknowledgement flag |
| `integration/test_testing_mode.py` | Full pipeline in `TEST` against a spy adapter: events displayed and logged, **zero adapter calls**, "would run" text produced |
| `integration/test_live_execution.py` | Full pipeline in `LIVE` with the fake adapter: at-most-once per trigger, held pose fires once, drop-while-busy, self-suppression, context change, ELEVATED without acknowledgement |
| `integration/test_stop_behavior.py` | Stop during a `delay`, gate closed before cancellation, 1 000 randomized stop times produce no action after the gate closes, `LiveSink` attached to a closed gate executes nothing |
| `integration/test_mode_switching.py` | LIVE → RECORDING confirmation path, recording returns to `STOPPED`, snapshot swap while frames flow |
| `integration/test_startup_shutdown.py` | Single-instance lock, ordering, camera release |
| `integration/test_ui_smoke.py` | `pytest-qt` offscreen: tabs construct, mode badge follows `RuntimeStatusChanged`, §14.3 control gating, `testing_tab` has no executor reference |
| `architecture/test_import_rules.py` | R1, R2, R4, R9, R10 by AST import-graph analysis |
| `architecture/test_no_network_imports.py` | R11: no `requests`, `urllib.request`, `http.client` or socket clients in application code |
| `architecture/test_no_dynamic_exec.py` | R5: no `eval`, `exec`, `pickle`, dynamic import from data, or `shell=True` |
| `manual/acceptance_checklist.md` | Real webcam and desktop: lighting, orientation, elevated windows, DPI/multi-monitor, hotkey, sleep/lock, false triggers |

### 15.3 Evaluation

Accuracy, confusion, latency and false-trigger acceptance criteria are
measured with `tools/evaluate_recognition.py` per §7.7, never by
impression. Reports are archived with each release.

### 15.4 Architecture tests

The rules of §3.1 that concern imports and forbidden constructs are
executable tests, so a violation fails CI rather than relying on review.
`test_import_rules.py` parses every module's imports and asserts that
the forbidden edges listed in R1, R2, R4, R9 and R10 do not exist,
including transitive paths from `ui/`, `gestures/`, `camera/` and
`services/diagnostic_sink.py` to the dispatcher, executor, gate and
Windows adapters.

------------------------------------------------------------------------

## 16. Implementation and verification milestones

These are implementation milestones, not separate architectural systems.
Build in dependency order and keep the application **runnable after each
milestone** (from M1 onward the shell launches into `STOPPED`). The
safety boundary (gate, sinks, stop paths) is built in M2, **before any
executor exists**.

| # | Milestone | Deliverables | Definition of done |
|---|---|---|---|
| **M0** | Feasibility spike | Pin dependencies; MediaPipe Tasks `HandLandmarker` on Python 3.11 Windows; capture and tracking FPS at 640 × 480; DTW prototype cost; `SendInput` and `RegisterHotKey` prototypes against a scratch window; camera backend and probing decisions | Benchmark report against §12.1 (or a documented lever); Appendix A updated; `numba` yes/no decided; version pins committed |
| **M1** | Foundation and persistence | Domain models, ports, `SettingsSchema`, paths, logging, event bus, database (connection, migrator, `0001`, codecs, repositories), composition root, window shell with status bar, fakes, architecture tests | CRUD tests on a temporary database; migrator tests; architecture tests green; app launches in `STOPPED` |
| **M2** | Camera, tracking, runtime controller | Camera manager, capture worker, OpenCV and MediaPipe backends, `QtBridge`, Live Monitor preview, `RuntimeController` with the full transition table, `ExecutionGate`, `DiagnosticSink`, global hotkey, session events, LIVE overlay and tray | Clean camera shutdown ≤ 2 s; UI stalls p99 ≤ 50 ms; every transition-table cell tested; hotkey → gate latency measured; stop path works with nothing to execute |
| **M3** | **Static vertical slice** | Hand selector, normalizer, feature extractor, static recorder and validator, static matcher, calibration and collision check, trigger validator, recognition engine, template loader and snapshot service, Gesture Studio (static), Testing tab with per-frame diagnostics | **One recorded static gesture is recognized in Test mode**; synthetic fixtures pass; evaluation tool runs on fixtures |
| **M4** | Dynamic gestures | Resampler, segmenter, dynamic recorder, DTW matcher, arbitration, consistency and collision checks, Gesture Studio (dynamic) | DTW within §12.1 budgets; speed-variation and arbitration tests pass; evaluation tool reports dynamic metrics |
| **M5** | Workflow configuration | Action registry and actions (against the fake adapter), `WorkflowService`, resolver, preview/dry-run, workflow snapshot, approved applications, Workflow Studio, Testing "would run" | Persistence, resolver and registry tests; acknowledgement flow; UI smoke tests |
| **M6** | Live execution | Windows adapters, context service, `LiveSink`, dispatcher, executor, rate/failure limits, watchdog, automatic exits, execution logging, confirmation dialogs. SAFE actions first, then ELEVATED | Live-execution and stop-behavior tests; manual harmless-action run on the target machine; stop latency p95 ≤ 100 ms; elevated-target test |
| **M7** | Complete UI | All §14 states, Settings, §13.3 messages, onboarding, keyboard navigation | UI smoke tests; manual UX checklist; control gating verified |
| **M8** | Hardening and release | Evaluation per §7.7, benchmark report, ≥ 3 h negative-data false-trigger run, clean-install test on a fresh Windows user profile, README with limitations, demo recording | Every criterion in §17 passes |

Packaging (PyInstaller) follows v1 and is out of scope for these
milestones.

------------------------------------------------------------------------

## 17. Acceptance criteria

The first complete release is acceptable when every criterion below
holds. Each is measurable and names its verification method.

| ID | Criterion | Verification |
|---|---|---|
| AC-01 | Static and dynamic gestures can be recorded, named, saved, loaded, renamed, re-recorded, have their sensitivity adjusted, and deleted (cascade) | Integration tests + manual checklist |
| AC-02 | Saved gestures, workflows and settings survive restart; the rebuilt snapshots are identical | `test_gesture_persistence`, `test_workflow_persistence`, snapshot-equality test |
| AC-03 | Editing or replacing a workflow leaves the gesture's samples and `template_revision` unchanged | Persistence test comparing sample bytes |
| AC-04 | **Static accuracy:** per gesture ≥ 95 % true accept over ≥ 50 attempts across 3 lighting conditions; misclassification as another gesture ≤ 2 % | `evaluate_recognition.py`, Wilson 95 % intervals reported |
| AC-05 | **Dynamic accuracy:** per gesture ≥ 90 % true accept over ≥ 30 attempts; misclassification ≤ 5 % | `evaluate_recognition.py` |
| AC-06 | A held pose produces exactly 1 event; it can fire again only after release and cooldown | `test_trigger_validator`, `test_live_execution` (10 s held-pose replay) |
| AC-07 | Latency targets of §12.1 (frame, static trigger, dynamic trigger) are met | `benchmark_pipeline.py` report |
| AC-08 | **False triggers ≤ 1 per hour:** 0 events in ≥ 3 h of negative landmark data, plus a 1-hour manual Live session with harmless actions | `evaluate_recognition.py` + manual log review |
| AC-09 | Test mode never executes: zero adapter calls in a full-pipeline run; no import path from `DiagnosticSink`/`ui/`/`gestures/` to the executor, dispatcher, gate or adapters | `test_testing_mode`, `test_import_rules`, fault-injection test |
| AC-10 | Live mode executes at most once per accepted trigger; busy triggers are dropped and logged | `test_live_execution`, `test_execution_dispatcher` |
| AC-11 | Workflow resolution is deterministic: app-specific beats default; the strict-per-app switch behaves as specified; ambiguity is impossible by constraint | `test_workflow_resolver`, constraint test |
| AC-12 | Unknown actions and invalid parameters are rejected at save, snapshot and run time; ELEVATED workflows without acknowledgement do not run; sensitive chords require acknowledgement | `test_action_registry`, `test_workflow_executor` |
| AC-13 | Stop: hotkey → gate closed p95 ≤ 100 ms; after the gate closes no new action starts (1 000 randomized stop times); queued work cancelled 100 %; `delay` actions end within 100 ms | `test_stop_behavior`, `test_execution_gate`, logged timestamps in manual run |
| AC-14 | Every automatic exit in §4.3 ends in `STOPPED` with a logged reason | `test_runtime_controller` |
| AC-15 | Camera loss, tracker error or workflow exception never crashes the UI and ends in a safe, explained state | Fault-injection tests |
| AC-16 | No `eval`/`exec`/`pickle`/`shell=True`, no network imports; executable paths and key names validated; only approved applications launchable | Architecture tests + unit tests |
| AC-17 | Migrations upgrade from fixture databases with a backup; a newer database is refused; `PRAGMA foreign_key_check` is clean after deletes | `test_migrator`, persistence tests |
| AC-18 | Performance targets of §12.1 are met on the reference machine, or the documented lever was applied and re-measured | Archived benchmark report |
| AC-19 | Automated tests use fake camera/adapters and perform zero real desktop actions | Autouse guard fixture; CI run |
| AC-20 | README documents setup, camera permissions, usage, data location, limitations (elevated windows, UWP, DPI, fullscreen games) and the threat model summary; the manual checklist is completed and archived | Review |
| AC-21 | The mode is always visible; control gating matches §14.3; the core flow is operable by keyboard alone | `test_ui_smoke` + manual |

------------------------------------------------------------------------

## 18. Important design decisions

1.  **Template matching first, not custom model training.** Normalized
    landmark templates (static) and motion-segmented DTW (dynamic).
    Evaluate with §7.7; a learned classifier is considered only if AC-04
    or AC-05 cannot be met after documented tuning.
2.  **One shared recognition engine.** Test and Live differ only in the
    `EventSink`; there is no second matching implementation.
3.  **Structural mode boundary.** Test mode is execution-free by wiring,
    by the gate, and by tests (§4.6) — not by hidden buttons.
4.  **Configuration is data.** Gestures and workflows are structured
    records; action types map to trusted implementations; stored values
    are never evaluated.
5.  **SQLite with WAL and numbered migrations** keeps setup simple for a
    single-user desktop application and makes schema change safe.
6.  **Windows-first, behind ports.** The OS is touched only by
    `adapters/windows/`; everything else depends on `domain/ports.py`,
    which also enables fakes and a later port to other platforms.
7.  **Vertical slice early.** M3 gets one recorded gesture recognized in
    Test mode before the action catalog or UI polish.
8.  **Raw landmarks are stored; features are derived.** Representation
    changes do not force re-recording.
9.  **Orientation-sensitive, hand-specific, no mirroring in v1.** It
    distinguishes thumbs-up from thumbs-down and avoids mirror semantics
    for directional movements.
10. **Dynamic matching happens once per motion segment**, with resampling,
    a band-limited DTW and early abandoning, so cost is bounded and
    independent of frame rate.
11. **Drop while busy; at-most-once.** Safer than queuing surprise
    actions; failures are never retried automatically.
12. **Risk tiers and acknowledgement, approved applications, relative
    mouse targets.** Guardrails against mistakes and fragile coordinates.
13. **Stop works from anywhere.** Global hotkey, overlay and tray; Live
    mode refuses to start without a working hotkey.
14. **MediaPipe Tasks `VIDEO` mode with a bundled, hash-verified model.**
    Deterministic threading, offline operation.
15. **A small `SendInput` wrapper instead of PyAutoGUI**, behind the same
    adapter port (PyAutoGUI remains a documented fallback).
16. **Defaults are hypotheses.** Appendix A values change only through
    the §7.7 evaluation protocol and a recorded before/after report.

------------------------------------------------------------------------

## Appendix A — Default parameters

"Exposed": **U** = Settings tab, **A** = Settings → Advanced, **C** =
constant in `constants.py`/schema, **H** = hard limit (not configurable).

### Camera and tracking

| Name | Default | Range / unit | Exposed |
|---|---|---|---|
| `camera_backend` | `DSHOW` (fallback `MSMF`) | DSHOW / MSMF | U |
| `camera_index` | 0 | 0–4 | U |
| `capture_width` × `capture_height` | 640 × 480 | px | A |
| `capture_fps` | 30 | fps | A |
| `min_hand_detection_confidence` / `min_hand_presence_confidence` / `min_tracking_confidence` | 0.6 / 0.6 / 0.6 | 0–1 | A |
| `tracked_hand` | `RIGHT` | RIGHT / LEFT / EITHER | U |
| `preview_fps` | 20 | 5–30 fps | A |
| `min_effective_fps` | 15 | fps | C |
| `recording_queue_frames` | 300 | frames | C |

### Static gestures

| Name | Default | Range / unit | Exposed |
|---|---|---|---|
| `static_countdown_ms` | 3000 | ms | A |
| `static_capture_window_ms` | 1500 | ms | A |
| `static_min_valid_frames` | 20 | frames | C |
| `static_max_samples` | 30 | samples | C |
| `static_capture_max_deviation` | 0.10 | palm units | C |
| `static_max_speed` | 0.35 | palm units/s | A |
| `threshold_slack` | 1.5 | × p95 | C |
| `static_threshold_min` / `static_threshold_max` | 0.06 / 0.30 | palm units | C |
| `margin_ratio` | 0.80 | d_best / d_second | A |
| `sensitivity` (global) | 1.0 | 0.5–1.5 | U |
| `threshold_scale` (per gesture) | 1.0 | 0.5–1.5 | U |

### Dynamic gestures

| Name | Default | Range / unit | Exposed |
|---|---|---|---|
| `dynamic_max_window_ms` | 3000 | 1000–5000 ms | U |
| `dynamic_min_duration_ms` | 400 | ms | C |
| `dynamic_samples_required` | 3 | 3–5 | C |
| `min_motion_path_palm` | 1.5 | palm units | C |
| `max_missing_ratio` | 0.20 | fraction | C |
| `max_interp_gap_ms` | 150 | ms | C |
| `motion_start_speed` / `motion_start_ms` | 0.8 / 100 | palm units/s / ms | A |
| `motion_end_speed` / `end_idle_ms` | 0.3 / 250 | palm units/s / ms | A |
| `segment_lookback_ms` | 300 | ms | C |
| `max_segment_ms` | 4500 (= 1.5 × window; cap 6000) | ms | C |
| `match_rate_hz` | 15 | Hz | C |
| `dtw_band_fraction` | 0.25 | of longer sequence | C |
| `dynamic_shape_weight` / `dynamic_trajectory_weight` | 1.0 / 2.0 | weights | C |
| `dynamic_threshold_slack` | 1.3 | × max pairwise | C |
| `dynamic_d_min` / `dynamic_d_max` | 0.08 / 0.5 | weighted palm units | C |
| `dynamic_margin_ratio` | 0.85 | d_best / d_second | A |

### Trigger validation

| Name | Default | Range / unit | Exposed |
|---|---|---|---|
| `stable_duration_ms` | 400 | 200–1500 ms | A |
| `max_gap_ms` | 120 | ms | C |
| `rearm_release_ms` | 300 | ms | A |
| `cooldown_ms` | 1500 | 500–10 000 ms | A |
| `global_cooldown_ms` | 500 | ms | A |

### Execution and safety

| Name | Default | Range / unit | Exposed |
|---|---|---|---|
| `overlap_policy` | `DROP_WHILE_BUSY` | fixed in v1 | H |
| `request_ttl_ms` | 1500 | ms | C |
| `max_actions_per_workflow` | 20 | actions | H |
| `max_total_delay_ms` | 30 000 | ms | H |
| `workflow_watchdog_ms` | 60 000 | ms | C |
| `action_timeout_ms` | 5000 | ms | C |
| `max_executions_per_minute` | 20 | 1–120 | U |
| `consecutive_failure_limit` | 3 | 1–10 | U |
| `pipeline_stall_ms` | 3000 | ms | C |
| `interruptible_poll_ms` | 50 | ms | C |
| `suppress_when_self_foreground` | true | bool | U |
| `use_default_when_no_app_match` | true | bool | U |
| `stop_hotkey` | `Ctrl+Alt+Shift+X` | key chord | U |
| `launch_mode` | `STOPPED` | STOPPED / TEST | U |

### Logging and database

| Name | Default | Range / unit | Exposed |
|---|---|---|---|
| `log_retention_rows` / `log_retention_days` | 10 000 / 30 | rows / days | U |
| `verbose_recognition_log` | false (≤ 5 rows/s when on) | bool | U |
| `log_window_titles` | false | bool | U |
| `diagnostics_ring_buffer` | 500 | entries | C |
| `busy_timeout_ms` | 5000 | ms | C |
| `backup_keep` / `backup_interval_days` | 5 / 7 | count / days | C |

## Appendix B — Enumerations

| Enum | Values |
|---|---|
| `RuntimeMode` | `STOPPED`, `RECORDING`, `TEST`, `LIVE` |
| `GestureType` / `Hand` | `STATIC`, `DYNAMIC` / `LEFT`, `RIGHT` |
| `RiskTier` | `SAFE`, `ELEVATED` |
| `TriggerState` | `IDLE`, `ACCUMULATING`, `FIRED`, `COOLDOWN`, `REARMING` |
| `RejectReason` | `NO_HAND`, `WRONG_HAND`, `AMBIGUOUS_HANDS`, `DEGENERATE_HAND`, `TOO_FEW_VALID_FRAMES`, `HAND_MOVING`, `LOW_FPS`, `TOO_SHORT`, `INSUFFICIENT_MOTION`, `TOO_MANY_GAPS`, `INCONSISTENT_SAMPLES`, `TRACKING_LOST`, `ABOVE_THRESHOLD`, `AMBIGUOUS_MARGIN`, `MOVING`, `SEGMENT_NO_MATCH` |
| `ExecutionStatus` | `SUCCEEDED`, `FAILED`, `CANCELLED`, `TIMED_OUT`, `DROPPED_NOT_LIVE`, `DROPPED_BUSY`, `EXPIRED`, `SUPPRESSED_SELF_FOREGROUND`, `NO_WORKFLOW`, `GESTURE_DISABLED`, `SKIPPED_WORKFLOW_DISABLED`, `SKIPPED_CONTEXT_CHANGED`, `SKIPPED_ELEVATED_TARGET` |
| Action error codes | `ACTION_REJECTED`, `ADAPTER_ERROR`, `TIMEOUT`, `TARGET_NOT_FOUND`, `APP_NOT_APPROVED` |
| Pipeline errors | `CAMERA_NOT_FOUND`, `CAMERA_BUSY`, `CAMERA_NO_FRAMES`, `CAMERA_LOST`, `TRACKER_MODEL_INVALID`, `TRACKER_ERROR` |
| Snapshot exclusion reasons | `NEEDS_RERECORDING`, `INVALID_LANDMARKS`, `UNSUPPORTED_TRACKER_MODEL`, `INVALID_WORKFLOW`, `RISK_NOT_ACKNOWLEDGED`, `MISSING_APP_REF` |

------------------------------------------------------------------------

## Final architecture summary

The application has five UI tabs — **Live Monitor, Gesture Studio,
Workflow Studio, Testing Studio and Settings** — plus a persistent
status bar, a LIVE overlay and a tray icon. Underneath them, one shared
camera/tracking pipeline feeds one recognition engine. The engine emits a
`FrameAnalysis` for every frame and a `RecognitionEvent` only after
trigger validation. `RuntimeController` selects the sink: in `STOPPED`,
`RECORDING` and `TEST` the `DiagnosticSink` displays and logs and can only
*describe* what would run; in `LIVE` the `LiveSink` obtains a gate
admission, captures the foreground application, resolves a context-aware
workflow and hands an immutable definition to a single execution thread
that re-checks the gate before every action and acts only through a
Windows adapter. SQLite persists raw gesture landmarks, workflow
definitions, settings and bounded logs.

The separation of recognition from execution, enforced by a gate, by
wiring and by architecture tests, together with stop controls that work
from anywhere on the desktop, is the central constraint. It makes the
system customizable, testable, safer to operate and extensible without
turning the codebase into one large script.
