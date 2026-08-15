"""P1.7 — Developer intelligence tests.

Covers the structured AST-based review engine: real analyzers (hardcoded
secrets, nested loops, unused imports, long functions, TODO markers),
structured findings with severity + evidence, review over a real repository,
and deterministic failure behavior.
"""

from __future__ import annotations

from pathlib import Path

from app.developer.review import (
    HardcodedSecretAnalyzer,
    LongFunctionAnalyzer,
    NestedLoopAnalyzer,
    ReviewEngine,
    ReviewResult,
    Severity,
    TodoFIXMEAnalyzer,
    UnusedImportAnalyzer,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestStructuredFindings:
    def test_finding_carries_evidence_and_severity(self, tmp_path):
        path = _write(tmp_path, "app.py", "password = 's3cr3t'\n")
        result = ReviewEngine().review(path)
        finding = result.sorted_findings()[0]
        assert finding.rule == "hardcoded-secret"
        assert finding.severity == Severity.HIGH
        assert finding.line == 1
        assert "s3cr3t" in finding.evidence
        assert finding.file == str(path)

    def test_severity_ranking(self):
        assert Severity.INFO.rank < Severity.LOW.rank < Severity.MEDIUM.rank < Severity.HIGH.rank

    def test_review_result_counts_by_severity(self, tmp_path):
        path = _write(tmp_path, "app.py", "password = 'abc123'\nTODO: later\n")
        result = ReviewEngine().review(path)
        counts = result.by_severity()
        assert counts["high"] == 1
        assert counts["info"] >= 1

    def test_sorted_findings_orders_high_first(self, tmp_path):
        path = _write(
            tmp_path,
            "app.py",
            "import os\n\n\ndef f():\n    for i in range(1):\n        for j in range(1):\n            pass\n",
        )
        result = ReviewEngine().review(path)
        sorted_findings = result.sorted_findings()
        assert sorted_findings == sorted(
            sorted_findings,
            key=lambda f: (-f.severity.rank, f.file, f.line or 0, f.rule),
        )


class TestHardcodedSecretAnalyzer:
    def test_detects_password_assignment(self, tmp_path):
        path = _write(tmp_path, "app.py", "api_password = 'hunter22'\n")
        result = ReviewEngine().review(path)
        assert any(f.rule == "hardcoded-secret" for f in result.findings)

    def test_detects_dict_literal_secret(self, tmp_path):
        path = _write(tmp_path, "app.py", 'creds = {"token": "abc123", "user": "u"}\n')
        result = ReviewEngine().review(path)
        assert any(f.rule == "hardcoded-secret" for f in result.findings)

    def test_ignores_innocuous_names(self, tmp_path):
        path = _write(tmp_path, "app.py", "name = 'password-guess'\n")
        result = ReviewEngine().review(path)
        assert not any(f.rule == "hardcoded-secret" for f in result.findings)


class TestNestedLoopAnalyzer:
    def test_detects_nested_loop(self, tmp_path):
        path = _write(
            tmp_path,
            "app.py",
            "for i in range(1):\n    for j in range(1):\n        pass\n",
        )
        result = ReviewEngine().review(path)
        nested = [f for f in result.findings if f.rule == "nested-loop"]
        assert len(nested) == 1
        assert nested[0].line == 2

    def test_flat_loop_has_no_finding(self, tmp_path):
        path = _write(tmp_path, "app.py", "for i in range(1):\n    print(i)\n")
        result = ReviewEngine().review(path)
        assert not any(f.rule == "nested-loop" for f in result.findings)


class TestUnusedImportAnalyzer:
    def test_detects_unused_import(self, tmp_path):
        path = _write(tmp_path, "app.py", "import os\nimport json\nprint(json.dumps({}))\n")
        result = ReviewEngine().review(path)
        unused = [f for f in result.findings if f.rule == "unused-import"]
        assert [f.evidence for f in unused] == ["import os"]

    def test_alias_and_from_imports(self, tmp_path):
        path = _write(
            tmp_path,
            "app.py",
            "from pathlib import Path as P\nimport re as unused_alias\nx = P('.')\n",
        )
        result = ReviewEngine().review(path)
        unused = [f for f in result.findings if f.rule == "unused-import"]
        assert [f.evidence for f in unused] == ["import re as unused_alias"]

    def test_import_star_ignored(self, tmp_path):
        path = _write(tmp_path, "app.py", "from m import *\n")
        result = ReviewEngine().review(path)
        assert not any(f.rule == "unused-import" for f in result.findings)


class TestLongFunctionAnalyzer:
    def test_detects_long_function(self, tmp_path):
        body = "\n".join(["    x = 1"] * 30)
        path = _write(tmp_path, "app.py", f"def long_fn():\n{body}\n")
        analyzer = LongFunctionAnalyzer(threshold=10)
        result = ReviewEngine(analyzers=[analyzer]).review(path)
        long_fns = [f for f in result.findings if f.rule == "long-function"]
        assert len(long_fns) == 1
        assert "long_fn" in long_fns[0].message
        assert long_fns[0].severity == Severity.MEDIUM

    def test_short_function_clean(self, tmp_path):
        path = _write(tmp_path, "app.py", "def f():\n    return 1\n")
        result = ReviewEngine().review(path)
        assert not any(f.rule == "long-function" for f in result.findings)


class TestTodoFIXMEAnalyzer:
    def test_detects_markers(self, tmp_path):
        path = _write(tmp_path, "app.py", "x = 1  # TODO: refactor\n# FIXME: bug\n")
        result = ReviewEngine().review(path)
        markers = [f for f in result.findings if f.rule == "todo-fixme"]
        assert len(markers) == 2
        assert markers[0].severity == Severity.INFO
        assert all(f.evidence for f in markers)


class TestReviewEngineFailureBehavior:
    def test_missing_path_reported(self, tmp_path):
        result = ReviewEngine().review(tmp_path / "does-not-exist.py")
        assert result.count() == 0
        assert result.errors and "not found" in result.errors[0]

    def test_unparseable_file_is_structured_finding(self, tmp_path):
        path = _write(tmp_path, "broken.py", "def f(:\n    pass\n")
        result = ReviewEngine().review(path)
        parse_errors = [f for f in result.findings if f.rule == "parse-error"]
        assert len(parse_errors) == 1
        assert parse_errors[0].severity == Severity.HIGH
        assert parse_errors[0].line == 1

    def test_not_a_file_reported(self, tmp_path):
        result = ReviewEngine().review_files([tmp_path])
        assert result.errors

    def test_repository_scan_skips_ignored_dirs(self, tmp_path):
        _write(tmp_path, "src/a.py", "import os\n")
        _write(tmp_path, ".venv/x.py", "def bad(:\n")
        result = ReviewEngine().review_repository(tmp_path)
        assert len(result.files_scanned) == 1
        assert not any(f.rule == "parse-error" for f in result.findings)

    def test_analyzer_error_recorded_not_fatal(self, tmp_path):
        class Boom:
            rule = "boom"

            def analyze(self, path, tree, source_lines):
                raise RuntimeError("boom")

        path = _write(tmp_path, "app.py", "x = 1\n")
        result = ReviewEngine(analyzers=[Boom()]).review(path)
        assert any("boom failed" in e for e in result.errors)


class TestReviewEngineIntegration:
    def test_review_repository_real_code(self, tmp_path):
        _write(tmp_path, "src/secrets.py", "api_key = '1234567890abcdef'\n")
        _write(
            tmp_path,
            "src/work.py",
            "import math\n"
            "def compute():\n"
            "    for a in range(1):\n"
            "        for b in range(1):\n"
            "            return a + b\n",
        )
        _write(tmp_path, "src/main.py", "import json\nimport sys\nprint(sys.argv)\n")
        result = ReviewEngine().review_repository(tmp_path)
        assert len(result.files_scanned) == 3
        rules = {f.rule for f in result.findings}
        assert "hardcoded-secret" in rules
        assert "nested-loop" in rules
        assert "unused-import" in rules
        assert result.errors == []

    def test_list_rules(self):
        engine = ReviewEngine()
        assert "hardcoded-secret" in engine.list_rules()
        assert "parse-error" not in engine.list_rules()

    def test_single_file_review(self, tmp_path):
        path = _write(tmp_path, "app.py", "import os\n")
        result = ReviewEngine().review(path)
        assert result.count() >= 1
        assert result.files_scanned == [str(path)]
