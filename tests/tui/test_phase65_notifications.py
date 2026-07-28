"""Tests for Phase 6.5 In-TUI Notification Widget."""

from app.tui.notifications import NotificationKind, NotificationBanner, NotificationHost


def test_notification_kinds_exist():
    assert NotificationKind.SUCCESS
    assert NotificationKind.WARNING
    assert NotificationKind.ERROR
    assert NotificationKind.INFO


def test_notification_banner_instantiation():
    banner = NotificationBanner("Test message", NotificationKind.SUCCESS, duration=1.0)
    assert banner._message == "Test message"
    assert banner._kind == NotificationKind.SUCCESS
    assert banner._duration == 1.0


def test_notification_banner_inherits_widget():
    from textual.widget import Widget
    banner = NotificationBanner("hello", NotificationKind.INFO)
    assert isinstance(banner, Widget)


def test_notification_host_instantiation():
    host = NotificationHost()
    assert hasattr(host, "notify_tui")


def test_notification_banner_css_class():
    """Ensure CSS class is set from kind."""
    banner = NotificationBanner("error!", NotificationKind.ERROR)
    assert "error" in banner.classes


def test_notification_banner_info_class():
    banner = NotificationBanner("info", NotificationKind.INFO)
    assert "info" in banner.classes
