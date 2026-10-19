"""Independent dataset CLI boundary; no map Role dependency."""
from typing import Protocol


class RouteWeftError(RuntimeError):
    pass


class RouteWeftPort(Protocol):
    identity: dict

    def call(self, command: str, arguments: list[str], timeout: float,
             expected_error: str | None = None) -> dict: ...
