from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from huavd_map_build.shared.kernel import Role


class ReadyMarkerError(ValueError):
    """Raised when a ready marker violates its published schema."""


_SHA512 = re.compile(r"^[0-9a-f]{128}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True, slots=True)
class ReadyMarker:
    schema_version: int
    role: Role
    file: str
    sha512: str
    manifest_sha512: str
    attribution_sha512: str
    published_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "role": self.role.value,
            "file": self.file,
            "sha512": self.sha512,
            "manifest_sha512": self.manifest_sha512,
            "attribution_sha512": self.attribution_sha512,
            "published_at": self.published_at,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ReadyMarker:
        if not isinstance(value, dict):
            raise ReadyMarkerError("ready marker root must be an object")
        required = {
            "schema_version",
            "role",
            "file",
            "sha512",
            "manifest_sha512",
            "attribution_sha512",
            "published_at",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ReadyMarkerError(f"ready marker missing fields: {', '.join(missing)}")
        if value["schema_version"] != 1:
            raise ReadyMarkerError("ready marker schema_version must be 1")
        try:
            role = Role(str(value["role"]))
        except ValueError as error:
            raise ReadyMarkerError(f"invalid ready marker role: {value['role']}") from error
        file = str(value["file"])
        if not file or "/" in file or "\\" in file:
            raise ReadyMarkerError("ready marker file must be a basename")
        digests = {
            name: str(value[name])
            for name in ("sha512", "manifest_sha512", "attribution_sha512")
        }
        invalid = [name for name, digest in digests.items() if not _SHA512.fullmatch(digest)]
        if invalid:
            raise ReadyMarkerError(
                f"ready marker fields must be lowercase SHA-512: {', '.join(invalid)}"
            )
        published_at = str(value["published_at"])
        if not _UTC_TIMESTAMP.fullmatch(published_at):
            raise ReadyMarkerError("ready marker published_at must be UTC YYYY-MM-DDTHH:MM:SSZ")
        return cls(
            schema_version=1,
            role=role,
            file=file,
            sha512=digests["sha512"],
            manifest_sha512=digests["manifest_sha512"],
            attribution_sha512=digests["attribution_sha512"],
            published_at=published_at,
        )
