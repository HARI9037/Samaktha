from __future__ import annotations

from pathlib import Path

from app.developer.code import CallGraphBuilder, CodeExplorer, DeadCodeAnalyzer, DuplicateDetector, RenamePlanner, ReferenceFinder, SymbolResolver
from app.developer.ci import CIInspector, DependencyAuditor, EnvironmentValidator
from app.developer.debugging import Debugger, ExceptionClassifier, FailureAnalyzer, RegressionAnalyzer
from app.developer.process import BackgroundJob, JobController, LogStreamer, ProcessManager
from app.developer.project import ModuleExplorer, ProjectExplorer, ProjectSummarizer
from app.developer.repository.inspector import RepositoryInspector
from app.developer.testing import CoverageInspector, ImpactAnalyzer, RegressionPredictor
from app.developer.workspace import WorkspaceIndex, WorkspaceManager, WorkspaceSearcher
from app.shell.command_router import CommandRouter, command_names


def test_repository_detection_and_summary(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("# Repo\nHello", encoding="utf-8")
    (tmp_path / "app.py").write_text("import os\n", encoding="utf-8")
    inspector = RepositoryInspector(tmp_path)
    summary = inspector.inspect()
    assert summary.root == str(tmp_path.resolve())
    assert summary.health.is_repository
    assert "Python" in summary.languages
    assert summary.readme_summary == "# Repo"


def test_nested_repository_detection(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    summary = RepositoryInspector(tmp_path).inspect()
    assert nested.as_posix() in summary.health.nested_repositories[0].replace("\\", "/")


def test_missing_git_and_monorepo_detection(tmp_path):
    (tmp_path / "service").mkdir()
    (tmp_path / "service" / "README.md").write_text("Service", encoding="utf-8")
    summary = RepositoryInspector(tmp_path).inspect()
    assert summary.health.missing_git


def test_code_intelligence_cross_file_lookup(tmp_path):
    (tmp_path / "a.py").write_text("def alpha():\n    beta()\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def beta():\n    return 1\n", encoding="utf-8")
    index = CodeExplorer().index(tmp_path)
    assert "alpha" in index.symbols[str(tmp_path / "a.py")]
    assert SymbolResolver().resolve(index, "alpha") == [str(tmp_path / "a.py")]
    assert ReferenceFinder().find(index, "beta") == [str(tmp_path / "a.py")]
    assert CallGraphBuilder().build(tmp_path)[str(tmp_path / "a.py")] == ["beta"]
    assert DuplicateDetector().find(tmp_path) == []
    assert "alpha" in DeadCodeAnalyzer().find(index)
    assert RenamePlanner().plan(index, "alpha", "gamma")["from"] == ["alpha"]


def test_process_manager_and_background_jobs():
    job = BackgroundJob(job_id="job-1", command="pytest")
    manager = ProcessManager()
    manager.registry.register(job)
    assert "job-1" in manager.registry.jobs
    assert LogStreamer().stream(job) == []
    JobController().cancel(job)
    assert job.status == "cancelled"


def test_debugging_and_review_heuristics():
    trace = "Traceback\nTypeError: bad call"
    assert ExceptionClassifier().classify(trace) == "type"
    assert FailureAnalyzer().analyze(trace)["classification"] == "type"
    assert RegressionAnalyzer().compare("a", "b")["regressed"]
    assert Debugger().summarize(trace) == "type"


def test_workspace_and_project_helpers(tmp_path):
    ws = WorkspaceManager([tmp_path])
    assert str(tmp_path.resolve()) in ws.roots[0]
    index = WorkspaceIndex(repositories=[str(tmp_path)])
    assert WorkspaceSearcher().search(index, tmp_path.name)
    assert ProjectExplorer(root=str(tmp_path), architecture={}).root == str(tmp_path)
    assert isinstance(ProjectSummarizer().summary, str)
    assert ModuleExplorer().modules == {}


def test_ci_and_testing_helpers():
    inspector = CIInspector()
    assert inspector.inspect([".github/workflows/build.yml"]) == ["GitHub Actions"]
    assert DependencyAuditor().audit(["pkg==1.0", "other"])
    assert EnvironmentValidator().validate({"A": "", "B": "1"}) == ["A"]
    assert CoverageInspector().inspect(10, 5) == 0.5
    assert RegressionPredictor().predict(["a.py"]) == ["a.py"]
    assert ImpactAnalyzer().analyze(["a.py"]) == ["a.py"]


def test_developer_commands_are_routed():
    assert "repo" in command_names()
    router = CommandRouter()
    result = router.parse("/repo")
    assert result == ("repo", [])
