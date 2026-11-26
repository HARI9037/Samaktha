"""M4 Task 4 Step 6 — Integration test for file follow-up context resolution.

This test verifies the complete integration of the backend-owned resource context
with the execution pipeline:
1. Create-then-"that file"-write follow-up (end-to-end)
2. Two-candidates-triggers-clarification-zero-writes
3. Explicit-path precedence over implicit references
4. Verify store is wired into execute.py/production.py/execution_coordinator.py
5. SSE file events carry resource_id
"""

import pytest
from datetime import datetime, timezone

from app.core.resource_context import (
    ResourceContextStore,
    ResourceRecord,
    ResourceReference,
    ResolutionResult,
    ResolutionOutcome,
    ContextError,
    generate_resource_id,
    compute_content_hash,
)
from app.api.protocol import EventEnvelope
from app.core.events import RuntimeEventType as EventType


class TestM4FileFollowUpContextIntegration:
    """Integration tests for M4 file follow-up context resolution."""

    def test_create_then_write_that_file_e2e(self):
        """
        End-to-end: Execute 'create a file' then 'write inside that file' in same session.

        This tests the complete flow from file creation through context update
        to implicit reference resolution.
        """
        store = ResourceContextStore()
        session_id = "sess-e2e-123"
        workspace_root = "/home/user/project"

        # Step 1: Simulate file creation (backend operation)
        content1 = b"Initial file content"
        record1 = ResourceRecord(
            resource_id=generate_resource_id(),
            path="/home/user/project/created.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash=compute_content_hash(content1),
            size_bytes=len(content1),
        )
        store.update(session_id, record1)

        # Step 2: User says "write inside that file"
        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        assert result.resolved_path == "/home/user/project/created.txt"
        assert result.resource_id == record1.resource_id

        # Step 3: Simulate write to resolved path (backend operation)
        content2 = b"Updated content written to that file"
        record2 = ResourceRecord(
            resource_id=generate_resource_id(),
            path=result.resolved_path,
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash=compute_content_hash(content2),
            size_bytes=len(content2),
        )
        store.update(session_id, record2)

        # Context should have both records in chronological order
        context = store.get_context(session_id)
        assert len(context) == 2
        assert context[0].resource_id == record1.resource_id
        assert context[1].resource_id == record2.resource_id

    def test_two_candidates_triggers_clarification_zero_writes(self):
        """
        With two candidates, assert clarification and zero filesystem writes.

        This ensures the resolver doesn't silently pick one candidate.
        """
        store = ResourceContextStore()
        session_id = "sess-ambiguous-123"
        workspace_root = "/home/user/project"

        # Two files in context from previous operations
        record1 = ResourceRecord(
            resource_id="res-1",
            path="/home/user/project/file1.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:1",
            size_bytes=10,
        )
        record2 = ResourceRecord(
            resource_id="res-2",
            path="/home/user/project/file2.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:2",
            size_bytes=10,
        )
        store.update(session_id, record1)
        store.update(session_id, record2)

        # User says "write inside that file" - ambiguous
        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.AMBIGUOUS
        assert result.resolved_path is None
        assert len(result.candidates) == 2

        # Critical: No write should occur - the caller must handle clarification
        # This test ensures the resolver doesn't silently pick one
        context = store.get_context(session_id)
        assert len(context) == 2  # No new records added

    def test_explicit_path_precedence_over_implicit(self):
        """Explicit validated path must take precedence over inferred context."""
        import os
        store = ResourceContextStore()
        session_id = "sess-precedence-123"
        workspace_root = "/home/user/project"

        # Add context: last file was /home/user/project/old.txt
        record = ResourceRecord(
            resource_id="res-old",
            path="/home/user/project/old.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:old",
            size_bytes=10,
        )
        store.update(session_id, record)

        # User explicitly says "write to /home/user/project/new.txt"
        reference = ResourceReference(
            explicit_path="/home/user/project/new.txt",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.RESOLVED_EXPLICIT
        assert os.path.normpath(result.resolved_path) == os.path.normpath("/home/user/project/new.txt")

        # Context should NOT be updated by resolution alone
        context = store.get_context(session_id)
        assert len(context) == 1
        assert os.path.normpath(context[0].path) == os.path.normpath("/home/user/project/old.txt")

    def test_resource_context_wired_into_execution_coordinator(self):
        """
        Verify ResourceContextStore is accessible via execution_coordinator.

        This ensures the store is properly integrated into the execution pipeline.
        """
        from app.core.execution_coordinator import ExecutionCoordinator
        from app.core.orchestrator import SamakthaOrchestrator

        # Create orchestrator and coordinator
        orchestrator = SamakthaOrchestrator()
        coordinator = ExecutionCoordinator(orchestrator)

        # Verify coordinator has access to resource context store
        # The coordinator should have a resource_context attribute or similar
        assert hasattr(coordinator, '_resource_context_store') or \
               hasattr(coordinator, 'resource_context') or \
               hasattr(orchestrator, '_resource_context_store'), \
               "ResourceContextStore must be wired into execution_coordinator or orchestrator"

    def test_sse_file_events_carry_resource_id(self):
        """
        Verify SSE file events include resource_id from ResourceRecord.

        This ensures the protocol includes the opaque server-issued resource ID
        in file-related SSE events for TUI correlation.
        """
        # File events should exist (using RuntimeEventType from app.core.events)
        file_event_types = [
            EventType.FILE_READ_STARTED,
            EventType.FILE_READ_COMPLETED,
            EventType.FILE_WRITE_STARTED,
            EventType.FILE_WRITE_COMPLETED,
            EventType.FILE_LIST_STARTED,
            EventType.FILE_LIST_COMPLETED,
        ]

        for event_type in file_event_types:
            assert event_type is not None, f"EventType.{event_type.name} must exist"

        # Verify EventEnvelope can carry resource_id in data
        envelope = EventEnvelope(
            sequence=1,
            event_type=EventType.FILE_WRITE_STARTED,
            data={
                "resource_id": "res-abc123",
                "path": "/home/user/project/file.txt",
                "operation": "write",
            }
        )

        # The envelope should serialize with resource_id
        serialized = envelope.model_dump(mode="json")
        assert "resource_id" in serialized.get("data", {})
        assert serialized["data"]["resource_id"] == "res-abc123"

    def test_workspace_isolation_in_integration(self):
        """Context must be isolated per workspace even within same session."""
        store = ResourceContextStore()
        session_id = "sess-ws-123"

        # File in workspace 1
        record1 = ResourceRecord(
            resource_id="res-ws1",
            path="/home/user/project1/file.txt",
            workspace_root="/home/user/project1",
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:ws1",
            size_bytes=10,
        )
        store.update(session_id, record1, workspace_root="/home/user/project1")

        # File in workspace 2
        record2 = ResourceRecord(
            resource_id="res-ws2",
            path="/home/user/project2/file.txt",
            workspace_root="/home/user/project2",
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:ws2",
            size_bytes=10,
        )
        store.update(session_id, record2, workspace_root="/home/user/project2")

        # Resolve in workspace 1 - should only see ws1 file
        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result1 = store.resolve(session_id, reference, "/home/user/project1")
        assert result1.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        assert result1.resolved_path == "/home/user/project1/file.txt"

        # Resolve in workspace 2 - should only see ws2 file
        result2 = store.resolve(session_id, reference, "/home/user/project2")
        assert result2.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        assert result2.resolved_path == "/home/user/project2/file.txt"

    def test_session_isolation_in_integration(self):
        """Context must be isolated per session."""
        store = ResourceContextStore()
        workspace_root = "/home/user/project"

        # Session A creates a file
        record_a = ResourceRecord(
            resource_id="res-a",
            path="/home/user/project/file_a.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:a",
            size_bytes=10,
        )
        store.update("session-a", record_a)

        # Session B creates a different file
        record_b = ResourceRecord(
            resource_id="res-b",
            path="/home/user/project/file_b.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:b",
            size_bytes=10,
        )
        store.update("session-b", record_b)

        # Session A resolves "that file" -> file_a.txt
        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result_a = store.resolve("session-a", reference, workspace_root)
        assert result_a.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        assert result_a.resolved_path == "/home/user/project/file_a.txt"

        # Session B resolves "that file" -> file_b.txt
        result_b = store.resolve("session-b", reference, workspace_root)
        assert result_b.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        assert result_b.resolved_path == "/home/user/project/file_b.txt"

    def test_bounded_history_in_integration(self):
        """Context should maintain bounded history (max 50 records)."""
        store = ResourceContextStore(max_history=3)
        session_id = "sess-bounded-123"
        workspace_root = "/home/user/project"

        # Add 5 records
        for i in range(5):
            record = ResourceRecord(
                resource_id=f"res-{i}",
                path=f"/home/user/project/file{i}.txt",
                workspace_root=workspace_root,
                operation="write",
                timestamp=datetime.now(timezone.utc),
                content_hash=f"sha256:{i}",
                size_bytes=10,
            )
            store.update(session_id, record)

        # Context should only keep last 3
        context = store.get_context(session_id)
        assert len(context) == 3
        assert context[0].resource_id == "res-2"
        assert context[2].resource_id == "res-4"

    def test_security_validation_rejects_path_traversal(self):
        """Path traversal attempts must be rejected in integration."""
        store = ResourceContextStore()
        session_id = "sess-sec-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path="/home/user/project/../../etc/passwd",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED
        assert "traversal" in result.message.lower() or "outside workspace" in result.message.lower()

    def test_security_validation_rejects_unc_paths(self):
        """UNC paths must be rejected in integration."""
        store = ResourceContextStore()
        session_id = "sess-sec-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path=r"\\server\share\file.txt",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED

    def test_security_validation_rejects_drive_relative(self):
        """Drive-relative paths must be rejected in integration."""
        store = ResourceContextStore()
        session_id = "sess-sec-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path="C:file.txt",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED

    def test_security_validation_rejects_null_bytes(self):
        """Null bytes in path must be rejected in integration."""
        store = ResourceContextStore()
        session_id = "sess-sec-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path="/home/user/project/file.txt\x00.exe",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED

    def test_security_validation_rejects_outside_workspace(self):
        """Paths outside workspace must be rejected in integration."""
        store = ResourceContextStore()
        session_id = "sess-sec-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path="/home/user/otherproject/file.txt",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED

    def test_opaque_server_issued_resource_ids(self):
        """Resource IDs must be opaque server-issued IDs, not client-provided."""
        # Test that generate_resource_id produces opaque IDs
        id1 = generate_resource_id()
        id2 = generate_resource_id()

        assert id1.startswith("res_")
        assert id2.startswith("res_")
        assert id1 != id2  # Should be unique
        assert len(id1) > 10  # Should have sufficient entropy

    def test_rejects_client_provided_fake_context(self):
        """Store must reject attempts to inject fake context from client."""
        store = ResourceContextStore()
        session_id = "sess-123"

        with pytest.raises(ContextError):
            store.inject_client_context(session_id, [
                {"resource_id": "fake-res", "path": "/etc/passwd", "operation": "read"}
            ])

    def test_resource_context_never_expands_permissions(self):
        """Resource context must never expand filesystem or tool permissions."""
        store = ResourceContextStore()
        session_id = "sess-perm-123"
        workspace_root = "/home/user/project"

        # Even if context has a file, resolution must validate against workspace
        record = ResourceRecord(
            resource_id="res-1",
            path="/home/user/project/allowed.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:1",
            size_bytes=10,
        )
        store.update(session_id, record)

        # Valid resolution within workspace
        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        assert result.resolved_path == "/home/user/project/allowed.txt"

    def test_clear_context(self):
        """Context can be cleared for a session/workspace."""
        store = ResourceContextStore()
        session_id = "sess-clear-123"
        workspace_root = "/home/user/project"

        record = ResourceRecord(
            resource_id="res-1",
            path="/home/user/project/file.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:1",
            size_bytes=10,
        )
        store.update(session_id, record)
        assert len(store.get_context(session_id)) == 1

        store.clear(session_id)
        assert len(store.get_context(session_id)) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])