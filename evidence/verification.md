# Verification evidence

The public distribution passed **17 of 17 regression tests** on Linux with Python 3.12.14 and Git 2.56.1. All tests used disposable data. The separate sample also completed its scan, preview, archive, and undo checks. [Test output](linux-tests.txt) · [Sample output](sample-run.txt) · [Restored receipt](../examples/restored-receipt.json)

| Failure or boundary | What the test checks |
| --- | --- |
| Process exits just after a rename | The next run reconciles the pending move and can restore the project copy. |
| Second item changes after preview | The full-batch check stops before moving the first item. |
| A move fails during a batch | The receipt identifies completed work. Undo restores the moved item. |
| An operator restores a folder by hand | The next Apply detects the changed path state. |
| Restore destination is occupied | Undo preserves the occupied destination. |
| Two skills share a name | A changed helper or an extra empty directory excludes the pair from archive. |
| Git ownership changes | The scanner checks staged files and the current commit. Apply rechecks ownership after preview. |
| A connector setting has the wrong type | The scan reports the bad setting and keeps other findings. |
| A schedule changes state | The receipt helper checks the task ID, title, enabled state, and phase against sample observations. |

## Repeat the checks

Run from the repository root.

```console
python -B -m unittest discover -s codex-detox/tests -v
python -B examples/try_detox.py
```

The test suite needs Git to exercise its Git cases. The link test can skip on hosts that cannot create symbolic links. Check the test output for skips.

## Browser and platform scope

The optional browser test uses Playwright and Chromium. It selects an item, downloads the checklist, checks the exported IDs, then runs preview, archive, and undo. In a Python environment used for testing, run:

```console
python -m pip install playwright
python -m playwright install chromium
python -B codex-detox/tests/browser_acceptance.py
```

On November 25, 2026, the Linux run passed all 17 tests with Python 3.12.14 and Git 2.56.1. The public sample passed archive and restore. The separate browser test passed with Chromium 158.0.8127.0. It checked the initial disabled button, downloaded the selected IDs, and used the downloaded file for preview, archive, and undo. [Browser test](../codex-detox/tests/browser_acceptance.py)

To use an existing Chromium installation, pass its executable path with `--browser`. The Linux run used this option. The schedule tests use sample provider observations. Live pause and resume need a connected provider. See [GitHub Actions](https://github.com/jpet121/Codex-Detox/actions) for the results on each operating system.
