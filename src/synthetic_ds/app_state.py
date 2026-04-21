from __future__ import annotations

import json
import platform
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class JobRecord(BaseModel):
    job_id: str
    source_dir: str
    provider: str
    model: str
    status: str
    stage: str
    percent: float
    current_file: str | None = None
    message: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    config: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    artifacts_dir: str


class JobEvent(BaseModel):
    event_id: int
    job_id: str
    stage: str
    status: str
    percent: float
    message: str | None = None
    current_file: str | None = None
    created_at: str


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists jobs (
                    job_id text primary key,
                    source_dir text not null,
                    provider text not null,
                    model text not null,
                    status text not null,
                    stage text not null,
                    percent real not null,
                    current_file text,
                    message text,
                    error text,
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp,
                    config_json text not null,
                    stats_json text not null default '{}',
                    control_action text,
                    artifacts_dir text not null
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("pragma table_info(jobs)").fetchall()
            }
            if "stats_json" not in columns:
                connection.execute("alter table jobs add column stats_json text not null default '{}'")
            if "control_action" not in columns:
                connection.execute("alter table jobs add column control_action text")
            connection.execute(
                """
                create table if not exists job_events (
                    event_id integer primary key autoincrement,
                    job_id text not null,
                    stage text not null,
                    status text not null,
                    percent real not null,
                    message text,
                    current_file text,
                    created_at text not null default current_timestamp
                )
                """
            )
            connection.commit()

    def create_job(
        self,
        *,
        source_dir: str,
        provider: str,
        model: str,
        config: dict[str, Any],
        artifacts_dir: str,
        job_id: str | None = None,
    ) -> str:
        job_id = job_id or uuid.uuid4().hex[:12]
        with self._connect() as connection:
            connection.execute(
                """
                insert into jobs (
                    job_id, source_dir, provider, model, status, stage, percent, config_json, stats_json, artifacts_dir
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    source_dir,
                    provider,
                    model,
                    "queued",
                    "queued",
                    0.0,
                    json.dumps(config, ensure_ascii=True),
                    json.dumps({}, ensure_ascii=True),
                    artifacts_dir,
                ),
            )
            connection.execute(
                """
                insert into job_events (job_id, stage, status, percent, message)
                values (?, ?, ?, ?, ?)
                """,
                (job_id, "queued", "queued", 0.0, "Job created"),
            )
            connection.commit()
        return job_id

    def update_progress(
        self,
        job_id: str,
        *,
        stage: str,
        status: str,
        percent: float,
        current_file: str | None = None,
        message: str | None = None,
        error: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute("select stats_json from jobs where job_id = ?", (job_id,)).fetchone()
            current_stats = json.loads(row["stats_json"]) if row and row["stats_json"] else {}
            next_stats = stats if stats is not None else current_stats
            connection.execute(
                """
                update jobs
                set stage = ?, status = ?, percent = ?, current_file = ?, message = ?, error = ?, stats_json = ?, updated_at = current_timestamp
                where job_id = ?
                """,
                (stage, status, percent, current_file, message, error, json.dumps(next_stats, ensure_ascii=True), job_id),
            )
            connection.execute(
                """
                insert into job_events (job_id, stage, status, percent, message, current_file)
                values (?, ?, ?, ?, ?, ?)
                """,
                (job_id, stage, status, percent, message, current_file),
            )
            connection.commit()

    def set_control_action(self, job_id: str, action: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "update jobs set control_action = ?, updated_at = current_timestamp where job_id = ?",
                (action, job_id),
            )
            connection.commit()

    def get_control_action(self, job_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("select control_action from jobs where job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return row["control_action"]

    def clear_control_action(self, job_id: str) -> None:
        self.set_control_action(job_id, None)

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("select * from jobs where job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._job_from_row(row)

    def list_jobs(self, limit: int = 20) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "select * from jobs order by datetime(created_at) desc, rowid desc limit ?",
                (limit,),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def list_events(self, job_id: str, after_event_id: int = 0) -> list[JobEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select * from job_events
                where job_id = ? and event_id > ?
                order by event_id asc
                """,
                (job_id, after_event_id),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def active_job(self) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                select * from jobs
                where status in ('queued', 'running', 'pausing', 'paused', 'resuming')
                order by datetime(created_at) asc, rowid asc
                limit 1
                """
            ).fetchone()
        if row is None:
            return None
        return self._job_from_row(row)

    def _job_from_row(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            source_dir=row["source_dir"],
            provider=row["provider"],
            model=row["model"],
            status=row["status"],
            stage=row["stage"],
            percent=float(row["percent"]),
            current_file=row["current_file"],
            message=row["message"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            config=json.loads(row["config_json"]),
            stats=json.loads(row["stats_json"] or "{}"),
            artifacts_dir=row["artifacts_dir"],
        )

    def _event_from_row(self, row: sqlite3.Row) -> JobEvent:
        return JobEvent(
            event_id=int(row["event_id"]),
            job_id=row["job_id"],
            stage=row["stage"],
            status=row["status"],
            percent=float(row["percent"]),
            message=row["message"],
            current_file=row["current_file"],
            created_at=row["created_at"],
        )


def default_app_state_dir() -> Path:
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library" / "Application Support" / "synthetic-ds"
    return home / ".local" / "state" / "synthetic-ds"
