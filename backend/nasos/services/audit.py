"""Writes to audit_log — called from a dependency on every mutating route
(PLAN.md §4: "Audit dependency on every mutating route").
"""

from __future__ import annotations

from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import AuditLog


def record(
    db: OrmSession,
    *,
    username: str | None,
    role: str | None,
    ip: str | None,
    method: str,
    path: str,
    action: str,
    status_code: int,
    detail: str | None = None,
) -> None:
    db.add(
        AuditLog(
            username=username,
            role=role,
            ip=ip,
            method=method,
            path=path,
            action=action,
            status_code=status_code,
            detail=detail,
        )
    )
    db.commit()
