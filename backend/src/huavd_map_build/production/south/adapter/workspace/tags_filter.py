from pathlib import Path


class FileSystemTagsFilterWorkspace:
    _WORKSPACE_PREFIXES = ("mirror/", "cache/", "staging/", "outputs/")

    def resolve_input(self, path: str, workdir: str) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            return str(candidate)
        if path.startswith(self._WORKSPACE_PREFIXES):
            return str(Path(workdir) / candidate)
        if candidate.exists():
            return str(candidate.resolve())
        return str(Path(workdir) / candidate)

    def require_file(self, path: str) -> None:
        if not Path(path).is_file():
            raise ValueError(f"required file does not exist: {path}")

    def ensure_directory(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
