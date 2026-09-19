"""Shared singletons RPC handlers need — dependency injection without a
framework. One instance is built in agent/main.py (or by dev/test wiring)
and threaded through the dispatcher to every handler.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nasos.agent.fileworker_supervisor import FileWorkerSupervisor
from nasos.agent.jobs import JobRunner
from nasos.config import Settings
from nasos.system.acl import Acl
from nasos.system.distro.base import DistroAdapter
from nasos.system.firewall import Firewall
from nasos.system.mdstat import MdstatReader
from nasos.system.mounts import MountInfo
from nasos.system.pam_auth import Authenticator
from nasos.system.runner import CommandResult, FakeRunner, Runner
from nasos.system.samba import Samba
from nasos.system.systemd import Systemd
from nasos.system.users import PosixUsers

_DEV_DISK_SIZE = 4_000_787_030_016  # ~4 TB, a common real-world "4TB" drive's actual byte count
_DEV_BOOT_DISK_SIZE = 500_107_862_016  # 500 GB


def _seed_dev_disks(runner: FakeRunner) -> None:
    """Storage Manager (Milestone 4, PLAN.md §6) needs *something* to show
    in `make dev` beyond an empty disk list: two identical spare disks (a
    plausible RAID 1 pair) and one already-mounted "boot" disk so the
    guard's protected-device check has something real to demonstrate too.
    Only lsblk/vgs/lvs/smartctl are seeded — mdadm/lvm/mkfs/parted calls
    made while actually executing a plan against this fake data just fall
    through to FakeRunner's non-strict canned-success default, since
    there's no real mutation for a canned reply to reflect back into.
    """
    spare_disks: list[dict[str, object]] = [
        {
            "name": name,
            "path": f"/dev/{name}",
            "type": "disk",
            "serial": serial,
            "model": "NAS-OS-SIM",
            "wwn": f"0x5000000000000{n:03d}",
            "size": _DEV_DISK_SIZE,
            "rota": True,
            "tran": "sata",
            "fstype": None,
            "mountpoint": None,
            "uuid": None,
            "children": [],
        }
        for n, (name, serial) in enumerate(
            (("sda", "NASOS-SIM-0001"), ("sdb", "NASOS-SIM-0002")), 1
        )
    ]
    boot_disk: dict[str, object] = {
        "name": "sdc",
        "path": "/dev/sdc",
        "type": "disk",
        "serial": "NASOS-SIM-0003",
        "model": "NAS-OS-BOOT",
        "wwn": "0x5000000000000003",
        "size": _DEV_BOOT_DISK_SIZE,
        "rota": False,
        "tran": "sata",
        "fstype": None,
        "mountpoint": None,
        "uuid": None,
        "children": [
            {
                "name": "sdc1",
                "path": "/dev/sdc1",
                "type": "part",
                "serial": None,
                "model": None,
                "wwn": None,
                "size": 1_073_741_824,
                "rota": False,
                "tran": None,
                "fstype": "vfat",
                "mountpoint": "/boot",
                "uuid": "AAAA-BBBB",
                "children": [],
            },
            {
                "name": "sdc2",
                "path": "/dev/sdc2",
                "type": "part",
                "serial": None,
                "model": None,
                "wwn": None,
                "size": _DEV_BOOT_DISK_SIZE - 1_073_741_824,
                "rota": False,
                "tran": None,
                "fstype": "xfs",
                "mountpoint": "/",
                "uuid": "11111111-2222-3333-4444-555555555555",
                "children": [],
            },
        ],
    }

    runner.expect(
        ["lsblk", "-J", "-O", "-b"],
        stdout=json.dumps({"blockdevices": [*spare_disks, boot_disk]}),
    )
    runner.expect(
        [
            "vgs",
            "--reportformat",
            "json",
            "--units",
            "b",
            "--nosuffix",
            "-o",
            "vg_name,pv_name,vg_size,vg_free",
        ],
        stdout=json.dumps({"report": [{"vg": []}]}),
    )
    runner.expect(
        [
            "lvs",
            "--reportformat",
            "json",
            "--units",
            "b",
            "--nosuffix",
            "-o",
            "lv_name,vg_name,lv_path,lv_size",
        ],
        stdout=json.dumps({"report": [{"lv": []}]}),
    )
    smart_ok = json.dumps(
        {
            "smart_status": {"passed": True},
            "temperature": {"current": 32},
            "power_on_time": {"hours": 120},
            "ata_smart_attributes": {"table": []},
        }
    )
    for disk in (*spare_disks, boot_disk):
        runner.expect(["smartctl", "--json=c", "-a", str(disk["path"])], stdout=smart_ok)

    # Storage Manager's create-volume flow names its mount unit from
    # whatever mountpoint the user's chosen volume name resolves to
    # (dynamic, so an exact `.expect()` can't cover it in advance) — a
    # `.respond()` prefix responder computes a plausible name instead,
    # the same way a real `systemd-escape -p --suffix=mount` would.
    def _fake_systemd_escape(argv: list[str]) -> CommandResult:
        mountpoint = argv[-1]
        escaped = mountpoint.strip("/").replace("/", "-") or "-"
        return CommandResult(argv=argv, returncode=0, stdout=f"{escaped}.mount\n", stderr="")

    runner.respond(["systemd-escape"], _fake_systemd_escape)


@dataclass
class AgentState:
    settings: Settings
    authenticator: Authenticator
    distro: DistroAdapter
    jobs: JobRunner
    runner: Runner
    systemd: Systemd
    acl: Acl
    users: PosixUsers
    samba: Samba
    mounts: MountInfo
    firewall: Firewall
    fileworkers: FileWorkerSupervisor
    mdstat: MdstatReader
    """Storage Manager (Milestone 4, PLAN.md §6). The lsblk/smartctl/mdadm/
    lvm/mkfs/parted adapters aren't their own AgentState fields — like
    samba.py, they're plain modules generic over `state.runner`
    (system/samba.py's docstring has the rationale), called directly from
    agent/inventory.py and agent/handlers/storage.py."""


def build_state(
    settings: Settings,
    on_event: Callable[[str, dict[str, object]], None],
    *,
    dev: bool,
) -> AgentState:
    """Constructs the real-or-fake adapter set for one mode. Used by both
    agent/main.py (the root daemon) and web/main.py's dev-mode in-process
    wiring, so the dev/prod adapter choice lives in exactly one place.
    """
    from nasos.system.distro import get_distro_adapter
    from nasos.system.pam_auth import DevUsersAuthenticator, PamAuthenticator

    is_dev = dev or settings.is_dev

    authenticator: Authenticator = (
        DevUsersAuthenticator(settings.devusers_file) if is_dev else PamAuthenticator()
    )

    runner: Runner
    systemd: Systemd
    acl: Acl
    users: PosixUsers
    mounts: MountInfo
    firewall: Firewall
    mdstat: MdstatReader
    if is_dev:
        from nasos.system.acl import FakeAcl
        from nasos.system.firewall import FakeFirewall
        from nasos.system.mdstat import FakeMdstat
        from nasos.system.mounts import FakeMounts
        from nasos.system.systemd import FakeSystemd
        from nasos.system.users import FakePosixUsers

        # Strict (raise on any unstubbed command) for pytest, where every
        # test sets up its own expectations and a miss should fail loudly.
        # Non-strict for the interactive dev server (mode=dev), which has
        # no test harness pre-registering expectations — an unstubbed
        # command there should no-op-success, not crash the request.
        runner = FakeRunner(strict=not settings.is_dev)
        systemd = FakeSystemd()
        acl = FakeAcl()
        users = FakePosixUsers()
        mounts = FakeMounts()
        firewall = FakeFirewall()
        mdstat = FakeMdstat()
        # Seeds two plausible dev volumes so `make dev` has something to
        # register/create shares under without a real mount — real
        # directories under devdata_dir (which this user can actually
        # write to, no sudo needed), the same spirit as devusers.toml
        # standing in for real accounts.
        for volume_name, filesystem in (("volume1", "xfs"), ("volume2", "ext4")):
            volume_path = Path(settings.devdata_dir) / volume_name
            volume_path.mkdir(parents=True, exist_ok=True)
            mounts.mounts[str(volume_path)] = filesystem
        _seed_dev_disks(runner)
    else:
        from nasos.system.acl import SetfaclAcl
        from nasos.system.firewall import DBusFirewall
        from nasos.system.mdstat import ProcMdstat
        from nasos.system.mounts import ProcMounts
        from nasos.system.runner import SubprocessRunner
        from nasos.system.systemd import DBusSystemd
        from nasos.system.users import RealPosixUsers

        runner = SubprocessRunner()
        systemd = DBusSystemd()
        acl = SetfaclAcl(runner)
        users = RealPosixUsers(runner)
        mounts = ProcMounts()
        firewall = DBusFirewall()
        mdstat = ProcMdstat()

    jobs = JobRunner(f"{settings.state_dir}/agent/jobs.jsonl", on_event=on_event)
    return AgentState(
        settings=settings,
        authenticator=authenticator,
        distro=get_distro_adapter(),
        jobs=jobs,
        runner=runner,
        systemd=systemd,
        acl=acl,
        users=users,
        samba=Samba(runner, systemd),
        mounts=mounts,
        firewall=firewall,
        fileworkers=FileWorkerSupervisor(settings.run_dir),
        mdstat=mdstat,
    )
