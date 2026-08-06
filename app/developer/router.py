from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DeveloperCommandResult:
    handled: bool
    output: str


class DeveloperCommandRouter:
    def route(self, command: str) -> DeveloperCommandResult:
        return DeveloperCommandResult(True, command)

