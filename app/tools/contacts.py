"""ContactsTool for Phase 14.8.

Local contact management with CRUD, search, tags,
emails, phones, addresses, vCard import/export, and voice support.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.tools.base import Tool
from app.tools.base import ToolResult
from app.tools.framework.models import ToolPermission
from app.tools.framework.capabilities import ToolCategory
from app.tools.storage import delete_row, open_table, rebuild, save

log = logging.getLogger(__name__)


class Contact:
    """A single contact entity."""

    def __init__(
        self,
        contact_id: str,
        name: str,
        emails: list[str] | None = None,
        phones: list[str] | None = None,
        addresses: list[str] | None = None,
        tags: list[str] | None = None,
        notes: str = "",
        created_at: datetime | None = None,
    ) -> None:
        self.id = contact_id
        self.name = name
        self.emails = emails or []
        self.phones = phones or []
        self.addresses = addresses or []
        self.tags = tags or []
        self.notes = notes
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "emails": self.emails,
            "phones": self.phones,
            "addresses": self.addresses,
            "tags": self.tags,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Contact":
        return cls(
            contact_id=data["id"],
            name=data["name"],
            emails=data.get("emails", []),
            phones=data.get("phones", []),
            addresses=data.get("addresses", []),
            tags=data.get("tags", []),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )


class ContactsStore:
    """Durable contacts store: in-memory cache backed by SQLite (P1.1)."""

    def __init__(self, db_path: str | None = None) -> None:
        self._contacts: dict[str, Contact] = {}
        self._db = open_table("contacts", db_path)
        self._rebuild()

    def _rebuild(self) -> None:
        rebuild(self._contacts, self._db, Contact.from_dict)

    def create(self, contact: Contact) -> Contact:
        self._contacts[contact.id] = contact
        save(self._db, contact)
        return contact

    def get(self, contact_id: str) -> Contact | None:
        return self._contacts.get(contact_id)

    def update(self, contact_id: str, **kwargs: Any) -> Contact | None:
        contact = self._contacts.get(contact_id)
        if not contact:
            return None
        for key, value in kwargs.items():
            if hasattr(contact, key):
                setattr(contact, key, value)
        save(self._db, contact)
        return contact

    def delete(self, contact_id: str) -> bool:
        if contact_id in self._contacts:
            del self._contacts[contact_id]
            delete_row(self._db, contact_id)
            return True
        return False

    def save(self, contact: Contact) -> None:
        """Persist a directly-mutated contact."""
        self._contacts[contact.id] = contact
        save(self._db, contact)

    def list_all(self) -> list[Contact]:
        return list(self._contacts.values())

    def search(self, query: str) -> list[Contact]:
        query_lower = query.lower()
        return [
            c for c in self._contacts.values()
            if query_lower in c.name.lower()
            or any(query_lower in e.lower() for e in c.emails)
            or any(query_lower in p.lower() for p in c.phones)
            or any(query_lower in t.lower() for t in c.tags)
        ]

    def lookup_by_email(self, email: str) -> Contact | None:
        email_lower = email.lower()
        for c in self._contacts.values():
            if email_lower in [e.lower() for e in c.emails]:
                return c
        return None

    def lookup_by_phone(self, phone: str) -> Contact | None:
        phone_clean = phone.replace("-", "").replace(" ", "")
        for c in self._contacts.values():
            if phone_clean in [p.replace("-", "").replace(" ", "") for p in c.phones]:
                return c
        return None


from app.integrations.contracts import IntegrationProvider, IntegrationRequest, IntegrationStatus

class ContactsTool(Tool):
    @property
    def name(self) -> str:
        return "contacts"
    """Tool for managing contacts with CRUD, search, and vCard support."""

    def __init__(self, db_path: str | None = None, integration_provider: IntegrationProvider | None = None) -> None:
        self._store = ContactsStore(db_path=db_path)
        self._provider = integration_provider
        self._capabilities = ["contact_create", "contact_read", "contact_update", "contact_delete", "contact_search", "contact_list", "contact_lookup", "contact_import", "contact_export"]

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def category(self):
        return ToolCategory.PERSONAL

    @property
    def permissions(self):
        return [ToolPermission.READ, ToolPermission.WRITE]

    @property
    def approval_required(self):
        return False

    @property
    def supported_actions(self):
        return ["create", "read", "update", "delete", "search", "list", "lookup", "import", "export"]

    @property
    def policy(self):
        from app.tools.framework.models import ToolPolicy
        return ToolPolicy(
            allowed=True,
            approval_required=False,
            required_permissions=[],
            max_timeout_s=30,
            max_retries=2,
        )

    @property
    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "read", "update", "delete", "search", "list", "lookup", "import", "export"]},
                "contact_id": {"type": "string"},
                "name": {"type": "string"},
                "emails": {"type": "array", "items": {"type": "string"}},
                "phones": {"type": "array", "items": {"type": "string"}},
                "addresses": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
                "query": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "vcard_data": {"type": "string"},
            },
            "required": ["action"],
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "list")

        if action == "create":
            return await self._create_contact(arguments)
        elif action == "read":
            return await self._read_contact(arguments)
        elif action == "update":
            return await self._update_contact(arguments)
        elif action == "delete":
            return await self._delete_contact(arguments)
        elif action == "search":
            return await self._search_contacts(arguments)
        elif action == "list":
            return await self._list_contacts(arguments)
        elif action == "lookup":
            return await self._lookup_contact(arguments)
        elif action == "import":
            return await self._import_vcard(arguments)
        elif action == "export":
            return await self._export_vcard(arguments)
        else:
            return ToolResult(ok=False, data={"error": f"Unknown action: {action}"})

    async def _create_contact(self, arguments: dict) -> ToolResult:
        contact_id = str(uuid.uuid4())[:8]
        name = arguments.get("name", "Unknown")
        contact = Contact(
            contact_id=contact_id,
            name=name,
            emails=arguments.get("emails", []),
            phones=arguments.get("phones", []),
            addresses=arguments.get("addresses", []),
            tags=arguments.get("tags", []),
            notes=arguments.get("notes", ""),
        )
        self._store.create(contact)

        sync_status = "local_only"
        if self._provider:
            req = IntegrationRequest(
                provider_id="contacts",
                action="sync_contact",
                payload={"contact": contact.to_dict()}
            )
            res = await self._provider.execute(req)
            sync_status = "synced" if res.status == IntegrationStatus.DELIVERED else "sync_failed"
        else:
            sync_status = "simulated_sync"

        return ToolResult(ok=True, data={"contact": contact.to_dict(), "sync_status": sync_status, "message": f"Contact '{name}' created."})

    async def _read_contact(self, arguments: dict) -> ToolResult:
        contact_id = arguments.get("contact_id", "")
        contact = self._store.get(contact_id)
        if not contact:
            return ToolResult(ok=False, data={"error": f"Contact {contact_id} not found."})
        return ToolResult(ok=True, data={"contact": contact.to_dict()})

    async def _update_contact(self, arguments: dict) -> ToolResult:
        contact_id = arguments.get("contact_id", "")
        contact = self._store.get(contact_id)
        if not contact:
            return ToolResult(ok=False, data={"error": f"Contact {contact_id} not found."})

        update_fields = {k: v for k, v in arguments.items() if k not in ("action", "contact_id")}
        self._store.update(contact_id, **update_fields)
        updated = self._store.get(contact_id)

        sync_status = "local_only"
        if updated:
            if self._provider:
                req = IntegrationRequest(
                    provider_id="contacts",
                    action="sync_contact",
                    payload={"contact": updated.to_dict()}
                )
                res = await self._provider.execute(req)
                sync_status = "synced" if res.status == IntegrationStatus.DELIVERED else "sync_failed"
            else:
                sync_status = "simulated_sync"

        return ToolResult(ok=True, data={"contact": updated.to_dict() if updated else {}, "sync_status": sync_status, "message": f"Contact {contact_id} updated."})

    async def _delete_contact(self, arguments: dict) -> ToolResult:
        contact_id = arguments.get("contact_id", "")
        deleted = self._store.delete(contact_id)
        if deleted:
            sync_status = "local_only"
            if self._provider:
                req = IntegrationRequest(
                    provider_id="contacts",
                    action="delete_contact",
                    payload={"contact_id": contact_id}
                )
                res = await self._provider.execute(req)
                sync_status = "deleted" if res.status == IntegrationStatus.DELIVERED else "delete_failed"
            else:
                sync_status = "simulated_delete"
            return ToolResult(ok=True, data={"message": f"Contact {contact_id} deleted.", "sync_status": sync_status})
        return ToolResult(ok=False, data={"error": f"Contact {contact_id} not found."})

    async def _search_contacts(self, arguments: dict) -> ToolResult:
        query = arguments.get("query", "")
        results = self._store.search(query)
        return ToolResult(ok=True, data={"contacts": [c.to_dict() for c in results], "count": len(results)})

    async def _list_contacts(self, arguments: dict) -> ToolResult:
        contacts = self._store.list_all()
        return ToolResult(ok=True, data={"contacts": [c.to_dict() for c in contacts], "count": len(contacts)})

    async def _lookup_contact(self, arguments: dict) -> ToolResult:
        email = arguments.get("email")
        phone = arguments.get("phone")
        if email:
            contact = self._store.lookup_by_email(email)
        elif phone:
            contact = self._store.lookup_by_phone(phone)
        else:
            return ToolResult(ok=False, data={"error": "Provide email or phone for lookup."})

        if contact:
            return ToolResult(ok=True, data={"contact": contact.to_dict()})
        return ToolResult(ok=False, data={"error": "Contact not found."})

    async def _import_vcard(self, arguments: dict) -> ToolResult:
        vcard_data = arguments.get("vcard_data", "")
        if not vcard_data:
            return ToolResult(ok=False, data={"error": "vcard_data is required"})

        name = ""
        emails = []
        phones = []
        for line in vcard_data.split("\n"):
            line = line.strip()
            if line.startswith("FN:"):
                name = line[3:].strip()
            elif line.startswith("EMAIL:"):
                emails.append(line[6:].strip())
            elif line.startswith("TEL:"):
                phones.append(line[4:].strip())

        contact = Contact(
            contact_id=str(uuid.uuid4())[:8],
            name=name or "Imported Contact",
            emails=emails,
            phones=phones,
        )
        self._store.create(contact)
        return ToolResult(ok=True, data={"contact": contact.to_dict(), "message": f"vCard imported: {name or 'Unknown'}"})

    async def _export_vcard(self, arguments: dict) -> ToolResult:
        contact_id = arguments.get("contact_id", "")
        contact = self._store.get(contact_id)
        if not contact:
            return ToolResult(ok=False, data={"error": f"Contact {contact_id} not found."})

        vcard_lines = [
            "BEGIN:VCARD",
            "VERSION:3.0",
            f"FN:{contact.name}",
        ]
        for email in contact.emails:
            vcard_lines.append(f"EMAIL:{email}")
        for phone in contact.phones:
            vcard_lines.append(f"TEL:{phone}")
        for addr in contact.addresses:
            vcard_lines.append(f"ADR:{addr}")
        vcard_lines.append("END:VCARD")

        return ToolResult(ok=True, data={"vcard": "\n".join(vcard_lines), "message": f"vCard exported for {contact.name}"})

    async def voice_speak(self, text: str) -> str:
        return f"Contact: {text}"
