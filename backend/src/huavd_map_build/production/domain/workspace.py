from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.shared.kernel import SessionId


@dataclass(frozen=True, slots=True)
class WorkspacePlan:
    root: str
    session: SessionId
    directory_mode: int = 0o750
    config_directory_mode: int = 0o755
    config_file_mode: int = 0o644
    copy_config: bool = False

    def __post_init__(self) -> None:
        if not self.root:
            raise ValueError("workspace root must not be empty")
        for name, mode in (
            ("directory", self.directory_mode),
            ("config directory", self.config_directory_mode),
            ("config file", self.config_file_mode),
        ):
            if mode < 0 or mode > 0o777:
                raise ValueError(f"invalid {name} mode: {mode:o}")

    @property
    def directories(self) -> tuple[str, ...]:
        session = self.session.value
        return (
            "bin",
            "tools",
            "mirror",
            "cache/bake",
            "cache/tags-filter",
            f"staging/{session}/layers",
            "outputs",
            "config/regions",
            "config/export-config",
        )

    @property
    def public_directories(self) -> tuple[str, ...]:
        return ("", "bin", "tools", "config", "config/regions", "config/export-config")

    @property
    def protected_directories(self) -> tuple[str, ...]:
        session = self.session.value
        return (
            "mirror",
            "cache",
            "cache/bake",
            "cache/tags-filter",
            "staging",
            f"staging/{session}",
            f"staging/{session}/layers",
            "outputs",
        )


@dataclass(frozen=True, slots=True)
class WorkspaceInitialization:
    root: str
    session: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schema_version": "1",
            "status": "initialized",
            "workdir": self.root,
            "session": self.session,
        }
