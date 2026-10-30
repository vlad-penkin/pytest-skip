import pytest

pytest_plugins = ["pytester"]

SELECT_OPT = "--select-from-file"
DESELECT_OPT = "--deselect-from-file"
SKIP_OPT = "--skip-from-file"
XFAIL_OPT = "--xfail-from-file"


@pytest.fixture
def is_xdist_installed(pytestconfig: pytest.Config):
    return pytestconfig.pluginmanager.hasplugin("xdist")
