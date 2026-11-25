# Install and run Codex Detox

Use Python 3.11 or later. Install Git for repository ownership checks. The local CLI and the regression suite use the Python standard library.

## Install the personal skill

Clone or download this repository. From its root, copy the **inner** `codex-detox` directory into your personal skill directory. The result should contain `.agents/skills/codex-detox/SKILL.md`. The following commands stop if a copy already exists. If Codex Detox is already available in your skill list, use that copy.

**Windows PowerShell**

```powershell
$skillDir = Join-Path $HOME ".agents/skills"
$dest = Join-Path $skillDir "codex-detox"
if (Test-Path -LiteralPath $dest) { throw "Codex Detox already exists at $dest" }
New-Item -ItemType Directory -Force -Path $skillDir | Out-Null
Copy-Item -LiteralPath "./codex-detox" -Destination $dest -Recurse
```

**macOS or Linux**

```sh
dest="$HOME/.agents/skills/codex-detox"
mkdir -p "$HOME/.agents/skills" && mkdir "$dest" && cp -R codex-detox/. "$dest/"
```

Codex supports personal and project skill directories. [Codex skill discovery](https://developers.openai.com/codex/skills/)

## Review a project

1. Open the project in Codex. Say **“Detox this project.”**
2. Read the findings in chat or open the HTML report. A missing account listing means the status is unknown.
3. Say **“Preview item 1.”** Check the project path, personal copy, and backup path. Review any code that depends on the project's original path.
4. Approve the exact preview if you want the move. Read the receipt and observed paths.
5. To restore the project copy, say **“Undo this Detox run”** and identify the receipt if you have more than one.

## Run the scanner directly

From this repository, substitute the path to the project you want to review.

```console
python codex-detox/scripts/detox.py scan --project "/path/to/project"
```

The command prints the HTML report path. The parent directory name is the run ID. Run `python codex-detox/scripts/detox.py list --run RUN_ID` to see eligible items. Scan creates audit files under the Codex data directory. It leaves the selected project's skills in place.

## Recover a blocked run

Read the error and the observed source and backup states in `receipt.json`. If someone edited a file after preview, inspect the edit. Use a new scan for a different plan. If a move stopped mid-batch, you can retry the same approved selection or request undo for the completed moves. Preserve the saved run directory and the backup together until you finish. Live project reports can contain local paths and skill text. The public examples use fictional data.
