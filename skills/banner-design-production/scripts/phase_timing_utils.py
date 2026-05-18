#!/usr/bin/env python3
"""Small helpers for writing phase timing events for banner design production runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def timing_path(run_dir: Path) -> Path:
    return run_dir / "phase_timings.json"


def load_timings(run_dir: Path, run_id: str | None = None) -> dict[str, Any]:
    path = timing_path(run_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    created_at = utc_now_iso()
    return {
        "run_id": run_id or run_dir.name,
        "created_at": created_at,
        "updated_at": created_at,
        "events": [],
        "latest": {},
    }


def save_timings(run_dir: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now_iso()
    path = timing_path(run_dir)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def init_phase_timings(run_dir: Path, run_id: str) -> None:
    path = timing_path(run_dir)
    if path.exists():
        return
    save_timings(
        run_dir,
        {
            "run_id": run_id,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "events": [],
            "latest": {},
        },
    )


def record_phase_event(
    run_dir: Path,
    phase: str,
    step: str,
    status: str = "completed",
    started_at: str | None = None,
    ended_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    data = load_timings(run_dir)
    end = parse_iso(ended_at) or utc_now()
    start = parse_iso(started_at)
    event: dict[str, Any] = {
        "phase": phase,
        "step": step,
        "status": status,
        "started_at": started_at,
        "ended_at": end.isoformat(),
    }
    if start is not None:
        event["duration_seconds"] = round((end - start).total_seconds(), 3)
    if extra:
        event["extra"] = extra
    data.setdefault("events", []).append(event)
    data.setdefault("latest", {})[f"{phase}.{step}"] = event
    save_timings(run_dir, data)
