# Database Migrations

This directory contains sequential, numbered SQL migrations for Gesture PC.

Rules:
1. Migrations are named `NNNN_<description>.sql`.
2. Each migration must be backward-compatible or include migration logic.
3. The migrator records applied migrations via `PRAGMA user_version`.
4. Prior to running migrations on an existing database, a timestamped snapshot is automatically backed up in `%LOCALAPPDATA%\GesturePC\backups\`.
