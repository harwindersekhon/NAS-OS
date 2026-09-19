"""SQLAlchemy models for nasos.db (SQLite, WAL mode, opened only by the web
process — PLAN.md §4). Tables land milestone by milestone; M1 added sessions,
audit_log, settings, notifications; M2 adds users, groups_meta, volumes,
shares, share_permissions, jobs, managed_files. SQLite is fast enough that
these are read/written with plain sync sessions from FastAPI `def` (not
`async def`) routes, which Starlette already runs off the event loop — no
explicit to_thread needed (contrast with genuinely blocking system
libraries, see config.py's dependency notes).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    uid: Mapped[int]
    username: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))
    created: Mapped[dt.datetime] = mapped_column(default=utcnow)
    last_seen: Mapped[dt.datetime] = mapped_column(default=utcnow)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(default=utcnow, index=True)
    username: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(16))
    ip: Mapped[str | None] = mapped_column(String(45))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int]
    detail: Mapped[str | None] = mapped_column(String(1024))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(String(64))
    read_at: Mapped[dt.datetime | None] = mapped_column(default=None)


class User(Base):
    """The "NAS-managed" marker (PLAN.md §3): a row here plus membership in
    `nasos-users` is what makes a POSIX account visible/editable in the GUI.
    Pre-existing accounts get a row via the admin "Import" action instead of
    `users.create`, with `created_by_nasos=False`.
    """

    __tablename__ = "users"

    uid: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    smb_enabled: Mapped[bool] = mapped_column(default=True)
    ftp_enabled: Mapped[bool] = mapped_column(default=False)
    created_by_nasos: Mapped[bool] = mapped_column(default=True)
    smb_password_synced: Mapped[bool] = mapped_column(default=True)


class GroupMeta(Base):
    """POSIX groups have no description field of their own; this is NAS-OS's
    metadata about groups it manages, keyed by gid like `users` is by uid.
    """

    __tablename__ = "groups_meta"

    gid: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    created_by_nasos: Mapped[bool] = mapped_column(default=True)


class Volume(Base):
    """A registered mountpoint shares can live under. M2 only supports
    registering an *existing* mounted filesystem (PLAN.md §6, M2 gate:
    "manual volume registration"); `managed=True` once Storage Manager
    (Milestone 4) owns the mount unit for it — the `device`/`uuid`/
    `raid_level`/`array_name`/`disk_serials` columns are only populated for
    those NAS-OS-created volumes (null for M2's manually-registered ones).
    """

    __tablename__ = "volumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    mountpoint: Mapped[str] = mapped_column(String(255), unique=True)
    filesystem: Mapped[str] = mapped_column(String(16))
    managed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
    device: Mapped[str | None] = mapped_column(String(255), default=None)
    """The LV (or single-disk partition) block device, e.g.
    /dev/nasos_pool1/volume1 — what the mount unit's `What=` resolves to a
    UUID from."""
    uuid: Mapped[str | None] = mapped_column(String(64), default=None)
    raid_level: Mapped[str | None] = mapped_column(String(16), default=None)
    """"basic" (single disk, no md) or an mdadm level ("1", "5", "6", "10")."""
    array_name: Mapped[str | None] = mapped_column(String(64), default=None)
    """mdadm array name (e.g. "pool1"), null for "basic" (single-disk)."""
    disk_serials: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    """Physical disk serials backing this volume, for the guard's protected-
    set check and the Storage Manager UI."""


class DiskSeen(Base):
    """One row per physical disk NAS-OS has ever observed (by serial), so
    hotplug add/remove and periodic SMART polling (PLAN.md §6: "SMART every
    30 min + on demand with threshold notifications") have somewhere to
    track state across restarts and de-duplicate repeat notifications for a
    health state that hasn't changed since the last poll.
    """

    __tablename__ = "disks_seen"

    serial: Mapped[str] = mapped_column(String(128), primary_key=True)
    path: Mapped[str] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    size: Mapped[int | None]
    first_seen_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    last_health: Mapped[str | None] = mapped_column(String(16), default=None)
    """"ok" | "warning" | "critical" | "unknown" — the SMART health as of
    the last poll; a Notification is only created when this *changes*."""


class Share(Base):
    __tablename__ = "shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    volume_id: Mapped[int] = mapped_column(ForeignKey("volumes.id"))
    path: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(String(255))
    smb_enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class SharePermission(Base):
    """rw -> u/g:x:rwx (+default); ro -> r-x (+default); a row's absence is
    "none" — removing access means deleting the row, not storing level="none"
    (PLAN.md §3's ACL rendering treats an explicit "none" the same as no
    entry, but the UI needs to represent "set to none" as a transient choice
    before the row is deleted, hence level still includes it here).
    """

    __tablename__ = "share_permissions"
    __table_args__ = (UniqueConstraint("share_id", "principal_type", "principal"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    share_id: Mapped[int] = mapped_column(ForeignKey("shares.id", ondelete="CASCADE"), index=True)
    principal_type: Mapped[str] = mapped_column(String(8))  # "user" | "group"
    principal: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(8))  # "rw" | "ro" | "none"


class Job(Base):
    """The web's mirror of agent-run job state (PLAN.md §4): the agent is the
    source of truth while a job runs (in-memory + jobs.jsonl); the web
    updates this row from job.progress events and reconciles via jobs.list
    on startup, so the Log Center / job history UI never touches the agent
    directly.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))  # queued|running|done|failed|cancelled
    progress: Mapped[float] = mapped_column(default=0.0)
    message: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Upload(Base):
    """A tus upload in progress or recently finished (PLAN.md §5: "tus 1.0
    core ... hourly GC of stale .part files"). The DB row is web-side
    bookkeeping only — the bytes are written by the fileworker (a different
    process/uid), so `offset` here is a convenience cache updated after each
    successful PATCH, never the authority a resume decision is made from;
    that's always the fileworker's own view of how many bytes actually
    landed on disk (`files.upload_offset`, queried live on every HEAD).
    """

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    uid: Mapped[int]
    dest_path: Mapped[str] = mapped_column(String(255))
    size: Mapped[int]
    offset: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(16), default="uploading")
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ManagedFileRecord(Base):
    """sha256 of the content NAS-OS last wrote to `path` (PLAN.md §2): a
    mismatch against the file's current on-disk hash means something other
    than NAS-OS touched it since, and the UI offers a Regenerate button.
    """

    __tablename__ = "managed_files"

    path: Mapped[str] = mapped_column(String(255), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)
