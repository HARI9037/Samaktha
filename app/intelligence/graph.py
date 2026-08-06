from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    kind: str
    label: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    relation: str
    target: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    version: str = "17.0.1"

    def neighbors(self, node_id: str, relation: str | None = None) -> tuple[str, ...]:
        targets = [
            edge.target
            for edge in self.edges
            if edge.source == node_id and (relation is None or edge.relation == relation)
        ]
        return tuple(targets)


class KnowledgeGraphBuilder:
    def build(self, *, project: str, repositories: list[str], files: list[str]) -> KnowledgeGraph:
        nodes = [GraphNode(project, "Project", project)]
        edges: list[GraphEdge] = []
        for repo in repositories:
            nodes.append(GraphNode(repo, "Repository", repo))
            edges.append(GraphEdge(project, "contains", repo))
        for file in files:
            nodes.append(GraphNode(file, "File", file))
        return KnowledgeGraph(nodes=tuple(nodes), edges=tuple(edges))

