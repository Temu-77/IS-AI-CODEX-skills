# Install Guide

## Prerequisites

- VS Code
- Codex extension
- Python 3
- Optional Python packages for image workflows: `pillow`, `requests`, `python-dotenv`, `openai`, `certifi`, `pypdf`

## Steps

```bash
git clone <repo-url> ACRC-codex-skills
cd ACRC-codex-skills
./install.sh
```

Edit:

```text
~/.config/acrc-codex-skills/.env
```

Then restart VS Code/Codex.

## Updating

Because the installer uses symlinks, updating is usually just:

```bash
cd ACRC-codex-skills
git pull
```

Restart VS Code/Codex after pulling skill changes.
