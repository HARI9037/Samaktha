"""First-run decision boundary for installed Samaktha."""

from __future__ import annotations

from app.config.store import SettingsStore
from app.paths import ApplicationPaths, get_application_paths


class FirstRunCoordinator:
    def __init__(self, *, paths: ApplicationPaths | None = None, settings_store: SettingsStore | None = None) -> None:
        self.paths = paths or get_application_paths()
        self.settings_store = settings_store or SettingsStore(paths=self.paths)

    def setup_required(self) -> bool:
        """Only packaged installs force setup; source development remains compatible."""
        return bool(self.paths.is_installed and not self.settings_store.is_setup_complete())

    def launch_setup(self) -> bool:
        from app.setup.wizard import launch_setup_wizard
        from app.setup.service import SetupService

        return launch_setup_wizard(
            SetupService(paths=self.paths, settings_store=self.settings_store)
        )
