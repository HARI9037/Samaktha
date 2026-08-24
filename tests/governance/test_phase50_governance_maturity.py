"""P2.5 — Governance Maturity.

Policy-as-code governance for the runtime: versioned GovernancePolicy
documents (capability/provider/tool permission requirements), deterministic
risk classification, declarative approval policies, immutable hash-chained
execution records, a governance audit trail, policy-violation handling and
rollback/recovery policy — integrated into the canonical ToolExecutor and
ProviderExecutor without changing their ungoverned behavior.
"""
import json

import pytest

from app.core.contracts.policy import ApprovalDecision, ActionRisk
from app.core.contracts.planning import TaskStatus
from app.core.contracts import RoutingDecision, RuntimeContext
from app.db.base import SQLiteJsonTable
from app.governance import (
    ApprovalPolicyEngine,
    GovernanceAuditLog,
    GovernanceEngine,
    GovernancePolicy,
    ExecutionRecordStore,
    PolicyRegistrationError,
    PolicyRegistry,
    PolicyViolation,
    PolicyViolationError,
    RiskClassifier,
    RollbackPolicy,
    TargetType,
    ViolationHandler,
    build_execution_record,
    load_policy,
    load_policy_file,
    risk_at_least,
    security_level_for,
    validate_policy,
)
from app.governance.models import DecisionStatus
from app.runtime import ProviderExecutor, ToolExecutor
from app.tools import ToolInfo, ToolManager, ToolRegistry
from app.tools.base import Tool, ToolResult
from app.tools.framework.models import ToolPermission, ToolPolicy
from tests.conftest import approved_task


BASIC_POLICY = {
    "policy_id": "corp",
    "version": "1.0.0",
    "name": "Corporate baseline",
    "tools": [{"target": "notes.delete", "permissions": ["read"], "approval_required": True}],
    "capabilities": [{"target": "files.read", "permissions": ["read"]}],
    "providers": [{"target": "openai", "approval_required": True}],
}


# ---------------------------------------------------------------------------
# Policy-as-code foundation
# ---------------------------------------------------------------------------

class TestPolicyAsCode:

    def test_validate_policy_reports_missing_policy_id(self):
        problems = validate_policy({"version": "1.0.0", "name": "x"})
        assert problems

    def test_validate_policy_reports_missing_name(self):
        problems = validate_policy({"policy_id": "x", "version": "1.0.0"})
        assert problems

    def test_validate_policy_reports_bad_semver(self):
        problems = validate_policy({"policy_id": "x", "version": "not-a-version", "name": "x"})
        assert problems

    def test_validate_policy_reports_duplicate_tool_rules(self):
        policy = {
            **BASIC_POLICY,
            "tools": [*BASIC_POLICY["tools"], {"target": "notes.delete", "permissions": ["read"]}],
        }
        problems = validate_policy(policy)
        assert any("Duplicate tool permission rule" in p for p in problems)

    def test_validate_policy_reports_duplicate_capability_rules(self):
        policy = {
            **BASIC_POLICY,
            "capabilities": [
                *BASIC_POLICY["capabilities"],
                {"target": "files.read", "permissions": ["write"]},
            ],
        }
        problems = validate_policy(policy)
        assert any("Duplicate capability permission rule" in p for p in problems)

    def test_validate_policy_returns_empty_for_valid(self):
        assert validate_policy(BASIC_POLICY) == []

    def test_load_policy_builds_versioned_model(self):
        policy = load_policy(BASIC_POLICY)
        assert isinstance(policy, GovernancePolicy)
        assert policy.key == "corp@1.0.0"
        assert policy.rule_for(TargetType.TOOL, "notes.delete") is not None
        assert policy.rule_for(TargetType.CAPABILITY, "files.read") is not None
        assert policy.rule_for(TargetType.PROVIDER, "openai") is not None

    def test_load_policy_file_reads_json(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(BASIC_POLICY), encoding="utf-8")
        policy = load_policy_file(str(path))
        assert policy.policy_id == "corp"

    def test_registry_register_get_has_list_count(self):
        registry = PolicyRegistry()
        registry.register(load_policy(BASIC_POLICY))
        assert registry.has("corp@1.0.0")
        assert registry.has("corp")
        assert registry.get("corp@1.0.0").version == "1.0.0"
        assert registry.count() == 1
        assert len(registry.list()) == 1

    def test_registry_rejects_duplicate_key(self):
        registry = PolicyRegistry()
        registry.register(load_policy(BASIC_POLICY))
        with pytest.raises(PolicyRegistrationError):
            registry.register(load_policy(BASIC_POLICY))

    def test_registry_latest_returns_highest_version(self):
        registry = PolicyRegistry()
        registry.register(load_policy({**BASIC_POLICY, "version": "1.0.0"}))
        registry.register(load_policy({**BASIC_POLICY, "version": "1.2.0"}))
        registry.register(load_policy({**BASIC_POLICY, "version": "1.10.0"}))
        latest = registry.latest("corp")
        assert latest.version == "1.10.0"
        assert registry.latest("missing") is None


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

class TestRiskClassification:

    def test_admin_permissions_are_critical(self):
        engine = GovernanceEngine()
        risk, _ = engine.risk.classify(
            TargetType.TOOL, "sys.admin", permissions=[ToolPermission.ADMIN]
        )
        assert risk == ActionRisk.CRITICAL

    def test_delete_is_critical_execute_network_high_write_medium(self):
        engine = GovernanceEngine()
        assert engine.risk.classify(TargetType.TOOL, "a", permissions=[ToolPermission.DELETE])[0] == ActionRisk.CRITICAL
        assert engine.risk.classify(TargetType.TOOL, "a", permissions=[ToolPermission.EXECUTE])[0] == ActionRisk.HIGH
        assert engine.risk.classify(TargetType.TOOL, "a", permissions=[ToolPermission.NETWORK])[0] == ActionRisk.HIGH
        assert engine.risk.classify(TargetType.TOOL, "a", permissions=[ToolPermission.WRITE])[0] == ActionRisk.MEDIUM
        assert engine.risk.classify(TargetType.TOOL, "a", permissions=[ToolPermission.MODIFY])[0] == ActionRisk.MEDIUM

    def test_approval_required_elevates_to_high(self):
        engine = GovernanceEngine()
        risk, _ = engine.risk.classify(
            TargetType.TOOL, "notes.write", permissions=[ToolPermission.WRITE],
            approval_required=True,
        )
        assert risk_at_least(risk, ActionRisk.HIGH)

    def test_policy_risk_rule_overrides_defaults(self):
        policy = load_policy({
            "policy_id": "soft", "version": "1.0.0", "name": "Soft",
            "risks": [{"target": "notes.delete", "risk": "low"}],
        })
        engine = GovernanceEngine()
        risk, reasons = engine.risk.classify(
            TargetType.TOOL, "notes.delete", permissions=[ToolPermission.DELETE], policy=policy
        )
        assert risk == ActionRisk.LOW
        assert any("risk rule" in reason for reason in reasons)

    def test_default_risk_and_security_level(self):
        engine = GovernanceEngine()
        risk, _ = engine.risk.classify(TargetType.PROVIDER, "openai", permissions=())
        assert risk == ActionRisk.LOW
        assert security_level_for(ActionRisk.CRITICAL) == "critical"
        assert risk_at_least(ActionRisk.HIGH, ActionRisk.MEDIUM)
        assert not risk_at_least(ActionRisk.MEDIUM, ActionRisk.HIGH)


# ---------------------------------------------------------------------------
# Approval policies
# ---------------------------------------------------------------------------

class TestApprovalPolicies:

    def test_allow_without_rules(self):
        engine = ApprovalPolicyEngine()
        decision, _ = engine.decision(TargetType.TOOL, "notes.write", ActionRisk.MEDIUM)
        assert decision == ApprovalDecision.ALLOW

    def test_ask_user_for_high_risk(self):
        engine = ApprovalPolicyEngine()
        decision, _ = engine.decision(TargetType.TOOL, "notes.delete", ActionRisk.HIGH)
        assert decision == ApprovalDecision.ASK_USER

    def test_policy_approval_rule_exempts_high_risk(self):
        policy = load_policy({
            "policy_id": "flex", "version": "1.0.0", "name": "Flex",
            "approvals": [{"target": "notes.delete", "risk_at_least": "high", "require": False}],
        })
        engine = ApprovalPolicyEngine()
        decision, _ = engine.decision(
            TargetType.TOOL, "notes.delete", ActionRisk.HIGH, policy=policy
        )
        assert decision == ApprovalDecision.ALLOW

    def test_deny_when_permission_not_granted(self):
        engine = ApprovalPolicyEngine()
        decision, _ = engine.decision(
            TargetType.TOOL, "notes.delete", ActionRisk.HIGH,
            denied_permissions=[ToolPermission.DELETE],
        )
        assert decision == ApprovalDecision.DENY

    def test_required_reflects_policy_and_risk(self):
        policy = load_policy({
            "policy_id": "req", "version": "1.0.0", "name": "Req",
            "tools": [{"target": "notes.delete", "permissions": ["read"], "approval_required": True}],
        })
        engine = ApprovalPolicyEngine()
        required, reasons = engine.required(
            TargetType.TOOL, "notes.delete", ActionRisk.MEDIUM, policy=policy, rule_approval=True
        )
        assert required is True
        assert reasons


# ---------------------------------------------------------------------------
# Enforcement: tools, providers, capabilities
# ---------------------------------------------------------------------------

class TestPermissionEnforcement:

    def test_no_policy_is_permissive_with_declared_permissions(self):
        engine = GovernanceEngine()
        decision = engine.evaluate(
            TargetType.TOOL, "notes.write", declared_permissions=[ToolPermission.WRITE]
        )
        assert decision.allowed
        assert decision.granted_permissions == (ToolPermission.WRITE,)

    def test_tool_rule_grants_only_policy_permissions(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy(BASIC_POLICY))
        decision = engine.evaluate(
            TargetType.TOOL, "notes.delete", declared_permissions=[ToolPermission.DELETE]
        )
        assert decision.granted_permissions == (ToolPermission.READ,)
        assert not decision.allowed

    def test_tool_denied_when_required_permission_missing(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy(BASIC_POLICY))
        with pytest.raises(PolicyViolationError) as exc:
            engine.enforce_tool("notes.delete", declared_permissions=[ToolPermission.DELETE])
        assert exc.value.violation.code == "permission_denied"
        assert "delete" in exc.value.violation.message
        assert exc.value.violation.decision.decision == ApprovalDecision.DENY

    def test_tool_approval_required_for_declared_permission(self):
        engine = GovernanceEngine()
        policy = load_policy({
            "policy_id": "ap", "version": "1.0.0", "name": "Ap",
            "tools": [{"target": "email.send", "permissions": ["network"], "approval_required": True}],
        })
        engine.set_default_policy(policy)
        with pytest.raises(PolicyViolationError) as exc:
            engine.enforce_tool("email.send", declared_permissions=[ToolPermission.NETWORK])
        assert exc.value.violation.decision.decision == ApprovalDecision.ASK_USER
        assert exc.value.violation.decision.approval_required is True

    def test_capability_enforced_with_declared_permissions(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy(BASIC_POLICY))
        decision = engine.enforce_capability("files.read", "files_tool", declared_permissions=[ToolPermission.READ])
        assert decision.allowed

    def test_capability_rejected_when_requirements_uncovered(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy(BASIC_POLICY))
        with pytest.raises(PolicyViolationError) as exc:
            engine.enforce_capability("files.read", "files_tool", declared_permissions=[ToolPermission.WRITE])
        assert exc.value.violation.code == "capability_permissions_missing"

    def test_provider_enforced_via_rule(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy(BASIC_POLICY))
        with pytest.raises(PolicyViolationError) as exc:
            engine.enforce_provider("openai")
        assert exc.value.violation.code == "provider_blocked"
        assert exc.value.violation.decision.approval_required is True

    def test_provider_allowed_without_rule(self):
        engine = GovernanceEngine()
        decision = engine.enforce_provider("local")
        assert decision.allowed


# ---------------------------------------------------------------------------
# Immutable execution records
# ---------------------------------------------------------------------------

class TestExecutionRecords:

    @staticmethod
    def make_record(store, *, status=DecisionStatus.EXECUTED):
        return store.append(build_execution_record(
            request_id="req-1", task_id="task-1",
            target_type=TargetType.TOOL, target="notes.write",
            decision=ApprovalDecision.ALLOW.value, risk=ActionRisk.MEDIUM.value,
            status=status,
        ))

    def test_append_chains_hashes(self):
        store = ExecutionRecordStore()
        first = self.make_record(store)
        second = self.make_record(store)
        assert first.previous_hash == ""
        assert second.previous_hash == first.hash
        assert store.verify_chain()
        assert len(store) == 2
        assert store.last().record_id == second.record_id

    def test_duplicate_record_id_rejected(self):
        store = ExecutionRecordStore()
        first = self.make_record(store)
        with pytest.raises(ValueError):
            store.append(first)

    def test_tampering_detected(self):
        store = ExecutionRecordStore()
        first = self.make_record(store)
        second = self.make_record(store)
        mutated = second.model_copy(update={"status": DecisionStatus.FAILED})
        store._records[1] = mutated
        assert store.verify_chain() is False
        assert mutated.recompute_hash() != mutated.hash

    def test_backing_persistence_reloads_chain(self, tmp_path):
        backing = SQLiteJsonTable(str(tmp_path / "gov.db"), "executions")
        store = ExecutionRecordStore(backing)
        self.make_record(store)
        self.make_record(store)
        reloaded = ExecutionRecordStore(backing)
        assert len(reloaded) == 2
        assert reloaded.verify_chain()
        assert reloaded.last().hash == store.last().hash

    def test_no_update_or_delete_api(self):
        store = ExecutionRecordStore()
        assert not hasattr(store, "update")
        assert not hasattr(store, "delete")
        assert not hasattr(store, "clear")

    def test_distinct_events_have_unique_record_ids(self):
        store = ExecutionRecordStore()
        first = self.make_record(store)
        second = self.make_record(store)
        assert first.record_id != second.record_id

    def test_lookup_by_record_id(self):
        store = ExecutionRecordStore()
        record = self.make_record(store)
        assert store.get(record.record_id) is record
        assert store.get("missing-record-id") is None


# ---------------------------------------------------------------------------
# Governance audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail:

    def test_audit_records_monotonic_sequence_and_chain(self):
        audit = GovernanceAuditLog()
        a = audit.record("governance", "tool:notes.write", "u1", "allow")
        b = audit.record("execution", "tool:notes.write", "u1", "executed")
        assert a.seq == 0
        assert b.seq == 1
        assert b.previous_hash == a.hash
        assert audit.verify_chain()
        assert len(audit) == 2
        assert audit.last_seq == 1

    def test_audit_query_filters(self):
        audit = GovernanceAuditLog()
        audit.record("governance", "tool:a", "u1", "allow")
        audit.record("governance", "tool:b", "u2", "deny")
        audit.record("violation", "tool:b", "u2", "blocked")
        assert len(audit.query(category="governance")) == 2
        assert len(audit.query(result="deny")) == 1
        assert len(audit.query(category="violation", result="blocked")) == 1
        assert len(audit.query(subject="u1")) == 1

    def test_audit_tampering_detected(self):
        audit = GovernanceAuditLog()
        first = audit.record("governance", "tool:a", "u1", "allow")
        audit.record("governance", "tool:b", "u2", "deny")
        mutated = audit._entries[0].model_copy(update={"result": "executed"})
        mutated = mutated.model_copy(update={"hash": mutated.recompute_hash()})
        audit._entries[0] = mutated
        assert first.hash != mutated.hash
        assert audit.verify_chain() is False

    def test_audit_backing_persistence_reloads_chain(self, tmp_path):
        backing = SQLiteJsonTable(str(tmp_path / "gov.db"), "audit")
        audit = GovernanceAuditLog(backing)
        audit.record("governance", "tool:a", "u1", "allow")
        audit.record("violation", "tool:b", "u2", "blocked")
        reloaded = GovernanceAuditLog(backing)
        assert len(reloaded) == 2
        assert reloaded.verify_chain()
        assert reloaded.last_seq == 1


# ---------------------------------------------------------------------------
# Policy violation handling
# ---------------------------------------------------------------------------

class TestViolationHandling:

    def test_violation_handler_blocked_payload(self):
        audit = GovernanceAuditLog()
        handler = ViolationHandler(audit)
        violation = PolicyViolation(
            code="permission_denied", message="denied",
            target_type=TargetType.TOOL, target="notes.delete",
        )
        payload = handler.blocked(violation)
        assert payload["governance_blocked"] is True
        assert payload["governance_violation"] == "permission_denied"
        assert len(audit.query(category="violation", result="blocked")) == 1

    def test_engine_denial_is_audited(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy(BASIC_POLICY))
        with pytest.raises(PolicyViolationError):
            engine.enforce_tool("notes.delete", declared_permissions=[ToolPermission.DELETE])
        assert len(engine.audit.query(category="governance", result="deny")) == 1
        assert engine.audit.verify_chain()


# ---------------------------------------------------------------------------
# Rollback / recovery policy
# ---------------------------------------------------------------------------

class TestRollbackPolicy:

    def test_no_rollback_when_not_supported(self):
        policy = RollbackPolicy()
        rollback, reasons = policy.should_rollback(
            target_type=TargetType.TOOL, target="notes.write",
            failed=True, risk=ActionRisk.CRITICAL,
        )
        assert rollback is False
        assert "target does not support rollback" in reasons

    def test_rollback_on_high_risk_failure(self):
        policy = RollbackPolicy()
        rollback, _ = policy.should_rollback(
            target_type=TargetType.TOOL, target="email.send",
            rollback_supported=True, failed=True, risk=ActionRisk.HIGH,
        )
        assert rollback is True

    def test_rollback_on_supported_failure_regardless_of_risk(self):
        policy = RollbackPolicy()
        rollback, _ = policy.should_rollback(
            target_type=TargetType.TOOL, target="notes.read",
            rollback_supported=True, failed=True, risk=ActionRisk.LOW,
        )
        assert rollback is True

    def test_no_rollback_on_success(self):
        policy = RollbackPolicy()
        rollback, _ = policy.should_rollback(
            target_type=TargetType.TOOL, target="email.send",
            rollback_supported=True, failed=False, denied=False,
            risk=ActionRisk.CRITICAL,
        )
        assert rollback is False

    def test_policy_rule_forces_rollback(self):
        policy_obj = load_policy({
            "policy_id": "rb", "version": "1.0.0", "name": "Rb",
            "rollbacks": [{"target": "journal.commit", "when": "failure", "force": True}],
        })
        policy = RollbackPolicy()
        rollback, reasons = policy.should_rollback(
            target_type=TargetType.TOOL, target="journal.commit",
            failed=True, policy=policy_obj,
        )
        assert rollback is True
        assert any("forced" in reason for reason in reasons)

    def test_policy_rule_exempts_rollback(self):
        policy_obj = load_policy({
            "policy_id": "rb", "version": "1.0.0", "name": "Rb",
            "rollbacks": [{"target": "journal.cleanup", "when": "failure", "force": False}],
        })
        policy = RollbackPolicy()
        rollback, _ = policy.should_rollback(
            target_type=TargetType.TOOL, target="journal.cleanup",
            rollback_supported=True, failed=True, risk=ActionRisk.CRITICAL,
            policy=policy_obj,
        )
        assert rollback is False

    def test_engine_rollback_resolves_policy(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy({
            "policy_id": "rb", "version": "1.0.0", "name": "Rb",
            "rollbacks": [{"target": "journal.commit", "when": "failure", "force": True}],
        }))
        rollback, _ = engine.should_rollback(
            target_type=TargetType.TOOL, target="journal.commit", failed=True
        )
        assert rollback is True


# ---------------------------------------------------------------------------
# Runtime integration: ToolExecutor / ProviderExecutor
# ---------------------------------------------------------------------------

class EchoTool(Tool):
    name = "echo"

    async def run(self, arguments: dict) -> ToolResult:
        return ToolResult(ok=True, data={"output": "echo"})


class FailTool(Tool):
    name = "fail"

    async def run(self, arguments: dict) -> ToolResult:
        return ToolResult(ok=False, error="boom")


class TestExecutorIntegration:

    @staticmethod
    def build_executor(*, governance=None):
        registry = ToolRegistry()
        registry.register(
            tool_id="echo",
            tool=EchoTool(),
            info=ToolInfo(
                tool_id="echo", description="", capabilities=["echo"],
                permissions=["read"], policy=None,
            ),
        )
        registry.register(
            tool_id="fail",
            tool=FailTool(),
            info=ToolInfo(
                tool_id="fail", description="", capabilities=["fail"],
                permissions=["write"],
                policy=ToolPolicy(rollback_supported=True),
            ),
        )
        return ToolExecutor(ToolManager(registry), governance=governance)

    @staticmethod
    def routing(tool_id):
        return RoutingDecision(
            provider_id="", model_id="", reasoning_summary=f"tool:{tool_id}"
        )

    async def test_tool_executor_allowed_without_governance(self):
        executor = self.build_executor()
        result = await executor.execute(
            RuntimeContext(request_id="r1"),
            approved_task(task_id="t1", action_type="tool", metadata={"tool": "echo"}, inputs={"x": 1}),
            self.routing("echo"),
        )
        assert result.status == TaskStatus.COMPLETED
        assert result.output == {"output": "echo"}

    async def test_tool_executor_governance_allowed_records_execution(self):
        engine = GovernanceEngine()
        executor = self.build_executor(governance=engine)
        result = await executor.execute(
            RuntimeContext(request_id="r1"),
            approved_task(task_id="t1", action_type="tool", metadata={"tool": "echo"}, inputs={"x": 1}),
            self.routing("echo"),
        )
        assert result.status == TaskStatus.COMPLETED
        assert len(engine.records) == 1
        assert engine.records.last().status == DecisionStatus.EXECUTED
        assert engine.records.verify_chain()
        assert result.metadata["record_id"] == engine.records.last().record_id

    async def test_tool_executor_governance_blocked_undeclared(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy({
            "policy_id": "strict", "version": "1.0.0", "name": "Strict",
            "tools": [{"target": "echo", "permissions": ["execute"]}],
        }))
        executor = self.build_executor(governance=engine)
        result = await executor.execute(
            RuntimeContext(request_id="r1"),
            approved_task(task_id="t1", action_type="tool", metadata={"tool": "echo"}, inputs={"x": 1}),
            self.routing("echo"),
        )
        assert result.status == TaskStatus.FAILED
        assert result.metadata.get("governance_blocked") is True
        assert len(engine.records) == 1
        assert engine.records.last().status == DecisionStatus.BLOCKED
        assert engine.records.verify_chain()

    async def test_tool_executor_rollback_status_on_failure(self):
        engine = GovernanceEngine()
        executor = self.build_executor(governance=engine)
        result = await executor.execute(
            RuntimeContext(request_id="r1"),
            approved_task(task_id="t1", action_type="tool", metadata={"tool": "fail"}, inputs={"x": 1}),
            self.routing("fail"),
        )
        assert result.status == TaskStatus.FAILED
        assert engine.records.last().status == DecisionStatus.ROLLED_BACK
        assert result.metadata["governance_rollback"] is True

    async def test_tool_executor_ungoverned_failure_stays_failed(self):
        executor = self.build_executor()
        result = await executor.execute(
            RuntimeContext(request_id="r1"),
            approved_task(task_id="t1", action_type="tool", metadata={"tool": "fail"}, inputs={"x": 1}),
            self.routing("fail"),
        )
        assert result.status == TaskStatus.FAILED
        assert "governance_rollback" not in result.metadata

    async def test_provider_executor_does_not_request_second_approval(self):
        calls = 0

        class DenyingProviderManager:
            async def execute_provider(self, **kwargs):
                nonlocal calls
                calls += 1
                raise AssertionError("must not run")

        engine = GovernanceEngine()
        engine.set_default_policy(load_policy({
            "policy_id": "prov", "version": "1.0.0", "name": "Prov",
            "providers": [{"target": "gate", "approval_required": True}],
        }))
        executor = ProviderExecutor(DenyingProviderManager(), governance=engine)
        routing = RoutingDecision(
            provider_id="gate", model_id="m", reasoning_summary="provider"
        )
        result = await executor.execute(
            RuntimeContext(request_id="r1"),
            approved_task(task_id="t1", action_type="text_generation"),
            routing,
        )
        assert result.status == TaskStatus.FAILED
        assert result.metadata.get("governance_blocked") is not True
        assert calls == 1
        assert len(engine.records) == 1
        assert engine.records.last().status == DecisionStatus.FAILED
        assert engine.records.last().permit_id is not None
        assert engine.records.last().decision == "allow"

    async def test_provider_executor_allowed_without_rule(self):
        class OkProviderManager:
            async def execute_provider(self, **kwargs):
                return {"success": True, "text": "ok", "metadata": {}}

        engine = GovernanceEngine()
        executor = ProviderExecutor(OkProviderManager(), governance=engine)
        routing = RoutingDecision(
            provider_id="openai", model_id="m", reasoning_summary="provider"
        )
        result = await executor.execute(
            RuntimeContext(request_id="r1"),
            approved_task(task_id="t1", action_type="text_generation"),
            routing,
        )
        assert result.status == TaskStatus.COMPLETED
        assert len(engine.records) == 1
        assert engine.records.last().status == DecisionStatus.EXECUTED


# ---------------------------------------------------------------------------
# Production wiring
# ---------------------------------------------------------------------------

class TestProductionWiring:

    def test_production_tool_executor_has_governance(self):
        from app.core.app import create_orchestrator
        orchestrator = create_orchestrator()
        executors = orchestrator._runtime._dispatcher._registry._executors
        assert isinstance(executors["tool"]._governance, GovernanceEngine)
        assert isinstance(executors["provider"]._governance, GovernanceEngine)
