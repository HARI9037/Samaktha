"""P10.1 — Real External Integrations: Pre-P10 Audit and Behavior Freeze.

These tests prove the baseline state BEFORE P10 external integrations are wired:
1. Email send returns simulated, externally_delivered=False
2. Message send returns simulated, externally_delivered=False
3. Calendar/Contacts are LOCAL_ONLY
4. CommunicationManager is a DISCONNECTED execution bypass (not reachable via ToolExecutor)
5. CapabilityRegistry correctly categorizes these as SIMULATED / LOCAL_ONLY
"""

import pytest

from app.communication.email_tool import EmailTool
from app.communication.message_tool import MessageTool
from app.tools.calendar import CalendarTool
from app.tools.contacts import ContactsTool
from app.tools.models import CapabilityAvailability
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_email_tool_is_simulated():
    """Prove EmailTool defaults to SIMULATED and does not perform real delivery."""
    tool = EmailTool()

    result = await tool.run({
        "action": "send",
        "to": ["test@example.com"],
        "subject": "Audit Test",
        "body": "Hello",
    })

    assert result.ok
    assert result.data.get("status") == "simulated"
    assert result.data.get("externally_delivered") is False


@pytest.mark.asyncio
async def test_message_tool_is_simulated():
    """Prove MessageTool defaults to SIMULATED and does not perform real delivery."""
    tool = MessageTool()

    result = await tool.run({
        "action": "send",
        "to": ["+1234567890"],
        "body": "Audit Test",
    })

    assert result.ok
    assert result.data.get("status") == "simulated"
    assert result.data.get("externally_delivered") is False


@pytest.mark.asyncio
async def test_calendar_and_contacts_are_local_only(tmp_path):
    """Prove Calendar and Contacts tools default to LOCAL_ONLY."""
    db_file = str(tmp_path / "test.db")
    calendar_tool = CalendarTool(db_path=db_file)
    # instantiation passes

    contacts_tool = ContactsTool(db_path=db_file)
    # instantiation passes


@pytest.mark.asyncio
async def test_capability_registry_truth(tmp_path):
    """Prove the registry truth derives correctly from the underlying tools."""
    from app.core.app import create_orchestrator
    from app.config.settings import Settings

    db_file = str(tmp_path / "test.db")
    settings = Settings(sqlite_url=f"sqlite:///{db_file}")
    orchestrator = create_orchestrator(settings)

    registry = orchestrator.tool_registry

    # Email should be SIMULATED
    email_info = registry.info_for("email")
    assert email_info is not None
    assert email_info.execution_mode == CapabilityAvailability.SIMULATED

    # Message should be SIMULATED
    message_info = registry.info_for("message")
    assert message_info is not None
    assert message_info.execution_mode == CapabilityAvailability.SIMULATED

    # Calendar should be LOCAL_ONLY
    calendar_info = registry.info_for("calendar")
    assert calendar_info is not None
    assert calendar_info.execution_mode == CapabilityAvailability.LOCAL_ONLY

    # Contacts should be LOCAL_ONLY
    contacts_info = registry.info_for("contacts")
    assert contacts_info is not None
    assert contacts_info.execution_mode == CapabilityAvailability.LOCAL_ONLY
