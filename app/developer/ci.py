from __future__ import annotations


class CIInspector:
    def inspect(self, root_files: list[str]) -> list[str]:
        found = []
        for name in root_files:
            lower = name.lower()
            if "github/workflows" in lower:
                found.append("GitHub Actions")
            if "gitlab-ci" in lower:
                found.append("GitLab")
            if "azure-pipelines" in lower:
                found.append("Azure")
        return found


class DependencyAuditor:
    def audit(self, deps: list[str]) -> list[str]:
        return [dep for dep in deps if "==" not in dep]


class EnvironmentValidator:
    def validate(self, env: dict[str, str]) -> list[str]:
        return sorted(k for k, v in env.items() if not v)


class CompatibilityChecker:
    def check(self, versions: list[str]) -> bool:
        return bool(versions)

