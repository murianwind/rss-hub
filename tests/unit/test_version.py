from importlib.metadata import PackageNotFoundError

from rss_hub.version import get_version


def test_the_installed_package_version_is_returned(monkeypatch):
    monkeypatch.setattr("rss_hub.version.version", lambda name: "9.9.9")
    assert get_version() == "9.9.9"


def test_a_checkout_that_is_not_installed_reports_dev(monkeypatch):
    def not_installed(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr("rss_hub.version.version", not_installed)
    assert get_version() == "dev"
