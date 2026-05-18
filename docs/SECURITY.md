# Security

## Secrets

Do not commit real credentials. Use one of:

- shell environment variables
- a local repo `.env`
- `~/.config/acrc-codex-skills/.env`

The committed `.env.example` file is only a template.

## Generated Artifacts

Generated outputs may include client creative material, local file paths, model prompts, QA notes, and provider metadata. Keep them out of Git unless intentionally sanitized.

Ignored by default:

- `.env`
- `.cache/`
- `outputs/`
- `banner-resizer-output/`
- `*.post_response.json`
- `manifest.json`
- `generated_banners.zip`

## External APIs

- OpenAI keys are loaded from environment/config files and are not accepted as CLI arguments.
- Power Automate URL and workflow secret are loaded from environment/config files.
- Adobe Firefly credentials are loaded from environment/config files.
- Canvas API-key CSV values must never be displayed, summarized, or saved.

## Sharing

Before sharing a run folder, inspect it for:

- credentials
- signed URLs
- raw provider responses
- absolute local paths
- confidential client source text
