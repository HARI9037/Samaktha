from __future__ import annotations

import re


class ExceptionClassifier:
    def classify(self, text: str) -> str:
        lower = text.lower()
        if "syntaxerror" in lower:
            return "syntax"
        if "typeerror" in lower:
            return "type"
        if "valueerror" in lower:
            return "value"
        return "unknown"


class FailureAnalyzer:
    def analyze(self, trace: str) -> dict[str, str]:
        cls = ExceptionClassifier().classify(trace)
        return {"classification": cls, "evidence": trace.splitlines()[-1] if trace else ""}


class RegressionAnalyzer:
    def compare(self, before: str, after: str) -> dict[str, bool]:
        return {"regressed": before != after}


class Debugger:
    def summarize(self, trace: str) -> str:
        return FailureAnalyzer().analyze(trace)["classification"]

