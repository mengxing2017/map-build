"""Independent dataset CLI boundary; no map Role dependency."""
from typing import Protocol


class RouteWeftError(RuntimeError):
    def __init__(self, message, *, response=None, command=None, exit_code=None):
        super().__init__(message)
        self.response = response
        self.command = command
        self.exit_code = exit_code


class RouteWeftPort(Protocol):
    identity: dict

    def call(self, command: str, arguments: list[str], timeout: float,
             expected_error: str | None = None) -> dict: ...
