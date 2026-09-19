from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nasos.system.managedfile import ConfigApplyError, ConfigValidationError, ManagedFile
from nasos.system.runner import FakeRunner


@pytest.fixture
def runner() -> FakeRunner:
    runner = FakeRunner()
    return runner


def _expect_restorecon_ok(runner: FakeRunner, path: Path) -> None:
    runner.expect(["restorecon", str(path)], returncode=0)


async def test_first_write_has_no_backup_and_returns_hash(
    tmp_path: Path, runner: FakeRunner
) -> None:
    target = tmp_path / "nasos.conf"
    _expect_restorecon_ok(runner, target)

    mf = ManagedFile(
        path=str(target),
        render=lambda: "hello\n",
        runner=runner,
        backup_dir=str(tmp_path / "backups"),
    )
    digest = await mf.write_and_apply()

    assert target.read_text() == "hello\n"
    assert digest == hashlib.sha256(b"hello\n").hexdigest()
    assert not (tmp_path / "backups").exists()


async def test_second_write_backs_up_previous_content(tmp_path: Path, runner: FakeRunner) -> None:
    target = tmp_path / "nasos.conf"
    backups = tmp_path / "backups"
    target.write_text("old content\n")
    _expect_restorecon_ok(runner, target)

    mf = ManagedFile(
        path=str(target), render=lambda: "new content\n", runner=runner, backup_dir=str(backups)
    )
    await mf.write_and_apply()

    assert target.read_text() == "new content\n"
    backed_up = list(backups.glob("nasos.conf.*"))
    assert len(backed_up) == 1
    assert backed_up[0].read_text() == "old content\n"


async def test_validate_failure_rolls_back_and_raises(tmp_path: Path, runner: FakeRunner) -> None:
    target = tmp_path / "nasos.conf"
    target.write_text("good config\n")
    _expect_restorecon_ok(runner, target)

    async def failing_validate(path: Path) -> None:  # noqa: ARG001
        raise ConfigValidationError("bad line 3")

    mf = ManagedFile(
        path=str(target),
        render=lambda: "broken config\n",
        runner=runner,
        validate=failing_validate,
        backup_dir=str(tmp_path / "backups"),
    )

    with pytest.raises(ConfigValidationError, match="bad line 3"):
        await mf.write_and_apply()

    assert target.read_text() == "good config\n"


async def test_apply_failure_rolls_back_and_reapplies_previous(
    tmp_path: Path, runner: FakeRunner
) -> None:
    target = tmp_path / "nasos.conf"
    target.write_text("good config\n")
    _expect_restorecon_ok(runner, target)

    apply_calls: list[str] = []

    async def flaky_apply() -> None:
        # Reads the file at call time so we can see which content was live.
        apply_calls.append(target.read_text())
        if len(apply_calls) == 1:
            raise ConfigApplyError("service failed to start")

    mf = ManagedFile(
        path=str(target),
        render=lambda: "broken config\n",
        runner=runner,
        apply=flaky_apply,
        backup_dir=str(tmp_path / "backups"),
    )

    with pytest.raises(ConfigApplyError, match="service failed to start"):
        await mf.write_and_apply()

    assert target.read_text() == "good config\n"
    # First call saw the broken content (that's why it failed); the
    # best-effort re-apply after rollback saw the restored good content.
    assert apply_calls == ["broken config\n", "good config\n"]


async def test_first_write_has_no_previous_to_restore_on_failure(
    tmp_path: Path, runner: FakeRunner
) -> None:
    target = tmp_path / "nasos.conf"
    _expect_restorecon_ok(runner, target)

    async def failing_validate(path: Path) -> None:  # noqa: ARG001
        raise ConfigValidationError("nope")

    mf = ManagedFile(
        path=str(target),
        render=lambda: "broken\n",
        runner=runner,
        validate=failing_validate,
        backup_dir=str(tmp_path / "backups"),
    )

    with pytest.raises(ConfigValidationError):
        await mf.write_and_apply()

    assert not target.exists()


async def test_backup_rotation_keeps_only_20(tmp_path: Path, runner: FakeRunner) -> None:
    target = tmp_path / "nasos.conf"
    backups = tmp_path / "backups"
    target.write_text("v0\n")
    _expect_restorecon_ok(runner, target)

    for i in range(1, 25):

        def render(value: int = i) -> str:
            return f"v{value}\n"

        mf = ManagedFile(path=str(target), render=render, runner=runner, backup_dir=str(backups))
        await mf.write_and_apply()

    assert len(list(backups.glob("nasos.conf.*"))) <= 20


async def test_mode_is_applied(tmp_path: Path, runner: FakeRunner) -> None:
    target = tmp_path / "vsftpd.conf"
    _expect_restorecon_ok(runner, target)

    mf = ManagedFile(path=str(target), render=lambda: "listen=YES\n", runner=runner, mode=0o600)
    await mf.write_and_apply()

    assert (target.stat().st_mode & 0o777) == 0o600
