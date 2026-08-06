import os
from pathlib import Path
from typing import Optional

from app.memory.resources import ResourceRegistry

class MultipleMatches:
    def __init__(self, candidates: list[str]):
        self.candidates = candidates

class FileResolver:
    """Resolves file paths, preserving absolute paths and discovering relative paths."""
    
    def __init__(self, root_dir: str | Path | None = None):
        if root_dir:
            self._root_dir = Path(root_dir).resolve()
        else:
            self._root_dir = Path.cwd().resolve()
        self._registry = ResourceRegistry()
            
    def resolve(self, path_str: str) -> Path | MultipleMatches | None:
        """
        Returns a single resolved Path if exactly one matches, or MultipleMatches if ambiguous.
        If the path is absolute, it returns it directly.
        Returns None if a registry entry is found but no longer exists on disk.
        """
        path_str = path_str.strip().strip('"').strip("'")
        if not path_str or path_str == ".":
            return self._root_dir.resolve()
        p = Path(os.path.expanduser(path_str))
        
        if p.is_absolute():
            return p.resolve()
            
        # Registry lookup
        registered_path = self._registry.lookup(path_str)
        if registered_path is not None:
            if registered_path.exists():
                return registered_path
            else:
                # The file was registered but no longer exists on disk.
                # Remove the stale entry and continue resolving, because the
                # user might be trying to recreate it, or there might be another
                # file with the same name in the search directories.
                self._registry.remove(registered_path)
            
        # Search locations for relative paths
        search_dirs = [
            self._root_dir,
            Path(os.path.expanduser("~/Desktop")).resolve(),
            Path(os.path.expanduser("~")).resolve(),
        ]
        
        candidates = []
        for d in search_dirs:
            if not d.exists() or not d.is_dir():
                continue
                
            candidate = (d / p).resolve()
            if candidate.exists() and str(candidate) not in candidates:
                candidates.append(str(candidate))
                
        if len(candidates) == 1:
            return Path(candidates[0])
        elif len(candidates) > 1:
            return MultipleMatches(candidates=candidates)
            
        # Fallback to standard resolution against root_dir if no existing file is found
        return (self._root_dir / p).resolve()
