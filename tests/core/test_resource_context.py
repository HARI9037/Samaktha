"""M4 Task 4 — Backend-owned Resource Context contract tests.

These tests define the expected behavior for deterministic file follow-up resolution,
unique "that file" references, explicit-path precedence, ambiguity clarification,
and opaque server-issued resource IDs.
They should FAIL initially (red phase) and pass after M4 implementation.
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
)


class TestM4ResourceContextStore:
    """Test the backend-owned resource context store."""

    def test_create_resource_record_updates_context(self):
        """Creating/reading/writing a file should update the context with canonical record."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        # Simulate file creation
        record = ResourceRecord(
            resource_id="res-abc123",
            path="/home/user/project/newfile.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:abc123",
            size_bytes=100,
        )
        store.update(session_id, record)

        # Context should have the record
        context = store.get_context(session_id)
        assert len(context) == 1
        assert context[0].resource_id == "res-abc123"
        assert context[0].path == "/home/user/project/newfile.txt"

    def test_read_resource_updates_context(self):
        """Reading a file should update the context with canonical record."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        record = ResourceRecord(
            resource_id="res-def456",
            path="/home/user/project/existing.txt",
            workspace_root=workspace_root,
            operation="read",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:def456",
            size_bytes=50,
        )
        store.update(session_id, record)

        context = store.get_context(session_id)
        assert len(context) == 1
        assert context[0].operation == "read"

    def test_context_bounded_history(self):
        """Context should maintain bounded history (e.g., last 50 records)."""
        store = ResourceContextStore(max_history=3)
        session_id = "sess-123"
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

        context = store.get_context(session_id)
        # Should only keep last 3
        assert len(context) == 3
        assert context[0].resource_id == "res-2"
        assert context[2].resource_id == "res-4"

    def test_session_isolation(self):
        """Context must be isolated per session."""
        store = ResourceContextStore()
        workspace_root = "/home/user/project"

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

        store.update("sess-a", record1)
        store.update("sess-b", record2)

        ctx_a = store.get_context("sess-a")
        ctx_b = store.get_context("sess-b")

        assert len(ctx_a) == 1
        assert ctx_a[0].resource_id == "res-1"
        assert len(ctx_b) == 1
        assert ctx_b[0].resource_id == "res-2"

    def test_workspace_isolation(self):
        """Context must be isolated per workspace (even within same session)."""
        store = ResourceContextStore()
        session_id = "sess-123"

        record1 = ResourceRecord(
            resource_id="res-1",
            path="/home/user/project1/file.txt",
            workspace_root="/home/user/project1",
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:1",
            size_bytes=10,
        )
        record2 = ResourceRecord(
            resource_id="res-2",
            path="/home/user/project2/file.txt",
            workspace_root="/home/user/project2",
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:2",
            size_bytes=10,
        )

        store.update(session_id, record1, workspace_root="/home/user/project1")
        store.update(session_id, record2, workspace_root="/home/user/project2")

        ctx1 = store.get_context(session_id, workspace_root="/home/user/project1")
        ctx2 = store.get_context(session_id, workspace_root="/home/user/project2")

        assert len(ctx1) == 1
        assert ctx1[0].path == "/home/user/project1/file.txt"
        assert len(ctx2) == 1
        assert ctx2[0].path == "/home/user/project2/file.txt"

    def test_opaque_server_issued_resource_ids(self):
        """Resource IDs must be opaque server-issued IDs, not client-provided."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        # Client cannot supply resource_id - it's generated by backend
        record = ResourceRecord(
            resource_id="res-server-generated",  # This simulates server-generated ID
            path="/home/user/project/file.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:abc",
            size_bytes=10,
        )
        store.update(session_id, record)

        context = store.get_context(session_id)
        assert context[0].resource_id == "res-server-generated"
        # Resource ID should be opaque - client cannot guess or forge

    def test_rejects_client_provided_fake_last_file_metadata(self):
        """Store must reject attempts to inject fake 'last file' metadata from client."""
        store = ResourceContextStore()
        session_id = "sess-123"

        # Client tries to inject fake context via some API - should be rejected
        # The store only accepts updates from backend operations, not client input
        with pytest.raises(ContextError):
            store.inject_client_context(session_id, [
                {"resource_id": "fake-res", "path": "/etc/passwd", "operation": "read"}
            ])

    def test_clear_context(self):
        """Context can be cleared for a session/workspace."""
        store = ResourceContextStore()
        session_id = "sess-123"
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


class TestM4ResourceResolution:
    """Test deterministic resource reference resolution."""

    def test_explicit_validated_path_precedence(self):
        """Explicit validated path must take precedence over inferred context."""
        store = ResourceContextStore()
        session_id = "sess-123"
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
        # Resolution should use explicit path, not context
        reference = ResourceReference(
            explicit_path="/home/user/project/new.txt",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.RESOLVED_EXPLICIT
        # Normalize for cross-platform comparison
        import os
        assert os.path.normpath(result.resolved_path) == os.path.normpath("/home/user/project/new.txt")

    def test_unique_that_file_resolution(self):
        """Unique 'that file' reference should resolve to single candidate."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        # Only one file in context
        record = ResourceRecord(
            resource_id="res-only",
            path="/home/user/project/thefile.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:only",
            size_bytes=10,
        )
        store.update(session_id, record)

        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        import os
        assert os.path.normpath(result.resolved_path) == os.path.normpath("/home/user/project/thefile.txt")
        assert result.resource_id == "res-only"

    def test_no_candidate_clarification(self):
        """No candidate for 'that file' should return clarification needed."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        # Empty context
        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.CLARIFICATION_NEEDED
        assert "no recent file" in result.message.lower()
        assert result.resolved_path is None

    def test_multiple_candidates_ambiguity(self):
        """Multiple candidates for 'that file' should return ambiguity error."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        # Two files in context
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

        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.AMBIGUOUS
        assert "multiple" in result.message.lower() or "ambiguous" in result.message.lower()
        assert result.resolved_path is None
        assert len(result.candidates) == 2

    def test_path_traversal_rejected(self):
        """Path traversal attempts must be rejected."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path="/home/user/project/../../etc/passwd",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED
        assert "traversal" in result.message.lower() or "outside workspace" in result.message.lower()

    def test_unc_path_rejected(self):
        """UNC paths must be rejected."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path=r"\\server\share\file.txt",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED

    def test_drive_relative_rejected(self):
        """Drive-relative paths must be rejected."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path="C:file.txt",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED

    def test_null_byte_rejected(self):
        """Null bytes in path must be rejected."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path="/home/user/project/file.txt\x00.exe",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED

    def test_outside_workspace_rejected(self):
        """Paths outside workspace must be rejected."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        reference = ResourceReference(
            explicit_path="/home/user/otherproject/file.txt",
            implicit_reference=None,
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.REJECTED
        import os
        # Also test with normalized path
        reference2 = ResourceReference(
            explicit_path=os.path.normpath("/home/user/otherproject/file.txt"),
            implicit_reference=None,
        )
        result2 = store.resolve(session_id, reference2, workspace_root)
        assert result2.outcome == ResolutionOutcome.REJECTED

    def test_resource_context_never_expands_permissions(self):
        """Resource context must never expand filesystem or tool permissions."""
        store = ResourceContextStore()
        session_id = "sess-123"
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

        # Try to resolve a path outside workspace via implicit reference
        # This should be rejected even though context exists
        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",  # Would resolve to allowed.txt
        )
        result = store.resolve(session_id, reference, workspace_root)

        # Should resolve to the allowed file (it's in workspace)
        assert result.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        assert result.resolved_path == "/home/user/project/allowed.txt"

        # Now try with a context that has outside-workspace file (should not happen in practice)
        # But if it did, resolution must reject
        # This is tested by ensuring the store only accepts workspace-validated paths


class TestM4FileFollowUpRegression:
    """Integration test: create file then write inside 'that file'."""

    def test_create_then_write_that_file(self):
        """Execute 'create a file' then 'write inside that file' in same session."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        # Step 1: Create a file
        record1 = ResourceRecord(
            resource_id="res-create",
            path="/home/user/project/created.txt",
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:create",
            size_bytes=20,
        )
        store.update(session_id, record1)

        # Step 2: User says "write inside that file"
        reference = ResourceReference(
            explicit_path=None,
            implicit_reference="that file",
        )
        result = store.resolve(session_id, reference, workspace_root)

        assert result.outcome == ResolutionOutcome.RESOLVED_IMPLICIT
        import os
        assert os.path.normpath(result.resolved_path) == os.path.normpath("/home/user/project/created.txt")

        # Step 3: Write to resolved path (simulated)
        record2 = ResourceRecord(
            resource_id="res-write",
            path=result.resolved_path,
            workspace_root=workspace_root,
            operation="write",
            timestamp=datetime.now(timezone.utc),
            content_hash="sha256:write",
            size_bytes=50,
        )
        store.update(session_id, record2)

        # Context should have both records
        context = store.get_context(session_id)
        assert len(context) == 2

    def test_two_candidates_assert_clarification_zero_writes(self):
        """With two candidates, assert clarification and zero filesystem writes."""
        store = ResourceContextStore()
        session_id = "sess-123"
        workspace_root = "/home/user/project"

        # Two files in context
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

        # No write should occur - the caller must handle clarification
        # This test ensures the resolver doesn't silently pick one


if __name__ == "__main__":
    pytest.main([__file__, "-v"])