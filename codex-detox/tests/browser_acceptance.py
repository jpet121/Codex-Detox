"""Optional real browser acceptance: python tests/browser_acceptance.py [--browser /path/to/chrome].
Requires Playwright and a Chromium browser. Operates only on temporary fixture files.
"""
import argparse
import json
from pathlib import Path

from test_detox import DetoxTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Path to an installed Chrome, Edge, or Chromium executable")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright
    fixture = DetoxTests()
    fixture.setUp()
    try:
        folder = fixture.pair("review", bundled=True)
        fixture.scan()
        with sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=args.browser)
            page = browser.new_page()
            page.goto(fixture.page.as_uri())
            button = page.get_by_role("button", name="Export selection")
            fixture.assertTrue(button.is_disabled())
            page.get_by_role("checkbox", name="Item 1 · Archive project copy").check()
            with page.expect_download() as event:
                button.click()
            selection = fixture.root / "downloaded.json"
            event.value.save_as(str(selection))
            browser.close()
        data = json.loads(selection.read_text(encoding="utf-8"))
        fixture.assertEqual(data, {"run":fixture.run,"ids":list(fixture.actions)})
        fixture.args = ["--run", fixture.run, "--selection", str(selection)]
        fixture.token = fixture.cli("preview",*fixture.args).stdout.split()[-1]
        fixture.apply()
        fixture.assertFalse(folder.exists())
        fixture.undo()
        fixture.assertTrue((Path(folder)/"assets/sample").is_file())
        print("PASS: browser download, preview, archive, and restore")
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
