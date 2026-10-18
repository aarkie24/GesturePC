"""Application settings schema and validation using Pydantic v2."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.constants import DEFAULT_STOP_HOTKEY

logger = logging.getLogger(__name__)


class SettingsSchema(BaseModel):
    """Single source of truth for all configurable settings."""
    model_config = ConfigDict(extra="ignore", frozen=True)

    # Camera & Tracking
    camera_backend: Literal["DSHOW", "MSMF"] = Field(default="DSHOW", description="OpenCV Windows capture backend")
    camera_index: int = Field(default=0, ge=0, le=4, description="Webcam device index")
    capture_width: int = Field(default=640, ge=320, le=1920)
    capture_height: int = Field(default=480, ge=240, le=1080)
    capture_fps: int = Field(default=30, ge=10, le=60)
    min_hand_detection_confidence: float = Field(default=0.6, ge=0.1, le=1.0)
    min_hand_presence_confidence: float = Field(default=0.6, ge=0.1, le=1.0)
    min_tracking_confidence: float = Field(default=0.6, ge=0.1, le=1.0)
    tracked_hand: Literal["RIGHT", "LEFT", "EITHER"] = Field(default="RIGHT")
    preview_fps: int = Field(default=20, ge=5, le=30)
    recording_queue_frames: int = Field(default=300, ge=60, le=1200)
    min_effective_fps: int = Field(default=15, ge=5, le=30)

    # Static Gestures
    static_countdown_ms: int = Field(default=3000, ge=1000, le=10000)
    static_capture_window_ms: int = Field(default=1500, ge=500, le=5000)
    static_min_valid_frames: int = Field(default=20, ge=5, le=100)
    static_max_samples: int = Field(default=30, ge=10, le=100)
    static_capture_max_deviation: float = Field(default=0.10, ge=0.01, le=0.50)
    static_max_speed: float = Field(default=0.35, ge=0.05, le=2.0)
    threshold_slack: float = Field(default=1.5, ge=1.0, le=3.0)
    static_threshold_min: float = Field(default=0.06, ge=0.01, le=0.20)
    static_threshold_max: float = Field(default=0.30, ge=0.10, le=0.80)
    margin_ratio: float = Field(default=0.80, ge=0.50, le=0.99)
    sensitivity: float = Field(default=1.0, ge=0.5, le=1.5)

    # Dynamic Gestures
    dynamic_max_window_ms: int = Field(default=3000, ge=1000, le=5000)
    dynamic_min_duration_ms: int = Field(default=400, ge=200, le=1000)
    dynamic_samples_required: int = Field(default=3, ge=3, le=5)
    min_motion_path_palm: float = Field(default=1.5, ge=0.5, le=5.0)
    max_missing_ratio: float = Field(default=0.20, ge=0.0, le=0.50)
    max_interp_gap_ms: int = Field(default=150, ge=50, le=500)
    motion_start_speed: float = Field(default=0.8, ge=0.2, le=3.0)
    motion_start_ms: int = Field(default=100, ge=30, le=500)
    motion_end_speed: float = Field(default=0.3, ge=0.05, le=1.0)
    end_idle_ms: int = Field(default=250, ge=100, le=1000)
    segment_lookback_ms: int = Field(default=300, ge=100, le=1000)
    max_segment_ms: int = Field(default=4500, ge=1000, le=6000)
    match_rate_hz: int = Field(default=15, ge=5, le=30)
    dtw_band_fraction: float = Field(default=0.25, ge=0.05, le=0.50)
    dynamic_shape_weight: float = Field(default=1.0, ge=0.1, le=5.0)
    dynamic_trajectory_weight: float = Field(default=2.0, ge=0.1, le=5.0)
    dynamic_threshold_slack: float = Field(default=1.3, ge=1.0, le=3.0)
    dynamic_d_min: float = Field(default=0.08, ge=0.01, le=0.30)
    dynamic_d_max: float = Field(default=0.50, ge=0.20, le=1.50)
    dynamic_margin_ratio: float = Field(default=0.85, ge=0.50, le=0.99)

    # Trigger Validation
    stable_duration_ms: int = Field(default=400, ge=200, le=1500)
    max_gap_ms: int = Field(default=120, ge=30, le=300)
    rearm_release_ms: int = Field(default=300, ge=100, le=1000)
    cooldown_ms: int = Field(default=1500, ge=500, le=10000)
    global_cooldown_ms: int = Field(default=500, ge=100, le=2000)

    # Execution & Safety
    request_ttl_ms: int = Field(default=1500, ge=500, le=5000)
    max_executions_per_minute: int = Field(default=20, ge=1, le=120)
    consecutive_failure_limit: int = Field(default=3, ge=1, le=10)
    pipeline_stall_ms: int = Field(default=3000, ge=1000, le=10000)
    interruptible_poll_ms: int = Field(default=50, ge=10, le=200)
    suppress_when_self_foreground: bool = Field(default=True)
    use_default_when_no_app_match: bool = Field(default=True)
    stop_hotkey: str = Field(default=DEFAULT_STOP_HOTKEY)
    launch_mode: Literal["STOPPED", "TEST"] = Field(default="STOPPED")

    # Logging & Persistence
    log_retention_rows: int = Field(default=10000, ge=1000, le=100000)
    log_retention_days: int = Field(default=30, ge=1, le=365)
    verbose_recognition_log: bool = Field(default=False)
    log_window_titles: bool = Field(default=False)
    busy_timeout_ms: int = Field(default=5000, ge=1000, le=30000)
    backup_keep: int = Field(default=5, ge=1, le=20)
    backup_interval_days: int = Field(default=7, ge=1, le=30)

    @classmethod
    def load_validated(cls, raw_dict: Dict[str, Any]) -> SettingsSchema:
        """Loads and validates a raw key-value dictionary, falling back to schema defaults per key."""
        defaults = cls()
        clean_values: Dict[str, Any] = {}

        for field_name, field_info in cls.model_fields.items():
            if field_name not in raw_dict:
                clean_values[field_name] = getattr(defaults, field_name)
                continue

            raw_val = raw_dict[field_name]
            # Validate individual field
            try:
                temp_obj = cls.model_validate({field_name: raw_val})
                clean_values[field_name] = getattr(temp_obj, field_name)
            except ValidationError as err:
                fallback = getattr(defaults, field_name)
                logger.warning(
                    "Invalid value %r for setting '%s' (%s). Falling back to default: %r",
                    raw_val,
                    field_name,
                    err.errors()[0]["msg"],
                    fallback,
                )
                clean_values[field_name] = fallback

        return cls(**clean_values)
