"""P10.4 — Calendar & Contacts Integration Tests."""

import pytest

from app.tools.calendar import CalendarTool
from app.tools.contacts import ContactsTool
from app.integrations.contracts import IntegrationProvider, IntegrationRequest, IntegrationResult, IntegrationStatus


class MockCalendarProvider(IntegrationProvider):
    async def connect(self) -> bool: return True
    async def disconnect(self) -> None: pass
    async def health(self) -> bool: return True
    async def validate(self, request: IntegrationRequest) -> list[str]: return []
    async def execute(self, request: IntegrationRequest) -> IntegrationResult:
        return IntegrationResult(
            status=IntegrationStatus.DELIVERED,
            provider_id="calendar",
            external_id="ext-cal-123",
            delivery_status="synced",
        )


class MockContactsProvider(IntegrationProvider):
    async def connect(self) -> bool: return True
    async def disconnect(self) -> None: pass
    async def health(self) -> bool: return True
    async def validate(self, request: IntegrationRequest) -> list[str]: return []
    async def execute(self, request: IntegrationRequest) -> IntegrationResult:
        return IntegrationResult(
            status=IntegrationStatus.DELIVERED,
            provider_id="contacts",
            external_id="ext-con-123",
            delivery_status="synced",
        )


@pytest.mark.asyncio
async def test_calendar_local_only(tmp_path):
    tool = CalendarTool(db_path=str(tmp_path / "calendar.db"))
    res = await tool.run({
        "action": "create",
        "title": "Meeting",
        "attendees": ["test@example.com"]
    })

    assert res.ok is True
    assert res.data["sync_status"] == "simulated_invite"


@pytest.mark.asyncio
async def test_calendar_with_provider(tmp_path):
    tool = CalendarTool(db_path=str(tmp_path / "calendar2.db"), integration_provider=MockCalendarProvider())
    res = await tool.run({
        "action": "create",
        "title": "Meeting",
        "attendees": ["test@example.com"]
    })

    assert res.ok is True
    assert res.data["sync_status"] == "invited"


@pytest.mark.asyncio
async def test_contacts_local_only(tmp_path):
    tool = ContactsTool(db_path=str(tmp_path / "contacts.db"))
    res = await tool.run({
        "action": "create",
        "name": "Alice"
    })

    assert res.ok is True
    assert res.data["sync_status"] == "simulated_sync"


@pytest.mark.asyncio
async def test_contacts_with_provider(tmp_path):
    tool = ContactsTool(db_path=str(tmp_path / "contacts2.db"), integration_provider=MockContactsProvider())
    res = await tool.run({
        "action": "create",
        "name": "Bob"
    })

    assert res.ok is True
    assert res.data["sync_status"] == "synced"
