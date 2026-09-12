"""Thin standard-Tkinter first-run wizard."""

from __future__ import annotations

from typing import Any

from app import __version__
from app.setup.controller import SetupController
from app.setup.service import SetupError, SetupService


PAGE_IDS = (
    "welcome", "system", "workspace", "provider", "search", "local",
    "shell", "experimental", "validation", "finish",
)


class SetupWizard:
    """Presentation only; persistence and validation remain in SetupService."""

    def __init__(self, controller: SetupController, root: Any = None) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.controller = controller
        self.root = root or tk.Tk()
        self.root.title("Samaktha Setup")
        self.root.geometry("720x560")
        self.completed = False
        self.page_index = 0
        self.values = controller.initial_values()
        self.variables: dict[str, Any] = {}
        self.container = ttk.Frame(self.root, padding=20)
        self.container.pack(fill="both", expand=True)
        self.content = ttk.Frame(self.container)
        self.content.pack(fill="both", expand=True)
        controls = ttk.Frame(self.container)
        controls.pack(fill="x", pady=(12, 0))
        self.back_button = ttk.Button(controls, text="Back", command=self.back)
        self.back_button.pack(side="left")
        self.next_button = ttk.Button(controls, text="Next", command=self.next)
        self.next_button.pack(side="right")
        self._render()

    @property
    def page_id(self) -> str:
        return PAGE_IDS[self.page_index]

    def run(self) -> bool:
        self.root.mainloop()
        return self.completed

    def back(self) -> None:
        self._capture()
        if self.page_index:
            self.page_index -= 1
        self._render()

    def next(self) -> None:
        from tkinter import messagebox

        self._capture()
        if self.page_id == "validation":
            try:
                outcome = self.controller.finish(self.values)
            except (SetupError, ValueError) as exc:
                messagebox.showerror("Setup could not finish", str(exc))
                return
            if not outcome.ready:
                messagebox.showerror("Setup incomplete", "Required configuration is not ready.")
                return
            self.completed = True
            self.page_index += 1
            self._render()
            return
        if self.page_id == "finish":
            self.root.destroy()
            return
        self.page_index += 1
        self._render()

    def _clear(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self.variables.clear()

    def _render(self) -> None:
        self._clear()
        renderer = getattr(self, f"_page_{self.page_id}")
        renderer()
        self.back_button.configure(state="normal" if self.page_index else "disabled")
        self.next_button.configure(text="Launch Samaktha" if self.page_id == "finish" else "Finish" if self.page_id == "validation" else "Next")

    def _title(self, text: str, detail: str = "") -> None:
        self.ttk.Label(self.content, text=text, font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 8))
        if detail:
            self.ttk.Label(self.content, text=detail, wraplength=650).pack(anchor="w", pady=(0, 14))

    def _entry(self, key: str, label: str, *, secret: bool = False) -> None:
        self.ttk.Label(self.content, text=label).pack(anchor="w")
        variable = self.tk.StringVar(value=str(self.values.get(key, "") or ""))
        self.variables[key] = variable
        self.ttk.Entry(self.content, textvariable=variable, show="•" if secret else "").pack(fill="x", pady=(0, 8))

    def _check(self, key: str, label: str) -> None:
        variable = self.tk.BooleanVar(value=bool(self.values.get(key, False)))
        self.variables[key] = variable
        self.ttk.Checkbutton(self.content, text=label, variable=variable).pack(anchor="w", pady=3)

    def _choice(self, key: str, label: str, options: list[tuple[str, str]]) -> None:
        self.ttk.Label(self.content, text=label).pack(anchor="w")
        variable = self.tk.StringVar(value=str(self.values.get(key, options[0][0])))
        self.variables[key] = variable
        for value, text in options:
            self.ttk.Radiobutton(self.content, text=text, value=value, variable=variable).pack(anchor="w")

    def _capture(self) -> None:
        from app.setup.field_state import capture_fields
        changes = {key: variable.get() for key, variable in self.variables.items()}
        if "smtp_port" in changes:
            try:
                changes["smtp_port"] = int(changes["smtp_port"])
            except (TypeError, ValueError):
                changes["smtp_port"] = 0
        self.values = capture_fields(self.values, changes)

    def _page_welcome(self):
        self._title("SAMAKTHA", f"Secure personal AI runtime\nVersion {__version__}")
        self.ttk.Label(self.content, text="This setup configures only capabilities that Samaktha can actually run.").pack(anchor="w")

    def _page_system(self):
        self._title("System Check", "Windows, storage, secure credential storage, runtime and network readiness.")
        for result in self.controller.service.system_validations():
            self.ttk.Label(self.content, text=f"{result.label}: {result.status.value.upper()} — {result.detail}", wraplength=650).pack(anchor="w")

    def _page_workspace(self):
        self._title("Workspace & Local Data")
        self._entry("workspace_path", "Default workspace")
        self._check("memory_enabled", "Enable persistent memory")
        self._check("session_history_enabled", "Keep conversation history")

    def _page_provider(self):
        self._title("AI Provider")
        self._choice("primary_provider", "Choose your AI provider", [("groq", "Groq"), ("openai", "OpenAI"), ("openrouter", "OpenRouter"), ("local", "Local Model"), ("later", "Configure Later")])
        self._entry("provider_api_key", "API key", secret=True)
        self._check("remove_provider_credential", "Remove saved API credential (switch to offline setup)")
        self._entry("provider_model", "Model")
        self._entry("provider_endpoint", "Local endpoint")
        self._check("import_environment_credential", "Import matching credential from existing development environment")
        self.ttk.Button(self.content, text="Test Connection", command=self._test_provider).pack(anchor="w", pady=(8, 0))

    def _page_search(self):
        self._title("Internet Search", "DuckDuckGo needs no API key, account, or Docker.")
        self._check("search_enabled", "Enable internet search")
        self._choice("search_provider", "Provider", [("ddgs", "DuckDuckGo"), ("searxng", "SearXNG (Advanced)"), ("brave", "Brave (Advanced)")])
        self._entry("searxng_url", "SearXNG endpoint")
        self._entry("brave_api_key", "Brave API key", secret=True)
        self._check("remove_brave_credential", "Remove saved Brave credential")
        self.ttk.Button(self.content, text="Test Search", command=self._test_search).pack(anchor="w", pady=(8, 0))

    def _page_local(self):
        self._title("Local Capabilities")
        self.ttk.Label(self.content, text="Filesystem, Persistent Memory, Clipboard, Notes, Tasks, Local Contacts and Local Calendar are available locally.", wraplength=650).pack(anchor="w")

    def _page_shell(self):
        self._title("Governed Command Execution", "Individual commands remain subject to Samaktha governance and P7 security.")
        self._check("shell_enabled", "Enable shell tools")

    def _page_experimental(self):
        self._title("Experimental Features", "These features are disabled by default and are not required.")
        self._check("smtp_enabled", "Enable Experimental SMTP Sending")
        self._choice("smtp_preset", "SMTP preset", [("gmail", "Gmail SMTP"), ("outlook", "Outlook SMTP"), ("custom", "Custom SMTP")])
        self._entry("smtp_sender", "Sender address")
        self._entry("smtp_host", "SMTP host")
        self._entry("smtp_port", "Port")
        self._entry("smtp_username", "Username")
        self._entry("smtp_password", "Password / app password", secret=True)
        self._check("remove_smtp_credential", "Remove saved SMTP credential")
        self._choice("smtp_security", "Security", [("starttls", "STARTTLS"), ("ssl", "SSL/TLS")])
        actions = self.ttk.Frame(self.content)
        actions.pack(fill="x", pady=(6, 4))
        self.ttk.Button(actions, text="Apply Preset", command=self._apply_smtp_preset).pack(side="left")
        self.ttk.Button(actions, text="Test Authentication", command=self._test_smtp).pack(side="left", padx=(8, 0))
        self._check("notifications_enabled", "Desktop Notifications (experimental)")
        self._check("ocr_enabled", "OCR / Documents (experimental)")
        self._check("voice_enabled", "Voice (experimental)")

    def _page_validation(self):
        self._title("Samaktha System Validation", "Finish commits one validated configuration transaction.")
        try:
            rows = self.controller.validate(self.values)
        except ValueError as exc:
            self.ttk.Label(self.content, text=str(exc)).pack(anchor="w")
            return
        for row in rows:
            self.ttk.Label(self.content, text=f"{row.label}: {row.status.value.upper()} — {row.detail}", wraplength=650).pack(anchor="w")

    def _page_finish(self):
        self._title("Samaktha is ready.")
        self.ttk.Label(self.content, text=f"Your Samaktha workspace: {self.values.get('workspace_path', '')}", wraplength=650).pack(anchor="w")
        self.ttk.Label(self.content, text="Available capabilities reflect the saved, validated setup. Shell and experimental features remain disabled unless you explicitly enabled them.", wraplength=650).pack(anchor="w")
        if self.values.get("smtp_enabled") and self.values.get("smtp_auth_verified"):
            self.ttk.Button(
                self.content, text="Send Test Email", command=self._send_smtp_test,
            ).pack(anchor="w", pady=(12, 0))

    def _test_provider(self) -> None:
        from tkinter import messagebox
        self._capture()
        try:
            result = self.controller.test_provider(self.values)
        except ValueError as exc:
            messagebox.showerror("Provider test", str(exc))
            return
        self.values["provider_verified"] = result.status.value == "pass"
        messagebox.showinfo("Provider test", result.detail)

    def _test_search(self) -> None:
        from tkinter import messagebox
        self._capture()
        try:
            result = self.controller.test_search(self.values)
        except ValueError as exc:
            messagebox.showerror("Search test", str(exc))
            return
        self.values["search_verified"] = result.status.value == "pass"
        messagebox.showinfo("Search test", result.detail)

    def _apply_smtp_preset(self) -> None:
        self._capture()
        preset = self.values.get("smtp_preset", "custom")
        if preset == "gmail":
            self.values.update(smtp_host="smtp.gmail.com", smtp_port=587, smtp_security="starttls")
        elif preset == "outlook":
            self.values.update(smtp_host="smtp.office365.com", smtp_port=587, smtp_security="starttls")
        self._render()

    def _test_smtp(self) -> None:
        from tkinter import messagebox
        self._capture()
        try:
            result = self.controller.test_smtp_authentication(self.values)
        except ValueError as exc:
            messagebox.showerror("SMTP authentication", str(exc))
            return
        self.values["smtp_auth_verified"] = result.status.value == "pass"
        messagebox.showinfo("SMTP authentication", result.detail)

    def _send_smtp_test(self) -> None:
        from tkinter import messagebox, simpledialog

        recipient = simpledialog.askstring(
            "SMTP test recipient", "Recipient address:", parent=self.root,
        )
        if not recipient:
            return
        confirmed = messagebox.askyesno(
            "Send a real external email?",
            "Samaktha is about to send one real external test email.\n\n"
            f"Recipient: {recipient}\n"
            f"Sender: {self.values.get('smtp_sender', '')}\n"
            "Subject: Samaktha setup test",
            parent=self.root,
        )
        result = self.controller.send_smtp_test_email(
            recipient, confirmed=confirmed,
        )
        if result.status.value == "pass":
            messagebox.showinfo("SMTP test", result.detail)
        elif result.status.value != "disabled":
            messagebox.showerror("SMTP test", result.detail)


def launch_setup_wizard(service: SetupService | None = None) -> bool:
    controller = SetupController(service or SetupService())
    return SetupWizard(controller).run()
