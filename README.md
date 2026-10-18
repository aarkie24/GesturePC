t# Gesture PC

<p align="center">
  <strong>Offline, Context-Aware Gesture Automation for Windows</strong><br>
  <em>Prediction prepares. Gestures execute.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11" />
  <img src="https://img.shields.io/badge/Qt_6-PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white" alt="PySide6" />
  <img src="https://img.shields.io/badge/MediaPipe-Tasks_API-4285F4?style=for-the-badge&logo=google&logoColor=white" alt="MediaPipe Tasks" />
  <img src="https://img.shields.io/badge/OpenCV-Headless-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white" alt="OpenCV" />
  <img src="https://img.shields.io/badge/Storage-SQLite_WAL-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite WAL" />
  <img src="https://img.shields.io/badge/Platform-Windows_10%2F11-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Windows" />
  <img src="https://img.shields.io/badge/Architecture-Enforced_Safety-brightgreen?style=for-the-badge" alt="Safety Boundary" />
</p>

---

## Overview

**Gesture PC** is a high-performance, customizable desktop automation application for Windows. It enables users to record custom static hand poses and dynamic hand gestures, bind rich multi-action workflows to them, safely test recognition without firing unintended actions, and run those workflows in real time with hardware-backed safety controls.

Unlike simple automation scripts that blindly map poses to keystrokes, Gesture PC is engineered around **deliberate safety**, **context awareness**, and **zero-latency control**.

### Core Principles

1. **Gestures remain the primary control mechanism:** The user is always in control. Automation triggers deliberately, never spontaneously or unpredictably.
2. **Context makes automation useful:** A gesture can trigger default global behaviors or adapt specifically to the active foreground application (e.g., browser vs. IDE vs. terminal).
3. **Safety by architectural boundary:** Test mode is physically incapable of executing desktop actions by structural wiring, not by disabled buttons. Automation can be halted instantly from anywhere via a dedicated OS-level emergency stop hotkey.
4. **Strict offline privacy:** Zero telemetry, zero cloud synchronization, zero network calls. All models, migrations, and landmark data stay on the local machine.

---

## Architectural Safety & Data Flow

Gesture PC enforces a strict unidirectional pipeline separated by an `ExecutionGate` and specialized `EventSink`s:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. PySide6 Desktop UI  (Main UI Thread)                                     │
│ Live Monitor | Gesture Studio | Workflow Studio | Testing Studio | Settings │
│ Persistent status bar, Stop button, LIVE overlay widget, system-tray icon   │
└──────────────────────────┬───────────────────────▲──────────────────────────┘
                           │ UI Commands           │ Qt Signals (Queued Bridge)
                           ▼                       │
┌──────────────────────────────────────────────────┴──────────────────────────┐
│ 2. Application Services & Runtime Controller                                │
│ RuntimeController (STOPPED, RECORDING, TEST, LIVE state machine)            │
│ ExecutionGate (epoch-based admissions & O(1) instantaneous cancellation)     │
│ DiagnosticSink (TEST / RECORDING) ────► Zero execution capability by wiring  │
│ LiveSink (LIVE only) ─────────────────► Single path to desktop execution    │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │ Pipeline Control
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Camera & Recognition Pipeline (Dedicated Background Threads)             │
│ Capture Thread:     OpenCV Backend (DSHOW / MSMF) -> LatestFrameMailbox      │
│ Recognition Thread: MediaPipe Tasks HandLandmarker (synchronous VIDEO mode) │
│                     -> HandSelector -> Normalizer -> Matchers                │
│                     -> TriggerValidator (stability & cooldown enforcement)   │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │ RecognitionEvent (Accepted triggers only)
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. Single-Worker Execution Engine (LIVE Mode Only)                          │
│ ExecutionDispatcher (DROP_WHILE_BUSY policy; at-most-once execution)        │
│ WorkflowExecutor -> Checks Gate epoch & token before EVERY action           │
│ DesktopActionAdapter (Win32 ctypes SendInput) -> Direct OS synthesis        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### The 4 Operational Modes

| Mode | Camera | Tracking | Matching | Active Sink | Gate | Desktop Actions |
|---|---|---|---|---|---|---|
| `STOPPED` | Off | Off | Off | None | Closed | **Never** |
| `RECORDING` | On | On | Off | `DiagnosticSink` | Closed | **Never** |
| `TEST` | On | On | On | `DiagnosticSink` | Closed | **Never** |
| `LIVE` | On | On | On | `LiveSink` | Open | **Admitted only** |

---

## Current Implementation Status

### Milestone 0: Feasibility Spike (Complete)
- [x] Pinned runtime and development dependencies for Python 3.11.
- [x] Verified MediaPipe Tasks API `HandLandmarker` in synchronous `VIDEO` mode on CPU using TensorFlow Lite XNNPACK delegate.
- [x] Bundled local `assets/models/hand_landmarker.task` with SHA-256 integrity verification at startup.
- [x] Measured sustained camera throughput: **29.8 FPS** at 640×480 with $p95 = 48.4\text{ ms}$ capture-to-landmark latency.
- [x] Vectorized Sakoe-Chiba band-limited DTW in pure NumPy: **0.48 ms $p50$** per comparison (10× faster than the 5.0 ms ceiling; eliminated the need for Numba).
- [x] Validated native 64-bit Win32 `SendInput` (40-byte struct layout) and `RegisterHotKey`.

### Milestone 1: Foundation & Persistence (Complete)
- [x] Pure domain layer with immutable frozen dataclasses (`domain/models.py`), enums, events, and port protocols (`domain/ports.py`).
- [x] SQLite database in WAL mode with sequential migrations (`database/migrations/0001_initial.sql`).
- [x] Automated database backup rotation (retaining the 5 newest snapshots).
- [x] Binary BLOB codecs for little-endian `float32` landmark arrays with finite/NaN validation.
- [x] Full repository suite: `GestureRepository`, `WorkflowRepository`, `ApplicationRepository`, `SettingsRepository`, `LogRepository`.
- [x] Pydantic v2 `SettingsSchema` with validation ranges and fallback logic.

### Milestone 2: Camera, Safety & Controls (Complete)
- [x] `CameraManager` and `CaptureWorker` with a thread-safe single-slot `LatestFrameMailbox` (eliminates frame queues and latency drift).
- [x] `ExecutionGate` providing atomic epoch-based admission tickets and instant cancellation.
- [x] `RuntimeController` enforcing the complete 4×4 mode transition table and Live mode entry preconditions.
- [x] Isolated Win32 message pump threads for the global emergency stop hotkey (`Ctrl+Alt+Shift+X`) and Windows session lock/logoff notifications (`WTSRegisterSessionNotification`).
- [x] PySide6 `MainWindow` shell with persistent status bar, vibrant mode indicators, and system tray integration.
- [x] `LiveMonitorTab` featuring real-time camera preview and 21-point hand skeleton overlay.
- [x] Always-on-top floating `LiveOverlay` with immediate Stop button.

### Roadmap to v1.0
- [ ] **Milestone 3 (In Progress):** Static gesture vertical slice (normalizer, 60-dim feature extractor, static template matcher, Gesture Studio recording tab).
- [ ] **Milestone 4:** Dynamic gesture engine (motion segmenter, resampler, banded DTW matcher).
- [ ] **Milestone 5:** Workflow Studio (action catalog, application targeting, dry-run preview).
- [ ] **Milestone 6:** Live execution worker (`LiveSink`, `WorkflowExecutor`, rate limits, watchdog).
- [ ] **Milestone 7:** Complete UI polish (Settings tab, keyboard navigation, onboarding).
- [ ] **Milestone 8:** Accuracy validation, false-trigger stress testing ($\ge 3\text{ hours}$ negative data), and release.

---

## Tech Stack

| Component | Technology | Responsibility |
|---|---|---|
| **Language** | Python 3.11 | Core application and business logic |
| **Desktop GUI** | PySide6 / Qt 6 | Main window, tab views, status bar, floating overlay, tray |
| **Camera Capture** | OpenCV (`cv2.VideoCapture`) | DirectShow (`DSHOW`) capture with Media Foundation (`MSMF`) fallback |
| **Hand Tracking** | MediaPipe Tasks API | Synchronous per-frame 21 3D landmark extraction (`VIDEO` mode) |
| **Tracker Model** | `hand_landmarker.task` | Bundled, SHA-256 verified local model (7.8 MB) |
| **Numerical Math** | NumPy | Coordinate normalization, joint angles, and band-limited DTW |
| **Persistence** | SQLite3 (WAL Mode) | Normalized relational storage for gestures, samples, workflows, and audit logs |
| **Schema Validation** | Pydantic v2 | Strict validation of settings and workflow action parameters |
| **OS Integration** | Win32 API via `ctypes` | `RegisterHotKey`, `SendInput`, `WTSRegisterSessionNotification` |
| **Testing** | `pytest`, `pytest-qt`, `hypothesis` | Unit tests, integration tests, offscreen UI tests, and AST architecture rules |

---

## Project Structure

```text
gesture-pc/
├── main.py                     # Entry point (single-instance lock, composition root)
├── requirements.txt            # Pinned runtime dependencies
├── requirements-dev.txt        # Testing & development dependencies
├── pyproject.toml              # Build metadata & pytest configuration
├── implementationPlan.md       # RFC 2119 architectural specification
├── decisions.md                # Architecture Decision Records (DEC-01 to DEC-24)
├── flow.md                     # Component connectivity and runtime flow map
├── README.md                   # Project overview and documentation
│
├── assets/models/              # Bundled offline tracker models
│   ├── hand_landmarker.task
│   └── MODEL_SHA256.txt
│
├── app/                        # Application composition & configuration
│   ├── application.py          # Composition root (pure dependency injection)
│   ├── config.py               # SettingsSchema (Pydantic v2)
│   ├── constants.py            # Version constants, model IDs, limits
│   ├── logging_config.py       # 5 x 1MB rotating structured logger
│   └── paths.py                # LocalAppData directory resolution
│
├── domain/                     # Pure domain logic (zero GUI/DB/OS imports)
│   ├── models.py               # Immutable frozen dataclasses
│   ├── enums.py                # RuntimeMode, GestureType, RejectReason, etc.
│   ├── events.py               # Typed domain bus events
│   ├── ports.py                # Protocols (CameraBackend, DesktopActionAdapter, etc.)
│   └── exceptions.py           # Domain exception hierarchy
│
├── camera/                     # Camera capture and landmark extraction
│   ├── camera_manager.py       # Hardware handle lifecycle
│   ├── capture_worker.py       # Threaded frame grabber
│   ├── frame_types.py          # LatestFrameMailbox and FramePacket
│   ├── opencv_backend.py       # DSHOW/MSMF VideoCapture implementation
│   ├── mediapipe_backend.py    # HandLandmarker Tasks API wrapper
│   └── hand_tracker.py         # Tracking coordinator
│
├── services/                   # Application coordination & safety
│   ├── runtime_controller.py   # State machine & transition table enforcement
│   ├── execution_gate.py       # Epoch-based admission gate
│   ├── diagnostic_sink.py      # Non-executing sink for TEST/RECORDING
│   └── event_bus.py            # Thread-safe pub/sub bus
│
├── adapters/windows/           # Native Windows adapters
│   ├── global_hotkey.py        # Win32 RegisterHotKey message pump thread
│   └── session_events.py       # Win32 WTSRegisterSessionNotification listener
│
├── database/                   # SQLite persistence layer
│   ├── connection.py           # WAL mode connection factory
│   ├── migrator.py             # Numbered SQL migration runner & backups
│   ├── codecs.py               # Float32 binary landmark array BLOB codecs
│   ├── migrations/
│   │   └── 0001_initial.sql    # Database schema
│   └── repositories/           # Gestures, Workflows, Applications, Settings, Logs
│
├── ui/                         # PySide6 Desktop Interface
│   ├── main_window.py          # Main window shell & status bar
│   ├── qt_bridge.py            # Thread-safe Qt signal bridge
│   ├── tray.py                 # System tray icon with mode display
│   ├── components/
│   │   ├── camera_view.py      # Frame display with 21-landmark skeleton
│   │   ├── status_badge.py     # Vibrant mode badge
│   │   └── live_overlay.py     # Always-on-top floating emergency stop overlay
│   └── tabs/
│       └── live_monitor_tab.py # Live monitor preview & controls
│
├── tools/
│   └── benchmark_pipeline.py   # Reproducible feasibility benchmark runner
│
└── tests/                      # Automated test suite
    ├── architecture/           # AST import boundary & safety rule enforcement
    ├── unit/                   # Codecs, gate, settings, controller tests
    ├── integration/            # Persistence, camera lifecycle, hotkey latency
    └── fakes/                  # FakeCamera, FakeHotkey, FakeClock
```

---

## Getting Started

### Prerequisites

- **OS:** Windows 10 or Windows 11 (64-bit).
- **Python:** Python 3.11.x (verified on Python 3.11.9).
- **Webcam:** Any built-in or USB webcam supporting 640×480 at 30 FPS.

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/aarkie24/GesturePC.git
cd GesturePC

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install runtime dependencies
pip install -r requirements.txt

# Install development & test dependencies (optional)
pip install -r requirements-dev.txt
```

### 2. Running the Application

Launch the desktop interface:

```bash
python main.py
```

- The application starts safely in **`STOPPED`** mode.
- Click **Start Test Mode** in the Live Monitor tab to stream your webcam with the real-time 21-landmark skeleton overlay (safe preview; desktop actions will never fire).
- Press **`Ctrl+Alt+Shift+X`** at any time to trigger the emergency stop.

### 3. Running Benchmarks & Tests

Run the reproducible Milestone 0 feasibility benchmark:

```bash
python tools/benchmark_pipeline.py
```

Run the complete automated test suite (30 tests covering unit, integration, and AST architecture rules):

```bash
pytest -v
```

---

## Architectural Rules (Test-Enforced)

The codebase strictly adheres to architectural rules verified via static AST inspection in `tests/architecture/`:
- **R1:** `ui/` contains zero imports of desktop adapters, execution dispatchers, SQLite, Win32, or OpenCV.
- **R2:** `camera/` and `gestures/` emit only data contracts (`FrameAnalysis`, `RecognitionEvent`) and never touch workflows.
- **R4:** `DiagnosticSink` has zero import paths or references to `ExecutionGate`, `ExecutionDispatcher`, or adapters.
- **R5:** Zero dynamic code execution — no `eval()`, `exec()`, `pickle`, or `shell=True`. All workflow actions are validated Pydantic models.
- **R11:** Strict offline policy — zero imports of `requests`, `urllib.request`, `http.client`, or `socket` in application code.

---

## License

This project is licensed under the Apache 2.0 License.
