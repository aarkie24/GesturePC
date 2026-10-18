"""Unit tests for SettingsSchema validation and defaults."""

from app.config import SettingsSchema


def test_schema_defaults_match_appendix_a():
    schema = SettingsSchema()
    assert schema.camera_backend == "DSHOW"
    assert schema.camera_index == 0
    assert schema.capture_width == 640
    assert schema.capture_height == 480
    assert schema.capture_fps == 30
    assert schema.tracked_hand == "RIGHT"
    assert schema.preview_fps == 20
    assert schema.static_countdown_ms == 3000
    assert schema.margin_ratio == 0.80
    assert schema.dtw_band_fraction == 0.25
    assert schema.stop_hotkey == "Ctrl+Alt+Shift+X"
    assert schema.launch_mode == "STOPPED"


def test_load_validated_applies_overrides():
    raw_dict = {
        "camera_index": 2,
        "preview_fps": 15,
        "tracked_hand": "LEFT",
        "stop_hotkey": "Ctrl+Alt+Shift+Z",
    }
    schema = SettingsSchema.load_validated(raw_dict)
    assert schema.camera_index == 2
    assert schema.preview_fps == 15
    assert schema.tracked_hand == "LEFT"
    assert schema.stop_hotkey == "Ctrl+Alt+Shift+Z"
    # Unspecified fields stay default
    assert schema.camera_backend == "DSHOW"


def test_load_validated_falls_back_on_invalid_values():
    raw_dict = {
        "camera_index": 999,  # Out of range (max 4)
        "camera_backend": "INVALID_BACKEND",  # Literal['DSHOW', 'MSMF']
        "capture_fps": 5,  # Out of range (min 10)
        "tracked_hand": "RIGHT",  # Valid
    }
    schema = SettingsSchema.load_validated(raw_dict)
    # Invalid values must safely fall back to default
    assert schema.camera_index == 0
    assert schema.camera_backend == "DSHOW"
    assert schema.capture_fps == 30
    # Valid value preserved
    assert schema.tracked_hand == "RIGHT"
