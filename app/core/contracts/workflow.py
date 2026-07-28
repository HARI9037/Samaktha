from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.contracts.planning import PlanTask


class TaskDependency(BaseModel):
    """Represents a dependency relationship for a task."""

    task_id: str
    depends_on: list[str] = Field(default_factory=list)


class ExecutionGraph(BaseModel):
    """Dependency-aware execution graph for deterministic parallel workflow scheduling."""

    tasks: list[PlanTask] = Field(default_factory=list)
    dependencies: list[TaskDependency] = Field(default_factory=list)

    def detect_cycles(self) -> bool:
        """Return True if a cycle is detected in the dependency graph."""
        graph: dict[str, list[str]] = {
            dep.task_id: dep.depends_on for dep in self.dependencies
        }
        visited: set[str] = set()
        stack: set[str] = set()

        def visit(node: str) -> bool:
            if node in stack:
                return True
            if node in visited:
                return False

            visited.add(node)
            stack.add(node)
            for neighbor in graph.get(node, []):
                if visit(neighbor):
                    return True
            stack.remove(node)
            return False

        for task_id in graph:
            if visit(task_id):
                return True
        return False

    def get_ready_tasks(self, completed_task_ids: set[str], failed_task_ids: set[str]) -> list[PlanTask]:
        """Return a deterministic list of tasks that have all dependencies met and are not failed/blocked."""
        graph_deps = {dep.task_id: dep.depends_on for dep in self.dependencies}
        ready: list[PlanTask] = []
        
        for task in self.tasks:
            if task.task_id in completed_task_ids or task.task_id in failed_task_ids:
                continue
                
            deps = graph_deps.get(task.task_id, task.dependencies)
            
            # If any dependency failed, this task cannot be ready
            if any(dep in failed_task_ids for dep in deps):
                continue
                
            # If all dependencies are completed, it's ready.
            if all(dep in completed_task_ids for dep in deps):
                ready.append(task)
                
        return ready

    def get_blocked_tasks(self, failed_task_ids: set[str]) -> list[PlanTask]:
        """Return tasks that cannot execute because a dependency has failed."""
        graph_deps = {dep.task_id: dep.depends_on for dep in self.dependencies}
        blocked: list[PlanTask] = []
        
        children: dict[str, list[str]] = {task.task_id: [] for task in self.tasks}
        for task in self.tasks:
            deps = graph_deps.get(task.task_id, task.dependencies)
            for d in deps:
                if d in children:
                    children[d].append(task.task_id)
                    
        blocked_ids = set()
        queue = list(failed_task_ids)
        
        while queue:
            curr = queue.pop(0)
            for child in children.get(curr, []):
                if child not in blocked_ids and child not in failed_task_ids:
                    blocked_ids.add(child)
                    queue.append(child)
                    
        for task in self.tasks:
            if task.task_id in blocked_ids:
                blocked.append(task)
                
        return blocked
