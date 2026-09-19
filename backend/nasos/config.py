"""Application configuration.

Settings are sourced (lowest to highest precedence) from defaults, the TOML
file at ``NASOS_CONFIG_FILE`` (default ``/etc/nasos/nasos.toml``, silently
skipped if absent), and ``NASOS_*`` environment variables.
"""

from __future__ import annotations

import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class Mode(StrEnum):
    prod = "prod"
    dev = "dev"
    test = "test"


class _TomlConfigSource(PydanticBaseSettingsSource):
    """Reads settings from the TOML file named by NASOS_CONFIG_FILE, if it exists."""

    def __init__(self, settings_cls: type[BaseSettings], toml_file: str) -> None:
        super().__init__(settings_cls)
        self._toml_file = toml_file

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:  # noqa: ARG002
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        path = Path(self._toml_file)
        if not path.is_file():
            return {}
        with path.open("rb") as fh:
            return tomllib.load(fh)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NASOS_",
        env_file=None,
        extra="ignore",
    )

    mode: Mode = Mode.prod
    config_file: str = "/etc/nasos/nasos.toml"

    hostname_override: str | None = None
    http_port: int = 5000
    https_port: int = 5001
    tls_cert: str = "/etc/nasos/tls/cert.pem"
    tls_key: str = "/etc/nasos/tls/key.pem"

    db_path: str = "/var/lib/nasos/nasos.db"
    state_dir: str = "/var/lib/nasos"
    log_dir: str = "/var/log/nasos"
    run_dir: str = "/run/nasos"

    agent_socket: str = "/run/nasos/agent.sock"
    workers_dir: str = "/run/nasos/workers"

    session_idle_timeout_minutes: int = 30
    session_cookie_secure: bool = True

    volumes_root: str = "/volume"

    devdata_dir: str = "./devdata"
    devusers_file: str = "./devdata/devusers.toml"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Read NASOS_CONFIG_FILE / defaults first (via env_settings) to know
        # which TOML file to load, then layer: defaults < toml < env < init.
        prelim = env_settings()
        toml_file = prelim.get("config_file", cls.model_fields["config_file"].default)
        toml_source = _TomlConfigSource(settings_cls, toml_file)
        return (init_settings, env_settings, dotenv_settings, toml_source, file_secret_settings)

    @property
    def is_dev(self) -> bool:
        return self.mode == Mode.dev

    @property
    def is_test(self) -> bool:
        return self.mode == Mode.test

    @property
    def cookie_secure(self) -> bool:
        """Dev mode is plain HTTP; a Secure cookie would silently never be sent."""
        return self.session_cookie_secure and not self.is_dev

    def system_path(self, real_path: str) -> str:
        """Remaps a real system path (a config file the agent would
        otherwise read/write in place, e.g. /etc/samba/nasos.conf) under
        devdata_dir in dev/test mode, so handlers never touch the real
        filesystem outside a sandbox during `make dev` / pytest — only the
        *destination* of an actual file read/write needs this; an argv
        string handed to a Runner (real or Fake) doesn't, since FakeRunner
        never touches disk regardless of what path string it's matching on.
        """
        if self.is_dev or self.is_test:
            return f"{self.devdata_dir}{real_path}"
        return real_path


def get_settings() -> Settings:
    return Settings()
