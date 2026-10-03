from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChecksumEntry:
    digest: str
    path: str

    def render(self) -> str:
        escaped = self.path.replace("\\", "\\\\").replace("\n", "\\n")
        prefix = "\\" if escaped != self.path else ""
        return f"{prefix}{self.digest}  {escaped}\n"


@dataclass(frozen=True, slots=True)
class ChecksumManifest:
    algorithm: str
    entries: tuple[ChecksumEntry, ...]

    def render(self) -> str:
        return "".join(entry.render() for entry in self.entries)
