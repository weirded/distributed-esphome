"""pytest configuration — adds source paths to sys.path."""
import sys
from pathlib import Path

import pytest

# Server modules
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "server"))
# Client modules
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "client"))
# HA custom integration lives under ha-addon/custom_integration/ so the
# add-on's Dockerfile can COPY it into the container. Tests import it as
# `esphome_fleet.*` — the enclosing directory goes on sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "custom_integration"))


@pytest.fixture(autouse=True)
def _reset_auto_versioning_state():
    """Clear git_versioning module state between tests.

    `commit_file()` schedules an asyncio task on the current event loop;
    pytest-asyncio creates a fresh loop per test function, so any task
    left in ``_pending`` from a prior test is bound to a now-closed
    loop. Resetting between tests keeps locks/tasks loop-local.

    Also clears the bug-#7 auth-failure rate-limit state in main.py
    so tests that assert on WARNING lines don't see suppressed output
    from a prior test with the same (peer_ip, reason) key.
    """
    # PR #80 review: don't import `main` here just to clear its state.
    # Importing ha-addon/server/main.py has real side-effects (module-
    # level logging.basicConfig, background-task module registrations)
    # that slow the suite and alter log-capture behaviour for every
    # test, even the ones that never touch `main`. Only clear the
    # state if *some earlier test* already imported `main` itself,
    # using ``sys.modules.get`` — that way we still clean up the
    # rate-limit dicts when they're dirty, but a pure
    # git_versioning/settings/queue test never pays the import tax.
    try:
        import git_versioning as _gv
    except ImportError:
        _gv = None
    _main = sys.modules.get("main")

    if _gv is not None:
        _gv._reset_for_tests()
    if _main is not None:
        if hasattr(_main, "_auth_fail_last_logged"):
            _main._auth_fail_last_logged.clear()
        if hasattr(_main, "_auth_fail_suppressed"):
            _main._auth_fail_suppressed.clear()

    yield

    if _gv is not None:
        _gv._reset_for_tests()
    # Re-read from sys.modules post-yield in case a test imported main.
    _main = sys.modules.get("main")
    if _main is not None:
        if hasattr(_main, "_auth_fail_last_logged"):
            _main._auth_fail_last_logged.clear()
        if hasattr(_main, "_auth_fail_suppressed"):
            _main._auth_fail_suppressed.clear()


