"""Per-worker state (PLAN.md §1) — files.* handlers' equivalent of
agent/state.py's AgentState, but much smaller: no DB, no distro adapter, no
authenticator. The worker only ever does two things once it's dropped to
the logged-in user's uid/gid — file I/O and jobs — so that's all this holds.

Lives in its own module (not agent/fileworker.py) so agent/handlers/files.py
can import the type without a cycle: fileworker.py imports handlers/files.py
(to populate the registry) exactly the same way agent/main.py imports
agent/handlers for the root agent's registry.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from nasos.agent.jobs import JobRunner
from nasos.config import Settings
from nasos.system.acl import Acl


@dataclass
class UploadHandle:
    dest_path: str
    part_path: str


@dataclass
class WorkerState:
    uid: int
    username: str
    jobs: JobRunner
    acl: Acl
    uploads: dict[str, UploadHandle]
    """upload_id -> handle, for in-flight tus uploads
    (agent/handlers/uploads.py). Lives here rather than in a DB — SQLite is
    opened only by the web process (PLAN.md §4), and this is purely
    in-memory bookkeeping the worker needs between upload_begin and
    upload_complete/abort on the same process."""


def build_worker_state(
    settings: Settings, on_event: Callable[[str, dict[str, object]], None], *, acl: Acl
) -> WorkerState:
    """Dev/test-mode-only in-process WorkerState (PLAN.md §1 "dev mode with
    fakes" applied to Milestone 3): the real fileworker process is never
    spawned there, so web/main.py's dev branch builds one of these instead,
    wired to a second in-process Dispatcher so files.* calls run against a
    WorkerState-shaped object exactly like they would in prod, not the
    AgentState the rest of dev mode's single process otherwise shares.

    No privilege drop: the dev server already runs as the developer's own
    uid, which is exactly what a real fileworker would have dropped to.
    `acl` is passed in rather than constructed here so it's the *same*
    FakeAcl instance as AgentState.acl — one coherent picture of "what ACLs
    are set on this path" whether the edit came from the Shared Folders
    permission matrix (M2) or the File Station ACL editor (M3).
    """
    jobs = JobRunner(f"{settings.state_dir}/fileworker/dev/jobs.jsonl", on_event=on_event)
    return WorkerState(
        uid=os.getuid(), username=os.environ.get("USER", "dev"), jobs=jobs, acl=acl, uploads={}
    )
