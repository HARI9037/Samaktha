from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TestAnalyzer:
    coverage: float = 0.0


class CoverageInspector:
    def inspect(self, lines: int, covered: int) -> float:
        return 0.0 if lines == 0 else covered / lines


class RegressionPredictor:
    def predict(self, changed_files: list[str]) -> list[str]:
        return list(changed_files)


class ImpactAnalyzer:
    def analyze(self, files: list[str]) -> list[str]:
        return list(files)

