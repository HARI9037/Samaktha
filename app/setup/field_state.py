"""Wizard input transitions: an empty hidden secret widget means unchanged."""
SECRET_FIELDS = {
    "provider_api_key": ("provider_credential_state", "remove_provider_credential"),
    "brave_api_key": ("brave_credential_state", "remove_brave_credential"),
    "smtp_password": ("smtp_credential_state", "remove_smtp_credential"),
}
DEPENDENCIES = {
    "provider_verified": ("primary_provider", "provider_model", "provider_endpoint", "provider_api_key", "remove_provider_credential", "import_environment_credential"),
    "search_verified": ("search_provider", "searxng_url", "brave_api_key", "remove_brave_credential"),
    "smtp_auth_verified": ("smtp_host", "smtp_port", "smtp_security", "smtp_username", "smtp_sender", "smtp_password", "remove_smtp_credential"),
}


def capture_fields(previous: dict, changes: dict) -> dict:
    result = dict(previous)
    for key, value in changes.items():
        if key in SECRET_FIELDS and not value:
            continue
        result[key] = value
    for field, (state, remove) in SECRET_FIELDS.items():
        if result.get(remove):
            result[field] = None
            result[state] = "remove_secret_requested"
        elif result.get(field):
            result[state] = "new_secret_provided"
    for verified, dependencies in DEPENDENCIES.items():
        if any(previous.get(key) != result.get(key) for key in dependencies):
            result[verified] = False
    return result
