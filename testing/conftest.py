import os, pathlib, pytest
from pytest import fixture
from click.testing import CliRunner
from testing.testing_utils import prerequisites_hook_download_data, construct_csv_files


def pytest_addoption(parser):
    parser.addoption(
        "--device", action="store", default="cpu", help="device option: cpu or cuda"
    )


@fixture()
def device(request):
    return request.config.getoption("--device")


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()

    # we only look at actual failing test calls, not setup/teardown
    if rep.when == "call" and rep.failed:
        log_filename = os.path.join(
            pathlib.Path(__file__).parent.absolute(), "failures.log"
        )
        mode = "a" if os.path.exists(log_filename) else "w"
        with open(log_filename, mode) as f:
            f.write(rep.longreprtext + "\n")


def pytest_sessionstart(session):
    """
    This hook is executed before the pytest session starts.
    """
    prerequisites_hook_download_data()
    construct_csv_files()
