"""Explicit memory writes and recall through the isolated production composition."""
import pytest
from app.core.gambit.goal_parser import GoalParser
from app.core.contracts.planning import GoalIntent
from app.core.contracts.memory import MemoryAccessContext, MemoryWriteEvidence
from app.core.gambit.memory_syntax import recall_target
from tests.production.test_durable_memory_recall_grounding import _composition, _approved_execution

FACT = "my pilot validation codeword is COBALT-619"
STORE_FORMS = ["remember that {}", "remember this: {}", "remember this for later: {}",
    "please remember that {}", "save this in memory: {}", "store this in memory: {}",
    "store this for later: {}", "keep this in memory: {}", "keep this for later: {}",
    "don't forget that {}", "make a note in your memory that {}"]

@pytest.mark.parametrize("form", STORE_FORMS)
def test_store_grammar(form):
    goal = GoalParser().parse(form.format(FACT))
    assert goal.intent == GoalIntent.MEMORY_STORE
    assert goal.intent_arguments["content"] == FACT
    assert goal.memory_intent is None
    assert not goal.missing_arguments

@pytest.mark.parametrize("prompt", ["do you remember my codeword?", "what do you remember about my codeword?",
    "what was the codeword I asked you to remember?", "what was my pilot validation codeword?",
    "search your memory for pilot validation codeword", "recall my pilot validation codeword",
    "what did I tell you my favorite editor was?"])
def test_targeted_grammar(prompt):
    goal = GoalParser().parse(prompt)
    assert goal.intent == GoalIntent.SEARCH_MEMORY
    assert goal.memory_intent.value == "targeted_recall"
    assert recall_target(prompt)

@pytest.mark.parametrize("prompt", ["search your memory", "show recent memories", "show what you remember", "list recent memories"])
def test_browse_grammar(prompt):
    assert GoalParser().parse(prompt).memory_intent.value == "memory_browse"
    assert recall_target(prompt) == ""

@pytest.fixture
def composition(tmp_path, monkeypatch, isolated_samaktha_security_state):
    monkeypatch.setattr("app.config.store.get_application_paths", lambda: isolated_samaktha_security_state.paths)
    monkeypatch.setattr("app.integrations.credentials.CredentialResolver.get_smtp_credentials", lambda: {})
    return _composition(tmp_path, monkeypatch)

async def test_exact_store_uses_real_tool_and_durable_evidence(composition, monkeypatch):
    orchestrator, provider = composition
    def forbidden(*args, **kwargs):
        raise AssertionError("Store must not browse memory")
    monkeypatch.setattr(orchestrator._memory_controller, "retrieve", forbidden)
    result = await _approved_execution(orchestrator, "remember that " + FACT, principal="user-a", session="store-one")
    assert "Stored." in str(result), result
    assert not provider.payloads
    records = orchestrator.memory_manager.get_recent_context(n=100, allow_private=True)
    stored = [r for r in records if r.metadata.get("source_authority") == "user_supplied"]
    assert len(stored) == 1 and stored[0].content == FACT
    assert stored[0].owner_id == "user-a" and stored[0].metadata["provenance"] == "user_message"
    assert orchestrator.memory_manager.read_persisted_memory(stored[0].id).content == FACT
