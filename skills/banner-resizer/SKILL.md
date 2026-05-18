---
name: banner-resizer
description: Resize existing banner/ad images directly from Codex into target canvas sizes with optional centered safe areas. Use when a user provides a source banner image and asks Codex to generate resized banners, batch banner variants, target/safe-area outputs, gpt-image-2 safe-area generation, Adobe Firefly Expand/outpaint, or a Banner Resize AI style workflow without opening the web app. This skill is for operating the banner-resize workflow, not editing the banner-resize-ai repo.
---

# Banner Resizer

## Overview

Use this skill to resize a source banner from Codex: generate a safe-area master with `gpt-image-2`, normalize it to the requested safe area, then use Adobe Firefly Expand to outpaint to the final target canvas.

## Quick Start

1. Confirm the user supplied a local source image path or attached image that can be saved locally.
2. Collect target sizes and optional safe areas. Treat blank safe-area axes as target-axis fallbacks.
3. Check credentials in the current environment or an env file:
   - `OPENAI_API_KEY` for `gpt-image-2`
   - `FIREFLY_CLIENT_ID` and `FIREFLY_CLIENT_SECRET` for Adobe Firefly outpaint
4. Run the bundled script:

```bash
python3 ~/.codex/skills/banner-resizer/scripts/resize_banner.py input/banner.png \
  --size 1200x628:1040x508 \
  --size 1080x1080:960x960 \
  --output-dir output/banner-resizer
```

Use `--dry-run` first when checking parsing, size planning, or missing dependencies without calling paid APIs.

## Size Syntax

- `1200x628` means target `1200x628`, safe area defaults to `1200x628`.
- `1200x628:1040x508` means target `1200x628`, safe area `1040x508`.
- `920x1020:500x_` means target `920x1020`, safe area `500x1020`.
- `_`, `*`, `auto`, or a blank safe-axis value falls back to the matching target axis.

## Operating Rules

- Preserve source-only content. Do not invent logos, products, CTAs, prices, offers, legal text, or brand elements absent from the source banner.
- Keep all critical existing elements fully inside the centered safe area.
- Let background and non-critical decoration extend outside the safe area.
- For `gpt-image-2`, enforce its size constraints before calling the API.
- Use Adobe Firefly only for the outpaint/expand stage. Do not add alternate image generation or outpaint providers to this skill.
- Never put provider secrets into the skill or output artifacts. Load them from env vars or a user-provided env file.

## Script Behavior

The script writes:

- final target-size PNG files
- `manifest.json` with non-secret model, size, attempt, and output metadata
- optional intermediate safe-area masters with `--keep-intermediates`
- optional ZIP archive with `--zip`

Read `references/workflow.md` for provider details, common commands, and troubleshooting.
