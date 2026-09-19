"""POSIX ACL manipulation for shared folders (PLAN.md §3).

The service layer always holds the complete, current permission list for a
share (from `share_permissions`), so the only operation this adapter offers
is `replace_all`: reset the ACL, then restate exactly the given entries.
That's a deliberate two-call sequence — `setfacl -b` (drop every extended
entry back to bare owner/group/other) followed by `setfacl -m` (rebuild from
the given list) — verified live during M2 research: plain `setfacl -m` only
*adds or updates* named entries, it never removes one that's no longer in
the caller's list, so a `-m`-only "replace" would silently leak stale access
for anyone previously granted and since removed from `share_permissions`.

Every call uses the principal's **numeric** uid/gid, never a name — a named
ACL entry for an NSS-unresolvable name fails `setfacl` outright (verified:
`setfacl: Option -m: Invalid argument`), and numeric ids sidestep that
class of failure entirely.

`-n`/`--no-mask` is never passed: plain `setfacl -m` already recomputes
`m::`/`d:m::` to the union of `group::` and every named entry on each call,
so reasserting the mask explicitly (as `_ALWAYS_ENTRIES` does) is defensive
and cheap, not load-bearing — but `-n` was verified to leave a stale,
silently-too-low mask that caps effective permissions with zero error, so
it must never appear here.

Share directories are `root:nasos-users` mode 2700, not 2770 (PLAN.md §3):
`group::` and every named entry share one mask, so a `group::rwx` from mode
2770 would hand every `nasos-users` member — i.e. every NAS-OS user — full
access to every share regardless of `share_permissions`. Mode 2700 keeps
`group::` at `---`; `_ALWAYS_ENTRIES` reasserts `u::rwx,g::---` on every
call so that stays true even if something else touched the directory.
"""

from __future__ import annotations

from typing import Literal, Protocol

from nasos.system.runner import Runner

AclLevel = Literal["rw", "ro"]
PrincipalKind = Literal["user", "group"]

_ALWAYS_ENTRIES = "u::rwx,g::---,m::rwx,d:u::rwx,d:g::---,d:m::rwx,o::---,d:o::---"


class AclError(Exception):
    pass


def _qualifier(kind: PrincipalKind) -> str:
    return "u" if kind == "user" else "g"


def _perm(level: AclLevel) -> str:
    return "rwx" if level == "rw" else "r-x"


class Acl(Protocol):
    async def replace_all(
        self,
        path: str,
        entries: list[tuple[PrincipalKind, int, AclLevel]],
        *,
        recursive: bool,
    ) -> None: ...

    async def read_acl(self, path: str) -> list[tuple[PrincipalKind, int, AclLevel]]: ...


def _parse_getfacl(output: str) -> list[tuple[PrincipalKind, int, AclLevel]]:
    """Parses `getfacl -n --absolute-names --omit-header` output (verified
    live against a real scratch directory during M3 research) into the same
    `(kind, numeric_id, level)` shape `replace_all` takes, so a File Station
    ACL editor round-trips through the same model share permissions do.

    Only plain (non-`default:`) named `user:`/`group:` lines become entries
    — the bare owner/owning-group (`user::`/`group::`, empty id field),
    `mask::`, `other::` are bookkeeping, not principals to edit; `default:`
    lines are skipped since `replace_all` always writes them identically to
    their regular counterpart, so the regular ones are the whole picture.
    """
    entries: list[tuple[PrincipalKind, int, AclLevel]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("default:"):
            continue
        parts = line.split(":")
        if len(parts) != 3:
            continue
        qualifier, id_str, perm = parts
        if qualifier not in ("user", "group") or not id_str:
            continue
        kind: PrincipalKind = "user" if qualifier == "user" else "group"
        level: AclLevel = "rw" if "w" in perm else "ro"
        entries.append((kind, int(id_str), level))
    return entries


class SetfaclAcl:
    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    async def replace_all(
        self,
        path: str,
        entries: list[tuple[PrincipalKind, int, AclLevel]],
        *,
        recursive: bool,
    ) -> None:
        specs = [_ALWAYS_ENTRIES]
        for kind, numeric_id, level in entries:
            q, perm = _qualifier(kind), _perm(level)
            specs.append(f"{q}:{numeric_id}:{perm}")
            specs.append(f"d:{q}:{numeric_id}:{perm}")

        reset_args = ["-b", "-R", path] if recursive else ["-b", path]
        apply_args = (
            ["-R", "-m", ",".join(specs), path] if recursive else ["-m", ",".join(specs), path]
        )
        await self._run(reset_args)
        await self._run(apply_args)

    async def read_acl(self, path: str) -> list[tuple[PrincipalKind, int, AclLevel]]:
        result = await self._runner.run(
            ["getfacl", "-n", "--absolute-names", "--omit-header", path]
        )
        if not result.ok:
            raise AclError(result.stderr.strip() or f"getfacl {path} failed")
        return _parse_getfacl(result.stdout)

    async def _run(self, args: list[str]) -> None:
        result = await self._runner.run(["setfacl", *args])
        if not result.ok:
            raise AclError(result.stderr.strip() or f"setfacl {' '.join(args)} failed")


class FakeAcl:
    """In-memory ACL state for dev mode / unit tests."""

    def __init__(self) -> None:
        self.entries: dict[str, dict[tuple[PrincipalKind, int], AclLevel]] = {}

    async def replace_all(
        self,
        path: str,
        entries: list[tuple[PrincipalKind, int, AclLevel]],
        *,
        recursive: bool,  # noqa: ARG002  (fake state isn't a real tree, nothing to recurse into)
    ) -> None:
        self.entries[path] = {(kind, numeric_id): level for kind, numeric_id, level in entries}

    async def read_acl(self, path: str) -> list[tuple[PrincipalKind, int, AclLevel]]:
        return [
            (kind, numeric_id, level)
            for (kind, numeric_id), level in self.entries.get(path, {}).items()
        ]
