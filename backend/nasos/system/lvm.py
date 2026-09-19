"""LVM: pv/vg/lv reporting (`--reportformat json --units b`) and creation
(PLAN.md §4/§6 decision). Generic over `Runner`, no bespoke Fake — see
system/samba.py's docstring.
"""

from __future__ import annotations

import json

from nasos.rpc.schemas import LvInfo, VgInfo
from nasos.system.runner import Runner


class LvmError(Exception):
    pass


def _to_int(value: object) -> int:
    """lvs/vgs `--reportformat json` numeric fields come back as JSON
    strings (e.g. `"1073741824"`), not JSON numbers."""
    return int(float(str(value))) if value is not None else 0


def pvcreate_argv(device: str) -> list[str]:
    return ["pvcreate", device]


def vgcreate_argv(vg_name: str, device: str) -> list[str]:
    return ["vgcreate", vg_name, device]


def lvcreate_full_free_argv(vg_name: str, lv_name: str) -> list[str]:
    return ["lvcreate", "-l", "100%FREE", "-n", lv_name, vg_name]


async def pvcreate(runner: Runner, device: str) -> None:
    result = await runner.run(pvcreate_argv(device))
    if not result.ok:
        raise LvmError(result.stderr.strip() or f"pvcreate exited {result.returncode}")


async def vgcreate(runner: Runner, vg_name: str, device: str) -> None:
    result = await runner.run(vgcreate_argv(vg_name, device))
    if not result.ok:
        raise LvmError(result.stderr.strip() or f"vgcreate exited {result.returncode}")


async def lvcreate_full_free(runner: Runner, vg_name: str, lv_name: str) -> None:
    result = await runner.run(lvcreate_full_free_argv(vg_name, lv_name))
    if not result.ok:
        raise LvmError(result.stderr.strip() or f"lvcreate exited {result.returncode}")


async def report_vgs(runner: Runner) -> list[VgInfo]:
    result = await runner.run(
        [
            "vgs",
            "--reportformat",
            "json",
            "--units",
            "b",
            "--nosuffix",
            "-o",
            "vg_name,pv_name,vg_size,vg_free",
        ]
    )
    if not result.ok:
        raise LvmError(result.stderr.strip() or f"vgs exited {result.returncode}")
    rows = _report_rows(result.stdout, "vg")

    by_name: dict[str, VgInfo] = {}
    for row in rows:
        name = str(row.get("vg_name", ""))
        if name not in by_name:
            by_name[name] = VgInfo(
                name=name,
                pvs=[],
                size=_to_int(row.get("vg_size")),
                free=_to_int(row.get("vg_free")),
            )
        pv_name = row.get("pv_name")
        if pv_name:
            by_name[name].pvs.append(str(pv_name))
    return list(by_name.values())


async def report_lvs(runner: Runner) -> list[LvInfo]:
    result = await runner.run(
        [
            "lvs",
            "--reportformat",
            "json",
            "--units",
            "b",
            "--nosuffix",
            "-o",
            "lv_name,vg_name,lv_path,lv_size",
        ]
    )
    if not result.ok:
        raise LvmError(result.stderr.strip() or f"lvs exited {result.returncode}")
    rows = _report_rows(result.stdout, "lv")

    return [
        LvInfo(
            name=str(row.get("lv_name", "")),
            vg=str(row.get("vg_name", "")),
            path=str(row.get("lv_path", "")),
            size=_to_int(row.get("lv_size")),
        )
        for row in rows
    ]


def _report_rows(stdout: str, kind: str) -> list[dict[str, object]]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise LvmError(f"{kind}s produced invalid JSON: {exc}") from exc

    reports = parsed.get("report", [])
    rows: list[dict[str, object]] = []
    for report in reports:
        rows.extend(report.get(f"{kind}", []))
    return rows
