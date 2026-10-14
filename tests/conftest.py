"""Shared fixtures."""

import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def offline_page():
    """Open saved pages in headless Chrome with every network request denied.

    The fixture skips when Playwright or Chrome is missing. Set FLOWSIM_CHROME
    to choose a browser; a FLOWSIM_CHROME path that does not exist fails.
    """
    sync_api = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("FLOWSIM_CHROME")
    if executable is not None and not Path(executable).exists():
        pytest.fail(f"FLOWSIM_CHROME points to a missing file: {executable}")
    executable = executable or shutil.which("google-chrome") or shutil.which("chromium")
    if executable is None:
        pytest.skip("Set FLOWSIM_CHROME to a Chrome or Chromium executable.")
    errors: list[str] = []
    with sync_api.sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=executable,
            headless=True,
            args=["--no-sandbox"],
        )

        def open_page(path: Path):
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            page.goto(path.resolve().as_uri())
            return page

        try:
            yield open_page
        finally:
            browser.close()
    assert not errors, errors
