from __future__ import annotations

from dataclasses import dataclass

from app.runtime_parallel.graph import ExecutionGraph


@dataclass
class DependencyResolver:
    def validate(self, graph: ExecutionGraph) -> None:
        self.topological_order(graph)

    def detect_cycles(self, graph: ExecutionGraph) -> bool:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for dep in graph.dependencies.get(node, []):
                if visit(dep):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in graph.task_ids)

    def topological_order(self, graph: ExecutionGraph) -> list[str]:
        indegree = {task: 0 for task in graph.task_ids}
        children: dict[str, list[str]] = {task: [] for task in graph.task_ids}
        for task, deps in graph.dependencies.items():
            indegree.setdefault(task, 0)
            for dep in deps:
                indegree.setdefault(dep, 0)
                indegree[task] += 1
                children.setdefault(dep, []).append(task)
        ready = sorted([task for task, deg in indegree.items() if deg == 0])
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for child in sorted(children.get(node, [])):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort()
        return order

    def levels(self, graph: ExecutionGraph) -> list[list[str]]:
        indegree = {task: 0 for task in graph.task_ids}
        children: dict[str, list[str]] = {task: [] for task in graph.task_ids}
        for task, deps in graph.dependencies.items():
            indegree.setdefault(task, 0)
            for dep in deps:
                indegree.setdefault(dep, 0)
                indegree[task] += 1
                children.setdefault(dep, []).append(task)
        ready = sorted([task for task, deg in indegree.items() if deg == 0])
        levels: list[list[str]] = []
        while ready:
            current = list(ready)
            levels.append(current)
            next_ready: list[str] = []
            for node in current:
                for child in sorted(children.get(node, [])):
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        next_ready.append(child)
            ready = sorted(dict.fromkeys(next_ready))
        return levels
