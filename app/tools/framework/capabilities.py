"""Tool categories and canonical capability vocabulary.

Categories are broad buckets used for discovery and filtering; every
category is independently extensible. Capabilities describe what a tool
can do and are the language GAMBIT uses to select tools.
"""

from __future__ import annotations

from enum import StrEnum


class ToolCategory(StrEnum):
    SYSTEM = "system"
    FILESYSTEM = "filesystem"
    INTERNET = "internet"
    COMMUNICATION = "communication"
    PRODUCTIVITY = "productivity"
    DEVELOPER = "developer"
    DATABASE = "database"
    MEDIA = "media"
    AI = "ai"
    CLOUD = "cloud"
    CUSTOM = "custom"

    @classmethod
    def known(cls) -> tuple[str, ...]:
        return tuple(category.value for category in cls)


class ToolCapability(StrEnum):
    """Canonical capability vocabulary used to request and select tools."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_LIST = "file_list"
    FILE_SEARCH = "file_search"
    FILE_MOVE = "file_move"
    FILE_COPY = "file_copy"
    FILE_DELETE = "file_delete"
    FILE_MKDIR = "file_mkdir"

    PDF_READ = "pdf_read"
    IMAGE_READ = "image_read"
    DOCUMENT_READ = "document_read"

    MEMORY_SEARCH = "memory_search"
    MEMORY_WRITE = "memory_write"
    MEMORY_DELETE = "memory_delete"

    INTERNET_SEARCH = "internet_search"
    INTERNET_NEWS = "internet_news"
    INTERNET_FETCH = "internet_fetch"
    INTERNET_SUGGEST = "internet_suggest"

    SHELL_EXEC = "shell_exec"
    PROCESS_LIST = "process_list"
    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"
    NOTIFY = "notify"

    DATABASE_QUERY = "database_query"
    DATABASE_WRITE = "database_write"

    CLOUD_STORAGE = "cloud_storage"
    CLOUD_SYNC = "cloud_sync"

    COMMUNICATION_SEND = "communication_send"
    COMMUNICATION_READ = "communication_read"
    CALENDAR_MANAGE = "calendar_manage"

    GIT_PUSH = "git_push"
    GIT_COMMIT = "git_commit"
    GIT_STATUS = "git_status"
    PROJECT_MANAGE = "project_manage"
    NOTE_MANAGE = "note_manage"

    AI_EMBED = "ai_embed"
    CUSTOM = "custom"
