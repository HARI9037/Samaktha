"""External adapter interfaces for third-party providers.

Interface-only: declares capabilities and operations; concrete
integrations must be supplied by the application. See base.py.
"""

from app.tools.adapters.base import AdaptersCatalog, ExternalAdapter, ExternalTool
from app.tools.adapters.providers import provider_catalog

__all__ = ["AdaptersCatalog", "ExternalAdapter", "ExternalTool", "provider_catalog"]

_default_catalog = AdaptersCatalog(provider_catalog())


def default_catalog() -> AdaptersCatalog:
    return _default_catalog
