"""Smoke-тест что пакет импортируется и имеет __version__."""

import pytest


@pytest.mark.fast()
def test_package_imports() -> None:
    import unifi_manager

    assert hasattr(unifi_manager, "__version__")
    assert isinstance(unifi_manager.__version__, str)
    assert unifi_manager.__version__ == "0.1.7"


@pytest.mark.fast()
@pytest.mark.parametrize(
    "submodule",
    [
        "unifi_manager.cli",
        "unifi_manager.clients",
        "unifi_manager.domain",
        "unifi_manager.services",
        "unifi_manager.diagnostics",
        "unifi_manager.integrations",
        "unifi_manager.utils",
    ],
)
def test_submodule_imports(submodule: str) -> None:
    assert __import__(submodule) is not None
