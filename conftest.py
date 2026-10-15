"""Integration gates: a required Docker job cannot pass by skipping its work."""

import pytest


def pytest_addoption(parser):
    parser.addoption("--require-docker", action="store_true", help="Fail on absent/skipped Docker coverage")


def pytest_collection_finish(session):
    session.config._required_docker_nodes = {
        item.nodeid for item in session.items if item.get_closest_marker("docker")
    }
    session.config._skipped_docker_nodes = set()
    if session.config.getoption("--require-docker") and not session.config._required_docker_nodes:
        raise pytest.UsageError("--require-docker requires at least one selected Docker test")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    if report.skipped and item.nodeid in item.config._required_docker_nodes:
        item.config._skipped_docker_nodes.add(item.nodeid)


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--require-docker") and getattr(session.config, "_skipped_docker_nodes", set()):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    skipped = getattr(config, "_skipped_docker_nodes", set())
    if config.getoption("--require-docker") and skipped:
        terminalreporter.write_sep("=", "Required Docker tests skipped; integration gate failed", red=True)
        for node in sorted(skipped):
            terminalreporter.write_line(node)
