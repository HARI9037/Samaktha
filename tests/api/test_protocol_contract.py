"""M1 — Protocol contract tests.

These tests define the expected wire protocol for the Rust TUI migration.
They should FAIL initially (red phase) and pass after protocol implementation.
"""

import pytest
from pydantic import ValidationError

# These imports will work after app/api/protocol.py is created
# from app.api.protocol import (
#     ProtocolVersion,
#     EventEnvelope,
#     ExecutionCreateRequest,
#     ExecutionCreateResponse,
#     ApprovalDecisionRequest,
#     VersionNegotiationRequest,
#     VersionNegotiationResponse,
#     PROTOCOL_VERSION,
#     PROTOCOL_VERSION_UNSUPPORTED_ERROR,
# )


class TestProtocolVersion:
    """Test protocol version constants and negotiation."""

    def test_protocol_version_constant_exists(self):
        """PROTOCOL_VERSION should be defined as '1.0'."""
        # This will fail until protocol.py defines it
        from app.api.protocol import PROTOCOL_VERSION
        assert PROTOCOL_VERSION == "1.0"

    def test_version_negotiation_supported(self):
        """Client requesting supported version should succeed."""
        from app.api.protocol import VersionNegotiationRequest, VersionNegotiationResponse

        request = VersionNegotiationRequest(client_version="1.0")
        response = VersionNegotiationResponse(
            supported=True,
            server_version="1.0",
            error=None
        )
        assert response.supported is True
        assert response.server_version == "1.0"

    def test_version_negotiation_unsupported_major_fails_closed(self):
        """Client requesting unsupported major version must fail closed."""
        from app.api.protocol import VersionNegotiationRequest, VersionNegotiationResponse
        from app.api.protocol import PROTOCOL_VERSION_UNSUPPORTED_ERROR

        request = VersionNegotiationRequest(client_version="2.0")
        response = VersionNegotiationResponse(
            supported=False,
            server_version="1.0",
            error=PROTOCOL_VERSION_UNSUPPORTED_ERROR
        )
        assert response.supported is False
        assert response.error == PROTOCOL_VERSION_UNSUPPORTED_ERROR

    def test_version_negotiation_unknown_fields_rejected(self):
        """Unknown fields in version negotiation must be rejected (extra=forbid)."""
        from app.api.protocol import VersionNegotiationRequest

        with pytest.raises(ValidationError) as exc_info:
            VersionNegotiationRequest(client_version="1.0", unknown_field="value")
        assert "extra" in str(exc_info.value).lower() or "forbid" in str(exc_info.value).lower()


class TestIdempotencyKey:
    """Test idempotency key on execution creation."""

    def test_execution_create_request_accepts_idempotency_key(self):
        """POST /executions request should accept optional idempotency_key."""
        from app.api.protocol import ExecutionCreateRequest

        request = ExecutionCreateRequest(
            message="test",
            idempotency_key="client-key-123"
        )
        assert request.idempotency_key == "client-key-123"

    def test_execution_create_request_idempotency_key_optional(self):
        """Idempotency key should be optional."""
        from app.api.protocol import ExecutionCreateRequest

        request = ExecutionCreateRequest(message="test")
        assert request.idempotency_key is None

    def test_execution_create_rejects_unknown_fields(self):
        """Extra fields on execution create must be rejected (extra=forbid)."""
        from app.api.protocol import ExecutionCreateRequest

        with pytest.raises(ValidationError) as exc_info:
            ExecutionCreateRequest(message="test", unknown_field="value")
        assert "extra" in str(exc_info.value).lower() or "forbid" in str(exc_info.value).lower()


class TestEventEnvelope:
    """Test the typed event envelope with monotonic sequences."""

    def test_event_envelope_has_required_fields(self):
        """EventEnvelope must have sequence, execution_id, session_id, event_type, payload."""
        from app.api.protocol import EventEnvelope
        from app.core.events import RuntimeEventType

        envelope = EventEnvelope(
            sequence=1,
            execution_id="exec-123",
            session_id="session-456",
            event_type=RuntimeEventType.EXECUTION_CREATED,
            payload={"status": "created"},
            timestamp="2024-01-01T00:00:00Z"
        )
        assert envelope.sequence == 1
        assert envelope.execution_id == "exec-123"
        assert envelope.session_id == "session-456"
        assert envelope.event_type == RuntimeEventType.EXECUTION_CREATED

    def test_event_envelope_sequence_monotonic_per_execution(self):
        """Sequence numbers must be monotonic per execution (backend-enforced)."""
        from app.api.protocol import EventEnvelope
        from app.core.events import RuntimeEventType

        # First event
        e1 = EventEnvelope(
            sequence=1,
            execution_id="exec-123",
            session_id="session-456",
            event_type=RuntimeEventType.EXECUTION_CREATED,
            payload={},
            timestamp="2024-01-01T00:00:00Z"
        )
        # Second event
        e2 = EventEnvelope(
            sequence=2,
            execution_id="exec-123",
            session_id="session-456",
            event_type=RuntimeEventType.EXECUTION_STATE_CHANGED,
            payload={},
            timestamp="2024-01-01T00:00:01Z"
        )
        assert e2.sequence > e1.sequence

    def test_event_envelope_rejects_unknown_fields(self):
        """EventEnvelope must reject unknown fields (extra=forbid)."""
        from app.api.protocol import EventEnvelope
        from app.core.events import RuntimeEventType

        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(
                sequence=1,
                execution_id="exec-123",
                session_id="session-456",
                event_type=RuntimeEventType.EXECUTION_CREATED,
                payload={},
                unknown_field="value"
            )
        assert "extra" in str(exc_info.value).lower() or "forbid" in str(exc_info.value).lower()


class TestApprovalDecision:
    """Test opaque approval decision transport."""

    def test_approval_decision_only_accepts_allow_deny(self):
        """Approval decision must only accept 'allow' or 'deny'."""
        from app.api.protocol import ApprovalDecisionRequest

        allow_req = ApprovalDecisionRequest(approval_id="appr-123", decision="allow")
        assert allow_req.decision == "allow"

        deny_req = ApprovalDecisionRequest(approval_id="appr-123", decision="deny")
        assert deny_req.decision == "deny"

    def test_approval_decision_rejects_invalid_decision(self):
        """Invalid decision values must be rejected."""
        from app.api.protocol import ApprovalDecisionRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApprovalDecisionRequest(approval_id="appr-123", decision="maybe")

    def test_approval_decision_no_permit_fields(self):
        """Approval decision must not contain permit, capability, or target fields."""
        from app.api.protocol import ApprovalDecisionRequest

        # These fields should not exist on the model
        req = ApprovalDecisionRequest(approval_id="appr-123", decision="allow", reasons=["user approved"])
        assert not hasattr(req, 'permit')
        assert not hasattr(req, 'capability')
        assert not hasattr(req, 'target')
        assert not hasattr(req, 'tool')
        assert not hasattr(req, 'path')


class TestSSECursorBinding:
    """Test SSE cursor (after parameter) binding to execution + session."""

    def test_events_endpoint_accepts_after_cursor(self):
        """GET /executions/{id}/events should accept 'after' parameter."""
        from app.api.protocol import EventsCursorRequest

        cursor = EventsCursorRequest(after=5)
        assert cursor.after == 5

    def test_events_cursor_after_is_exclusive(self):
        """'after=N' should mean sequence > N (exclusive)."""
        from app.api.protocol import EventsCursorRequest

        cursor = EventsCursorRequest(after=5)
        # This documents the expected behavior; implementation enforces it
        assert cursor.after == 5  # Client requests events with sequence > 5

    def test_events_cursor_binds_to_execution(self):
        """Cursor must be validated against execution_id (backend enforcement tested separately)."""
        from app.api.protocol import EventsCursorRequest

        cursor = EventsCursorRequest(after=10)
        assert cursor.after == 10


class TestCursorExpiredResponse:
    """Test structured cursor-expired response for stale cursors."""

    def test_cursor_expired_response_structure(self):
        """Cursor-expired response must have structured bounds, not silent skip."""
        from app.api.protocol import CursorExpiredResponse

        response = CursorExpiredResponse(
            error="CURSOR_EXPIRED",
            message="Cursor predates retained history",
            earliest_sequence=100,
            latest_sequence=150
        )
        assert response.error == "CURSOR_EXPIRED"
        assert response.earliest_sequence == 100
        assert response.latest_sequence == 150


class TestExplicitDTOsNoRawSerialization:
    """Test that public DTOs are explicit and don't leak internals."""

    def test_execution_state_response_excludes_internals(self):
        """ExecutionStateResponse must not contain permit, secrets, or raw metadata."""
        from app.api.protocol import ExecutionStateResponse

        response = ExecutionStateResponse(
            execution_id="exec-123",
            status="running",
            principal_id="local",
            session_id="session-456",
            pending_approval=False,
            result_available=False,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            completed_at=None,
            error=None
        )
        # Verify no internal fields exist
        assert not hasattr(response, 'permit')
        assert not hasattr(response, 'integrity_digest')
        assert not hasattr(response, 'secret')
        assert not hasattr(response, 'raw_metadata')


class TestResynchronizationSignal:
    """Test explicit resynchronization signal on sequence gap."""

    def test_resync_signal_structure(self):
        """Resynchronization signal must have defined structure."""
        from app.api.protocol import ResynchronizationSignal

        signal = ResynchronizationSignal(
            type="RESYNC",
            expected_sequence=10,
            actual_sequence=12,
            message="Sequence gap detected"
        )
        assert signal.type == "RESYNC"
        assert signal.expected_sequence == 10
        assert signal.actual_sequence == 12


if __name__ == "__main__":
    pytest.main([__file__, "-v"])