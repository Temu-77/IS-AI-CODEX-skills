#!/usr/bin/env python3
"""SharePoint / OpenAI設定を秘密情報なしで確認する。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1] if SKILL_ROOT.parent.name == "skills" else SKILL_ROOT.parent
POWER_AUTOMATE_DIR = REPO_ROOT
POWER_AUTOMATE_ENV = POWER_AUTOMATE_DIR / ".env"
POWER_AUTOMATE_SAVE_SCRIPT = POWER_AUTOMATE_DIR / "scripts/send_flow1_save_run.py"
SKILL_SHAREPOINT_SEND_SCRIPT = Path(__file__).resolve().with_name("send_sharepoint_flow1.py")
REPO_ENV_FILE = REPO_ROOT / ".env"
OPENAI_ENV_FILE = Path.home() / ".config/jt-codex/openai.env"
PACK_ENV_FILE = Path.home() / ".config/acrc-codex-skills/.env"


def certifi_status() -> dict[str, Any]:
    try:
        import certifi  # type: ignore
    except ImportError:
        return {"available": False, "path": ""}
    path = Path(certifi.where())
    return {"available": path.exists(), "path": str(path)}


def unquote_env_value(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def env_file_has_value(env_path: Path, name: str) -> bool:
    if not env_path.exists():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        if key.strip() == name and unquote_env_value(value):
            return True
    return False


def configured_value(name: str, env_path: Path = REPO_ENV_FILE) -> bool:
    return (
        bool(os.environ.get(name, "").strip())
        or env_file_has_value(Path.cwd() / ".env", name)
        or env_file_has_value(env_path, name)
        or env_file_has_value(PACK_ENV_FILE, name)
    )


def main() -> int:
    sharepoint_configured = configured_value("PA_SAVE_RUN_URL") and configured_value("PA_WORKFLOW_SECRET")
    openai_configured = (
        bool(os.environ.get("OPENAI_API_KEY", "").strip())
        or env_file_has_value(Path.cwd() / ".env", "OPENAI_API_KEY")
        or env_file_has_value(REPO_ENV_FILE, "OPENAI_API_KEY")
        or env_file_has_value(PACK_ENV_FILE, "OPENAI_API_KEY")
        or env_file_has_value(OPENAI_ENV_FILE, "OPENAI_API_KEY")
    )
    result = {
        "sharepoint": {
            "template_dir_exists": POWER_AUTOMATE_DIR.exists(),
            "template_save_script_exists": POWER_AUTOMATE_SAVE_SCRIPT.exists(),
            "skill_send_script_exists": SKILL_SHAREPOINT_SEND_SCRIPT.exists(),
            "env_exists": POWER_AUTOMATE_ENV.exists(),
            "save_run_url_configured": configured_value("PA_SAVE_RUN_URL"),
            "workflow_secret_configured": configured_value("PA_WORKFLOW_SECRET"),
            "certifi": certifi_status(),
            "can_build_payload": True,
            "can_post_to_sharepoint": POWER_AUTOMATE_ENV.exists() and SKILL_SHAREPOINT_SEND_SCRIPT.exists() and sharepoint_configured,
            "note": ".envにPA_SAVE_RUN_URLとPA_WORKFLOW_SECRETがない場合はpayload作成まで可能、SharePoint POSTは不可。POSTはSkill側send_sharepoint_flow1.pyを使う。",
        },
        "openai": {
            "env_var_exists": bool(os.environ.get("OPENAI_API_KEY")),
            "repo_env_file_exists": REPO_ENV_FILE.exists(),
            "repo_env_file_has_key": env_file_has_value(REPO_ENV_FILE, "OPENAI_API_KEY"),
            "pack_env_file_exists": PACK_ENV_FILE.exists(),
            "pack_env_file_has_key": env_file_has_value(PACK_ENV_FILE, "OPENAI_API_KEY"),
            "fallback_env_file_exists": OPENAI_ENV_FILE.exists(),
            "fallback_env_file_has_key": env_file_has_value(OPENAI_ENV_FILE, "OPENAI_API_KEY"),
            "can_run_gpt_image2": openai_configured,
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
