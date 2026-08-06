"""Interface-only adapters for external providers.

These declare the capabilities, categories, policies and operations of
each integration. None of them connect or perform network I/O; they
exist so the ecosystem can discover, govern and select external
capabilities uniformly. Concrete integrations subclass these and
implement ``run_operation``.
"""

from __future__ import annotations

from typing import Any

from app.tools.adapters.base import ExternalAdapter
from app.tools.framework.capabilities import ToolCapability, ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy

_PROVIDERS: dict[str, type[ExternalAdapter]] = {}


def _register(cls: type[ExternalAdapter]) -> type[ExternalAdapter]:
    _PROVIDERS[cls.provider_id] = cls
    return cls


class _BaseAdapter(ExternalAdapter):
    async def connect(self) -> bool:
        # Interface-only: never connects, never stores credentials.
        return False

    async def run_operation(self, operation: str, parameters: dict[str, Any]) -> Any:  # pragma: no cover
        raise NotImplementedError(
            f"Adapter '{self.provider_id}' is interface-only; "
            "a concrete integration must implement run_operation"
        )


@_register
class GoogleWorkspaceAdapter(_BaseAdapter):
    provider_id = "google_workspace"
    provider_name = "Google Workspace"
    category = ToolCategory.PRODUCTIVITY
    capabilities = (ToolCapability.CALENDAR_MANAGE, ToolCapability.COMMUNICATION_SEND, "calendar", "email", "drive")
    operations = {"send_email": "send an email via Gmail", "list_events": "list calendar events"}


@_register
class Microsoft365Adapter(_BaseAdapter):
    provider_id = "microsoft_365"
    provider_name = "Microsoft 365"
    category = ToolCategory.PRODUCTIVITY
    capabilities = (ToolCapability.CALENDAR_MANAGE, ToolCapability.COMMUNICATION_SEND, "calendar", "email", "onedrive")
    operations = {"send_email": "send an email via Outlook", "list_events": "list calendar events"}


@_register
class GitHubAdapter(_BaseAdapter):
    provider_id = "github"
    provider_name = "GitHub"
    category = ToolCategory.DEVELOPER
    capabilities = (ToolCapability.GIT_STATUS, ToolCapability.GIT_COMMIT, ToolCapability.GIT_PUSH, "repository", "code")
    policy = ToolPolicy(
        permissions=(ToolPermission.READ, ToolPermission.WRITE, ToolPermission.NETWORK),
        approval_required=True,
        max_parallel_instances=2,
        description="Interface-only GitHub integration.",
    )
    operations = {"create_issue": "create an issue", "list_pull_requests": "list open pull requests"}


@_register
class GitLabAdapter(_BaseAdapter):
    provider_id = "gitlab"
    provider_name = "GitLab"
    category = ToolCategory.DEVELOPER
    capabilities = (ToolCapability.GIT_STATUS, ToolCapability.GIT_COMMIT, ToolCapability.GIT_PUSH, "repository")
    operations = {"create_issue": "create an issue", "list_merge_requests": "list open merge requests"}


@_register
class SlackAdapter(_BaseAdapter):
    provider_id = "slack"
    provider_name = "Slack"
    category = ToolCategory.COMMUNICATION
    capabilities = (ToolCapability.COMMUNICATION_SEND, ToolCapability.COMMUNICATION_READ, "message")
    operations = {"send_message": "send a message to a channel"}


@_register
class DiscordAdapter(_BaseAdapter):
    provider_id = "discord"
    provider_name = "Discord"
    category = ToolCategory.COMMUNICATION
    capabilities = (ToolCapability.COMMUNICATION_SEND, "message")
    operations = {"send_message": "send a message to a channel"}


@_register
class WhatsAppAdapter(_BaseAdapter):
    provider_id = "whatsapp"
    provider_name = "WhatsApp"
    category = ToolCategory.COMMUNICATION
    capabilities = (ToolCapability.COMMUNICATION_SEND, "message")
    operations = {"send_message": "send a message to a contact"}


@_register
class TelegramAdapter(_BaseAdapter):
    provider_id = "telegram"
    provider_name = "Telegram"
    category = ToolCategory.COMMUNICATION
    capabilities = (ToolCapability.COMMUNICATION_SEND, "message")
    operations = {"send_message": "send a message to a chat"}


@_register
class NotionAdapter(_BaseAdapter):
    provider_id = "notion"
    provider_name = "Notion"
    category = ToolCategory.PRODUCTIVITY
    capabilities = (ToolCapability.NOTE_MANAGE, "notes", "pages")
    operations = {"create_page": "create a page", "list_pages": "list pages"}


@_register
class ObsidianAdapter(_BaseAdapter):
    provider_id = "obsidian"
    provider_name = "Obsidian"
    category = ToolCategory.PRODUCTIVITY
    capabilities = (ToolCapability.NOTE_MANAGE, "notes")
    operations = {"create_note": "create a note", "search_notes": "search notes"}


@_register
class JiraAdapter(_BaseAdapter):
    provider_id = "jira"
    provider_name = "Jira"
    category = ToolCategory.DEVELOPER
    capabilities = (ToolCapability.PROJECT_MANAGE, "issue", "ticket")
    operations = {"create_issue": "create an issue", "list_issues": "list issues"}


@_register
class LinearAdapter(_BaseAdapter):
    provider_id = "linear"
    provider_name = "Linear"
    category = ToolCategory.DEVELOPER
    capabilities = (ToolCapability.PROJECT_MANAGE, "issue", "ticket")
    operations = {"create_issue": "create an issue", "list_issues": "list issues"}


@_register
class TrelloAdapter(_BaseAdapter):
    provider_id = "trello"
    provider_name = "Trello"
    category = ToolCategory.PRODUCTIVITY
    capabilities = (ToolCapability.PROJECT_MANAGE, "card", "board")
    operations = {"create_card": "create a card", "list_boards": "list boards"}


@_register
class GoogleDriveAdapter(_BaseAdapter):
    provider_id = "google_drive"
    provider_name = "Google Drive"
    category = ToolCategory.CLOUD
    capabilities = (ToolCapability.CLOUD_STORAGE, "storage", "file")
    operations = {"list_files": "list files", "upload_file": "upload a file"}


@_register
class OneDriveAdapter(_BaseAdapter):
    provider_id = "onedrive"
    provider_name = "OneDrive"
    category = ToolCategory.CLOUD
    capabilities = (ToolCapability.CLOUD_STORAGE, "storage", "file")
    operations = {"list_files": "list files", "upload_file": "upload a file"}


@_register
class DropboxAdapter(_BaseAdapter):
    provider_id = "dropbox"
    provider_name = "Dropbox"
    category = ToolCategory.CLOUD
    capabilities = (ToolCapability.CLOUD_STORAGE, "storage", "file")
    operations = {"list_files": "list files", "upload_file": "upload a file"}


@_register
class SQLiteAdapter(_BaseAdapter):
    provider_id = "sqlite"
    provider_name = "SQLite (local)"
    category = ToolCategory.DATABASE
    capabilities = (ToolCapability.DATABASE_QUERY, ToolCapability.DATABASE_WRITE, "query")
    operations = {"query": "run a read-only SQL query", "execute": "run a write SQL statement"}


@_register
class PostgreSQLAdapter(_BaseAdapter):
    provider_id = "postgresql"
    provider_name = "PostgreSQL"
    category = ToolCategory.DATABASE
    capabilities = (ToolCapability.DATABASE_QUERY, ToolCapability.DATABASE_WRITE, "query")
    operations = {"query": "run a read-only SQL query", "execute": "run a write SQL statement"}


@_register
class MongoDBAdapter(_BaseAdapter):
    provider_id = "mongodb"
    provider_name = "MongoDB"
    category = ToolCategory.DATABASE
    capabilities = (ToolCapability.DATABASE_QUERY, ToolCapability.DATABASE_WRITE, "query")
    operations = {"find": "query documents", "insert": "insert documents"}


def provider_catalog() -> dict[str, type[ExternalAdapter]]:
    return dict(_PROVIDERS)
