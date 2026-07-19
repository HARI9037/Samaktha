from app.config.settings import get_settings
from app.core.app import create_app
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings)
app = create_app(settings)
