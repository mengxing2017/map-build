from huavd_map_build.production.domain.workspace import (
    WorkspaceInitialization,
    WorkspacePlan,
)
from huavd_map_build.production.south.port.workspace import WorkspaceStore


class WorkspaceInitializer:
    def __init__(self, store: WorkspaceStore, config_source: str) -> None:
        self._store = store
        self._config_source = config_source

    def initialize(self, plan: WorkspacePlan) -> WorkspaceInitialization:
        for directory in plan.directories:
            self._store.ensure_directory(plan.root, directory)
        for directory in plan.public_directories:
            self._store.set_directory_mode(plan.root, directory, 0o755)
        for directory in plan.protected_directories:
            self._store.set_directory_mode(
                plan.root, directory, plan.directory_mode
            )
        if plan.copy_config:
            self._store.copy_configuration(self._config_source, plan.root)
            self._store.set_configuration_modes(
                plan.root, plan.config_directory_mode, plan.config_file_mode
            )
        return WorkspaceInitialization(plan.root, plan.session.value)
