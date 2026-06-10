# zenodo-release-drift

Detect drift between GitHub releases and Zenodo archives.

When a repository is connected to Zenodo via the GitHub–Zenodo webhook, every new release should be automatically archived.
In practice the webhook silently fails, gets disabled, or simply falls behind.
`zenodo-release-drift` surfaces those gaps so you can act on them.

## Installation

```bash
pip install zenodo-release-drift
# or with uv
uv add zenodo-release-drift
```

## Quick start

Check a single repository:

```bash
zenodo-release-drift check owner/repo
```

Scan every repository owned by a GitHub user or org:

```bash
zenodo-release-drift check cytomining
```

Example output:

```
GitHub user or org: cytomining
28 repos found, 5 with Zenodo integration.

Repository                Code    Description              Details
------------------------  ------  -----------------------  -------------------------------------------
cytomining/CytoTable      ZRD001  Release(s) not archived  15 release(s) not archived:
                                                           1.2.0, 1.1.4, 1.0.1, ...
cytomining/CytoTable      ZRD002  Zenodo out of date       Zenodo latest: 1.1.3  |  GitHub latest: 1.2.0
```

Exit code is **1** when drift is found (single-repo mode), **0** when clean —
suitable for CI and pre-commit hooks.

## Commands

### `check`

```
zenodo-release-drift check [OPTIONS] TARGET
```

`TARGET` is either `owner/repo` (single repository) or a GitHub username/org
(scans all owned repositories).

| Option       | Description                                                        |
| ------------ | ------------------------------------------------------------------ |
| `--json`     | Output findings as JSON                                            |
| `--markdown` | Output as a Markdown table (single repo only)                      |
| `--explain`  | Full human-readable explanation of each finding (single repo only) |

### `lint`

Explicit single-repository check — useful in pre-commit hooks where the
command name should be unambiguous.

```
zenodo-release-drift lint [OPTIONS] OWNER/REPO
```

Same options as `check`.

### `version`

```
zenodo-release-drift version
```

## Check codes

| Code   | Description                                                   |
| ------ | ------------------------------------------------------------- |
| ZRD001 | A GitHub release exists with no matching Zenodo archive       |
| ZRD002 | The latest Zenodo version is behind the latest GitHub release |

## Authentication

By default the tool makes unauthenticated GitHub API calls (60 requests/hour limit).
Set `GITHUB_TOKEN` to raise this to 5,000 requests/hour:

```bash
export GITHUB_TOKEN=ghp_...
zenodo-release-drift check my-org
```

## Pre-commit hook

Add to `.pre-commit-config.yaml` to gate commits on a single repository.
Set `args` to the repository you want to check:

```yaml
- repo: local
  hooks:
    - id: zenodo-release-drift
      name: Zenodo release drift
      entry: zenodo-release-drift lint
      args: ["owner/repo"]
      language: python
      pass_filenames: false
      always_run: true
```

## Python API

```python
from zenodo_release_drift import lint_repo, lint_repo_explain

# Returns a list of finding dicts
findings = lint_repo("owner", "repo")

# Returns a Markdown string with explanations
report = lint_repo_explain("owner", "repo")
```

## Development

```bash
git clone https://github.com/d33bs/zenodo-release-drift
cd zenodo-release-drift
uv sync --all-groups
uv run poe pipeline   # pre-commit + tests
```
