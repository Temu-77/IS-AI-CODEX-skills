# ACRC Codex Skills

Shareable Codex skill pack for banner planning, design production, and banner resizing workflows.

## Included Skills

- `$banner-proposal`: Japanese 2-1 banner concept workflow with GPT Image 2, QA, Canvas acceptance evaluation, and SharePoint payload support.
- `$banner-design-production`: Japanese 2-2 production design workflow for refining approved concepts.
- `$banner-resizer`: Direct banner resize workflow using GPT Image 2 safe-area generation plus Adobe Firefly outpaint.

## Install

```bash
git clone <repo-url> ACRC-codex-skills
cd ACRC-codex-skills
./install.sh
```

The installer symlinks the skill folders into `~/.codex/skills/` and creates:

```text
~/.config/acrc-codex-skills/.env
```

Fill that file with your own API keys. The file is created with `600` permissions.

You can also keep a local project `.env` next to this repo, but never commit it:

```bash
cp .env.example .env
chmod 600 .env
```

## Required Credentials

```bash
OPENAI_API_KEY=
PA_SAVE_RUN_URL=
PA_WORKFLOW_SECRET=
CANVAS_API_BASE_URL=https://mugen-ai-chat.jp
CANVAS_API_KEY=
CANVAS_COMPANY_ID=
CANVAS_AGENT_ID=
CANVAS_EXTERNAL_USER_ID=creative-production-user-001
FIREFLY_CLIENT_ID=
FIREFLY_CLIENT_SECRET=
```

Canvas credentials are only needed for `$banner-proposal` Phase 3 acceptance evaluation. Power Automate credentials are only needed for SharePoint save/post steps. Firefly credentials are only needed for `$banner-resizer`.

## Usage

After installing, restart VS Code/Codex so the skills are reloaded.

```text
$banner-proposal を使って、2-1. バナー案作成フローを実行してください。
```

```text
$banner-design-production を使って、採用案とフィードバックをもとに2-2. デザイン作成フローをPhase 1まで進めてください。
```

```text
$banner-resizer を使って、このバナーを target size:1200x628, safe area:1040x508 と target size:1080x1080, safe area:960x960 にリサイズしてください。
```

## Repository Hygiene

This repo is meant to be shared without secrets. Do not commit:

- `.env` files
- generated run outputs
- cached client materials
- `manifest.json` or POST response files from real API runs
- `__pycache__`, `.pyc`, or `.DS_Store`

See [docs/SECURITY.md](docs/SECURITY.md) for details.
