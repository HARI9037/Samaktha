from fastapi import APIRouter, Depends, Request

from app.config.settings import Settings, get_settings
from app.diagnostics import SystemDiagnostics
from app.models.health import HealthResponse
from app.providers.config import ProviderSettings, _PRODUCTION_PROVIDERS

router = APIRouter(tags=["health"])


def get_provider_settings() -> ProviderSettings:
    return ProviderSettings()


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: Settings = Depends(get_settings),
    provider_settings: ProviderSettings = Depends(get_provider_settings),
) -> HealthResponse:
    """Liveness probe.

    The application is reachable (200) even when provider credentials are
    absent; missing credentials are reported as a degraded dependency state
    rather than a startup failure.
    """
    providers: dict[str, str] = {}
    for provider_id in _PRODUCTION_PROVIDERS:
        if not provider_settings.is_provider_enabled(provider_id):
            providers[provider_id] = "disabled"
        elif provider_settings.is_provider_configured(provider_id):
            providers[provider_id] = "configured"
        else:
            providers[provider_id] = "missing_credentials"

    degraded = (
        not provider_settings.mock_allowed()
        and not provider_settings.configured_production_providers()
    )

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        degraded=degraded,
        providers=providers,
    )


@router.get("/diagnostics")
async def diagnostics_report(
    request: Request,
    provider_settings: ProviderSettings = Depends(get_provider_settings),
) -> dict:
    """P2.7 — diagnostic reporting over HTTP.

    Runs the same deterministic health sweep as the TUI ``/doctor`` view and
    returns it as JSON so remote operators can observe system health.
    """
    orchestrator = getattr(request.app.state, "orchestrator", None)
    report = SystemDiagnostics(
        settings=provider_settings,
        orchestrator=orchestrator,
    ).run()
    return {
        "version": report.version,
        "healthy": not report.is_critical(),
        "health_percentage": report.health_percentage(),
        "checks": [check.__dict__ for check in report.checks],
    }
