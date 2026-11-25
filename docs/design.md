# How Detox verifies a cleanup

| Step | Evidence | Decision |
| --- | --- | --- |
| Scan | Codex skill name, relative paths, file hashes, and mode bits | Compare whole bundles. Flag changed helpers, assets, or instructions. Exclude links and incomplete comparisons from automatic archive. |
| Check ownership | Git index and current commit | Protect tracked files, including a path removed from the index that still exists in the current commit. |
| Preview | Selected run, action IDs, source, backup, and retained copy | Bind the preview to the proposed plan. Approval takes place in chat. |
| Apply | Project lock, current paths, bundle fingerprints, and pending move recorded in the receipt | Check the full batch. Check again before each move. Use a rename that refuses an occupied destination. |
| Retry or undo | Observed source, backup, and personal copy | Reconcile an interrupted move. Stop on an unexpected path state. Preserve the receipt when a batch stops. |

For a Git project, backups for new moves go under the repository metadata directory. For a project outside Git, backups go under `.codex-detox-backups` in the project. A receipt is a record of observed state. The next operation checks the files again. The process-exit test covers a stopped process. Power-loss durability has separate failure modes and has not been tested here.

The scanner reads the current folder and its ancestors up to the repository root, plus the standard personal skills location. It does not scan every sibling or every managed plugin. The bundle comparator limits size, depth, and entry count. When it cannot complete a comparison, it reports the item for manual review.

| Code | Responsibility |
| --- | --- |
| [inventory.py](../codex-detox/scripts/inventory.py) | Read the project, compare bundles, and check Git ownership. |
| [detox.py](../codex-detox/scripts/detox.py) | Build the report, validate a selection, and preview the plan. |
| [journal.py](../codex-detox/scripts/journal.py) | Lock, move, restore, and verify the observed state. |
| [schedules.py](../codex-detox/scripts/schedules.py) | Record a schedule plan and compare provider observations before and after a pause or resume. |
