"""Wire protocol envelopes and the RPC method registry.

Every RPC method has a pair of Pydantic models (Params, Result) declared in
this module and registered in ``REGISTRY``. The agent-side dispatcher
validates incoming params against ``REGISTRY[method].params``, calls the
matching handler, and validates the handler's return value against
``REGISTRY[method].result`` before it goes on the wire. Handlers themselves
live in ``nasos.agent.handlers.*`` and are bound to a method name via
``nasos.agent.dispatcher.handler``.

Nothing here talks to a socket; see ``transport.py`` for the framing and
``client.py`` for the caller-facing API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Usernames map 1:1 to POSIX account names created by `useradd`.
USERNAME_RE = r"^[a-z_][a-z0-9_-]{0,31}$"
GROUP_NAME_RE = USERNAME_RE
# Share names become both a directory component and a Samba [section] name.
SHARE_NAME_RE = r"^[a-zA-Z0-9][a-zA-Z0-9 _-]{0,63}$"

Role = Literal["admin", "user"]


class RpcModel(BaseModel):
    """Base for every Params/Result model: unknown fields are a protocol bug."""

    model_config = ConfigDict(extra="forbid")


# --- Envelope -----------------------------------------------------------


class RpcContext(RpcModel):
    """Who is making the call, attached by the caller and never trusted blindly:
    the agent only trusts ``user``/``role`` for calls it authenticated itself
    (see peer-cred check in agent/main.py); ``ip`` is caller-supplied, for
    audit logging only.
    """

    user: str | None = None
    # Informational only (audit-log display), so plain str rather than the
    # stricter Role: it's sourced from session/DB rows at various call sites,
    # never itself an authorization decision (AuthLoginResult.role is that).
    role: str | None = None
    ip: str | None = None


class RpcError(RpcModel):
    code: str
    message: str


class RpcRequest(RpcModel):
    type: Literal["request"] = "request"
    id: str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    ctx: RpcContext = Field(default_factory=RpcContext)


class RpcResponse(RpcModel):
    type: Literal["response"] = "response"
    id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: RpcError | None = None


class RpcEvent(RpcModel):
    """Unsolicited agent -> web message, fanned out by the web EventBus."""

    type: Literal["event"] = "event"
    topic: str
    data: dict[str, Any] = Field(default_factory=dict)


class RpcException(Exception):
    """Raised by handlers; caught by the dispatcher and turned into an RpcError."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# --- auth.* ---------------------------------------------------------------


class AuthLoginParams(RpcModel):
    """`password` is plain str, not SecretStr: this model's whole purpose is to
    be serialized across the RPC wire, which is exactly what SecretStr blocks
    (it masks on every model_dump, by design). The dispatcher's audit log
    never records raw params, only method name + outcome, so there's nothing
    here for SecretStr to protect against.
    """

    username: str = Field(pattern=USERNAME_RE)
    password: str


class AuthLoginResult(RpcModel):
    uid: int
    username: str
    role: Role
    display_name: str


# --- system.* ---------------------------------------------------------------


class SystemInfoParams(RpcModel):
    pass


class SystemInfoResult(RpcModel):
    hostname: str
    os_pretty_name: str
    kernel: str
    nasos_version: str
    uptime_seconds: float


# --- users.* ------------------------------------------------------------


class UserCreateParams(RpcModel):
    username: str = Field(pattern=USERNAME_RE)
    password: str
    description: str = ""


class UserInfo(RpcModel):
    uid: int
    username: str


class UserSetSmbEnabledParams(RpcModel):
    """`description` isn't here: it's NAS-OS's own bookkeeping (the `users`
    table), not something the real system needs to know about, so changing
    it is a plain DB update with no RPC call at all.
    """

    username: str = Field(pattern=USERNAME_RE)
    enabled: bool


class UserDeleteParams(RpcModel):
    username: str = Field(pattern=USERNAME_RE)
    delete_home: bool = False


class UserSetPasswordParams(RpcModel):
    username: str = Field(pattern=USERNAME_RE)
    password: str


class UserImportParams(RpcModel):
    username: str = Field(pattern=USERNAME_RE)


class OkResult(RpcModel):
    ok: Literal[True] = True


# --- groups.* -----------------------------------------------------------


class GroupCreateParams(RpcModel):
    name: str = Field(pattern=GROUP_NAME_RE)
    description: str = ""


class GroupInfo(RpcModel):
    gid: int
    name: str


class GroupDeleteParams(RpcModel):
    name: str = Field(pattern=GROUP_NAME_RE)


class GroupMembershipParams(RpcModel):
    name: str = Field(pattern=GROUP_NAME_RE)
    username: str = Field(pattern=USERNAME_RE)


# --- volumes.* ----------------------------------------------------------


class VolumeRegisterParams(RpcModel):
    """Just the mountpoint: the agent only validates and reports the
    filesystem type. The volume's display `name` is a web/DB-side label,
    unrelated to what the agent needs to check.
    """

    mountpoint: str = Field(min_length=1, max_length=255)


class VolumeInfo(RpcModel):
    mountpoint: str
    filesystem: str


# --- storage.* (Milestone 4: PLAN.md §6) ---------------------------------

StorageHealth = Literal["ok", "warning", "critical", "unknown"]
RaidLevel = Literal["basic", "1", "5", "6", "10"]
Filesystem = Literal["xfs", "ext4"]

# A device/array/LV name that becomes a systemd unit name component and an
# argv token — deliberately narrow (lsblk/mdadm/lvm names are always plain
# ASCII in practice; this just keeps anything stranger out of a mount-unit
# filename or a shell-adjacent argv slot).
DEVICE_NAME_RE = r"^[a-zA-Z0-9_.:-]{1,64}$"
VOLUME_NAME_RE = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"


class SmartAttribute(RpcModel):
    id: int
    name: str
    value: int
    worst: int
    threshold: int
    raw: str


class DiskSmart(RpcModel):
    health: StorageHealth
    temperature_c: float | None = None
    power_on_hours: int | None = None
    attributes: list[SmartAttribute] = Field(default_factory=list)


class DiskNode(RpcModel):
    """One node of the lsblk device tree (disk -> partition -> md member ->
    PV -> LV -> filesystem), mirroring lsblk's own nested `children` shape
    so the guard's "transitively hosts a mounted FS" walk is a plain
    recursive traversal (PLAN.md §6).
    """

    name: str
    path: str
    type: str
    """lsblk TYPE: "disk" | "part" | "raid1"/"raid5"/... | "lvm" | "crypt" | ..."""
    serial: str | None = None
    model: str | None = None
    wwn: str | None = None
    size: int = 0
    rota: bool = False
    transport: str = "unknown"
    fstype: str | None = None
    mountpoint: str | None = None
    uuid: str | None = None
    smart: DiskSmart | None = None
    protected: bool = False
    protected_reason: str | None = None
    children: list[DiskNode] = Field(default_factory=list)


class ArrayInfo(RpcModel):
    path: str
    name: str
    level: str
    devices: list[str]
    state: str
    resync_percent: float | None = None


class VgInfo(RpcModel):
    name: str
    pvs: list[str]
    size: int
    free: int


class LvInfo(RpcModel):
    name: str
    vg: str
    path: str
    size: int


class StorageInventoryParams(RpcModel):
    pass


class StorageInventoryResult(RpcModel):
    disks: list[DiskNode]
    arrays: list[ArrayInfo]
    vgs: list[VgInfo]
    lvs: list[LvInfo]


class StoragePlanSpec(RpcModel):
    """Everything needed to deterministically rebuild the same ordered
    argv steps (system/storage_plan.py's `build_steps`) both when the web
    process renders a plan preview and, unchanged, when the agent actually
    executes it — the same pure function, the same input, the same output,
    which is what makes "plan preview renders exact argv" a meaningful
    guarantee rather than two implementations that might drift apart.
    """

    volume_name: str = Field(pattern=VOLUME_NAME_RE)
    level: RaidLevel
    filesystem: Filesystem
    disk_paths: list[str] = Field(min_length=1)
    disk_serials: list[str] = Field(min_length=1)
    array_name: str = Field(pattern=DEVICE_NAME_RE)
    vg_name: str = Field(pattern=DEVICE_NAME_RE)
    lv_name: str = Field(pattern=DEVICE_NAME_RE)
    mountpoint: str = Field(min_length=1, max_length=255)


class StorageExecutePlanParams(RpcModel):
    spec: StoragePlanSpec
    expected_sizes: dict[str, int]
    """serial -> size recorded at plan time, for the agent's own fresh-
    inventory mismatch check just before anything destructive runs."""
    managed_mountpoints: list[str]
    """Every currently-managed volume's mountpoint (including the new
    one), for the smb/nfs-server/vsftpd drop-ins' `RequiresMountsFor=` —
    the agent has no DB access (PLAN.md §4: SQLite is opened only by the
    web process), so the web resolves this list, not the agent."""


# --- shares.* -----------------------------------------------------------


class ShareCreateParams(RpcModel):
    path: str = Field(min_length=1, max_length=255)


class ShareDeleteParams(RpcModel):
    path: str = Field(min_length=1, max_length=255)
    delete_files: bool = False


SharePrincipalKind = Literal["user", "group"]
ShareAclLevel = Literal["rw", "ro"]


class ShareAclEntry(RpcModel):
    kind: SharePrincipalKind
    numeric_id: int
    level: ShareAclLevel


class ShareSetPermissionsParams(RpcModel):
    path: str = Field(min_length=1, max_length=255)
    entries: list[ShareAclEntry]
    recursive: bool = False


class JobStartedResult(RpcModel):
    job_id: str | None = None
    """None when applied synchronously (recursive=False); set when a
    background job was submitted instead."""


# --- samba.* --------------------------------------------------------------


class SambaApplyConfigParams(RpcModel):
    content: str
    restart: bool = False
    """False: reload (share-only change). True: full restart (global
    parameter change) — PLAN.md §2."""


class SambaApplyConfigResult(RpcModel):
    sha256: str


class SambaEnsureEnabledParams(RpcModel):
    pass


# --- firewall.* -------------------------------------------------------------


class FirewallEnsureServiceParams(RpcModel):
    """`service` is a firewalld service name (e.g. "samba"), applied to the
    default zone — resolved agent-side, since only the agent talks to
    firewalld."""

    service: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")


# --- jobs.* ---------------------------------------------------------------


class JobListParams(RpcModel):
    pass


class JobRecordResult(RpcModel):
    id: str
    kind: str
    resource: str | None
    status: str
    progress: float
    message: str


class JobListResult(RpcModel):
    jobs: list[JobRecordResult]


# --- files.* (served by the per-user fileworker, PLAN.md §1/§5) -----------
#
# Bulk file bytes (upload chunks, downloads, zip streams) never go through
# these Params/Result models or the Dispatcher/REGISTRY machinery below —
# embedding gigabyte-scale payloads as base64 inside a JSON line is exactly
# what PLAN.md's "optional binary frame" wire extension exists to avoid. The
# methods here only ever carry metadata; FileWorkerClient (rpc/client.py)
# speaks a small hand-rolled framing of its own for the actual bytes, over
# its own short-lived connections to the same worker socket.

FilePrincipalKind = Literal["user", "group"]
FileAclLevel = Literal["rw", "ro"]


class FileEntry(RpcModel):
    name: str
    path: str
    is_dir: bool
    size: int
    mtime: float
    owner_uid: int


class FilesListParams(RpcModel):
    path: str = Field(min_length=1, max_length=4096)


class FilesListResult(RpcModel):
    entries: list[FileEntry]


class FilesSearchParams(RpcModel):
    path: str = Field(min_length=1, max_length=4096)
    query: str = Field(min_length=1, max_length=255)


class FilesSearchResult(RpcModel):
    entries: list[FileEntry]


class FilesMkdirParams(RpcModel):
    path: str = Field(min_length=1, max_length=4096)


class FilesRenameParams(RpcModel):
    path: str = Field(min_length=1, max_length=4096)
    new_name: str = Field(min_length=1, max_length=255)


class FilesDeleteParams(RpcModel):
    paths: list[str] = Field(min_length=1)


class FilesCopyParams(RpcModel):
    sources: list[str] = Field(min_length=1)
    dest_dir: str = Field(min_length=1, max_length=4096)


class FilesMoveParams(RpcModel):
    sources: list[str] = Field(min_length=1)
    dest_dir: str = Field(min_length=1, max_length=4096)


class FilesZipParams(RpcModel):
    sources: list[str] = Field(min_length=1)
    dest_path: str = Field(min_length=1, max_length=4096)


class FilesPropertiesParams(RpcModel):
    path: str = Field(min_length=1, max_length=4096)


class FilesPropertiesResult(RpcModel):
    name: str
    path: str
    is_dir: bool
    size: int
    mtime: float
    owner_uid: int
    owner_name: str
    mode: str
    """Symbolic permission string, e.g. "rwxr-x---" (stat mode, not ACL)."""
    item_count: int | None = None
    """Immediate-children count; set for directories only."""


class FilesAclEntry(RpcModel):
    kind: FilePrincipalKind
    numeric_id: int
    level: FileAclLevel


class FilesGetAclParams(RpcModel):
    path: str = Field(min_length=1, max_length=4096)


class FilesGetAclResult(RpcModel):
    entries: list[FilesAclEntry]


class FilesSetAclParams(RpcModel):
    path: str = Field(min_length=1, max_length=4096)
    entries: list[FilesAclEntry]
    recursive: bool = False


class FilesUploadBeginParams(RpcModel):
    upload_id: str
    dest_path: str = Field(min_length=1, max_length=4096)
    size: int = Field(ge=0)


class FilesUploadOffsetParams(RpcModel):
    upload_id: str


class FilesUploadOffsetResult(RpcModel):
    offset: int


class FilesUploadCompleteParams(RpcModel):
    upload_id: str


class FilesUploadAbortParams(RpcModel):
    upload_id: str


class FilesJobListParams(RpcModel):
    pass


# --- agent.fileworker.* (root agent: spawn/reap/reconnect, PLAN.md §1) ----


class FileWorkerEnsureParams(RpcModel):
    uid: int
    username: str = Field(pattern=USERNAME_RE)


class FileWorkerEnsureResult(RpcModel):
    socket_path: str


# --- registry ---------------------------------------------------------------


@dataclass(frozen=True)
class MethodSpec:
    params: type[RpcModel]
    result: type[RpcModel]


REGISTRY: dict[str, MethodSpec] = {
    "auth.login": MethodSpec(AuthLoginParams, AuthLoginResult),
    "system.info": MethodSpec(SystemInfoParams, SystemInfoResult),
    "users.create": MethodSpec(UserCreateParams, UserInfo),
    "users.set_smb_enabled": MethodSpec(UserSetSmbEnabledParams, OkResult),
    "users.delete": MethodSpec(UserDeleteParams, OkResult),
    "users.set_password": MethodSpec(UserSetPasswordParams, OkResult),
    "users.import_existing": MethodSpec(UserImportParams, UserInfo),
    "groups.create": MethodSpec(GroupCreateParams, GroupInfo),
    "groups.delete": MethodSpec(GroupDeleteParams, OkResult),
    "groups.add_member": MethodSpec(GroupMembershipParams, OkResult),
    "groups.remove_member": MethodSpec(GroupMembershipParams, OkResult),
    "volumes.register": MethodSpec(VolumeRegisterParams, VolumeInfo),
    "storage.inventory": MethodSpec(StorageInventoryParams, StorageInventoryResult),
    "storage.execute_plan": MethodSpec(StorageExecutePlanParams, JobStartedResult),
    "shares.create": MethodSpec(ShareCreateParams, OkResult),
    "shares.delete": MethodSpec(ShareDeleteParams, OkResult),
    "shares.set_permissions": MethodSpec(ShareSetPermissionsParams, JobStartedResult),
    "samba.apply_config": MethodSpec(SambaApplyConfigParams, SambaApplyConfigResult),
    "samba.ensure_enabled": MethodSpec(SambaEnsureEnabledParams, OkResult),
    "firewall.ensure_service": MethodSpec(FirewallEnsureServiceParams, OkResult),
    "jobs.list": MethodSpec(JobListParams, JobListResult),
    "files.list": MethodSpec(FilesListParams, FilesListResult),
    "files.search": MethodSpec(FilesSearchParams, FilesSearchResult),
    "files.mkdir": MethodSpec(FilesMkdirParams, OkResult),
    "files.rename": MethodSpec(FilesRenameParams, OkResult),
    "files.delete": MethodSpec(FilesDeleteParams, JobStartedResult),
    "files.copy": MethodSpec(FilesCopyParams, JobStartedResult),
    "files.move": MethodSpec(FilesMoveParams, JobStartedResult),
    "files.zip": MethodSpec(FilesZipParams, JobStartedResult),
    "files.properties": MethodSpec(FilesPropertiesParams, FilesPropertiesResult),
    "files.get_acl": MethodSpec(FilesGetAclParams, FilesGetAclResult),
    "files.set_acl": MethodSpec(FilesSetAclParams, JobStartedResult),
    "files.upload_begin": MethodSpec(FilesUploadBeginParams, OkResult),
    "files.upload_offset": MethodSpec(FilesUploadOffsetParams, FilesUploadOffsetResult),
    "files.upload_complete": MethodSpec(FilesUploadCompleteParams, OkResult),
    "files.upload_abort": MethodSpec(FilesUploadAbortParams, OkResult),
    "files.jobs.list": MethodSpec(FilesJobListParams, JobListResult),
    "agent.fileworker.ensure": MethodSpec(FileWorkerEnsureParams, FileWorkerEnsureResult),
}
