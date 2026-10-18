-- 0001_initial.sql: Initial database schema for Gesture PC
-- Single source of truth for database structure

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
