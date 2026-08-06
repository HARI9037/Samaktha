import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid

from app.memory.models import MemoryEntry
from app.memory.repository import MemoryRepository

class ResourceRegistry:
    """Registry for files and folders explicitly approved or requested by the user."""
    
    CATEGORY = "RESOURCE"
    
    def __init__(self, repository: Optional[MemoryRepository] = None):
        self._repo = repository or MemoryRepository()
        
    def _generate_key(self, path: Path) -> str:
        # Use lowercase string representation to handle case insensitivity on Windows
        return f"resource_{str(path).lower()}"
        
    def register(self, path: Path | str) -> None:
        """Register an absolute path as a known resource."""
        p = Path(path).resolve()
        key = self._generate_key(p)
        
        # Check if it already exists to preserve aliases/created_at
        existing = self._repo.get(key)
        
        now = datetime.now(timezone.utc)
        
        if existing:
            try:
                data = json.loads(existing.value)
            except json.JSONDecodeError:
                data = {}
            data["last_accessed"] = now.isoformat()
            existing.value = json.dumps(data)
            existing.updated_at = now
            self._repo.save(existing)
            return

        # Create new entry
        data = {
            "name": p.name,
            "absolute_path": str(p),
            "resource_type": "folder" if p.is_dir() else "file",
            "parent_folder": str(p.parent),
            "aliases": [p.name],
            "last_accessed": now.isoformat()
        }
        
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            key=key,
            value=json.dumps(data),
            category=self.CATEGORY,
            created_at=now,
            updated_at=now
        )
        self._repo.save(entry)
        
    def lookup(self, name_or_alias: str) -> Optional[Path]:
        """Look up a registered resource by exact name or alias."""
        # Find all resources
        entries = self._repo.search(category=self.CATEGORY)
        
        # Exact match preferred
        target = name_or_alias.lower()
        
        for entry in entries:
            try:
                data = json.loads(entry.value)
            except json.JSONDecodeError:
                continue
                
            aliases = [a.lower() for a in data.get("aliases", [])]
            name = data.get("name", "").lower()
            
            if target == name or target in aliases:
                abs_path = data.get("absolute_path")
                if abs_path:
                    # Update last accessed
                    now = datetime.now(timezone.utc)
                    data["last_accessed"] = now.isoformat()
                    entry.value = json.dumps(data)
                    entry.updated_at = now
                    self._repo.save(entry)
                    return Path(abs_path)
                    
        return None
        
    def remove(self, path: Path | str) -> None:
        """Remove a resource from the registry."""
        p = Path(path).resolve()
        key = self._generate_key(p)
        self._repo.delete(key)
