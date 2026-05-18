#!/usr/bin/env python3
"""Post a Flow 1 SharePoint save payload with a stable TLS certificate setup."""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from phase_timing_utils import record_phase_event, utc_now_iso


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1] if SKILL_ROOT.parent.name == "skills" else SKILL_ROOT.parent
DEFAULT_POWER_AUTOMATE_DIR = REPO_ROOT
CONFIG_ENV_FILE = Path.home() / ".config/acrc-codex-skills/.env"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(OPENAI_API_KEY\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(PA_SAVE_RUN_URL\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(PA_WORKFLOW_SECRET\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*bearer\s+)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(sig=)[^\s\"'&]+", re.IGNORECASE),
    re.compile(r"(code=)[^\s\"'&]+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", help="Flow 1 payload JSON path.")
    parser.add_argument("--run-dir", help="runフォルダ。未指定時はpayloadの親フォルダ。")
    parser.add_argument("--power-automate-dir", default=str(DEFAULT_POWER_AUTOMATE_DIR), help="Power Automateテンプレートフォルダ。")
    parser.add_argument("--response-output", help="POST結果JSONの保存先。未指定時は<payload>.post_response.json。")
    parser.add_argument("--dry-run", action="store_true", help="POSTせず、設定確認だけ行う。secretやURLは表示しない。")
    return parser.parse_args()


def unquote_env_value(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("("):
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def load_env(env_path: Path) -> bool:
    if not env_path.exists():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), unquote_env_value(value))
    return True


def load_env_candidates(power_automate_dir: Path) -> list[str]:
    loaded: list[str] = []
    candidates = [
        Path.cwd() / ".env",
        REPO_ROOT / ".env",
        power_automate_dir / ".env",
        CONFIG_ENV_FILE,
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if load_env(resolved):
            loaded.append(str(resolved))
    return loaded


def resolve_cert_bundle() -> tuple[str, str | None]:
    env_cert = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if env_cert and Path(env_cert).exists():
        return "env", env_cert
    try:
        import certifi  # type: ignore
    except ImportError:
        return "system_default", None
    cert_path = certifi.where()
    if cert_path and Path(cert_path).exists():
        os.environ.setdefault("SSL_CERT_FILE", cert_path)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", cert_path)
        return "certifi", cert_path
    return "system_default", None


def build_ssl_context(cert_path: str | None) -> ssl.SSLContext:
    if cert_path:
        return ssl.create_default_context(cafile=cert_path)
    return ssl.create_default_context()


def post_json(url: str, secret: str, payload: dict[str, Any], context: ssl.SSLContext) -> tuple[int, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-workflow-secret": secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def write_response(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    started_at = utc_now_iso()
    payload_path = Path(args.payload).expanduser().resolve()
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else payload_path.parent
    response_output = (
        Path(args.response_output).expanduser().resolve()
        if args.response_output
        else payload_path.with_suffix(payload_path.suffix + ".post_response.json")
    )
    power_automate_dir = Path(args.power_automate_dir).expanduser().resolve()
    env_path = power_automate_dir / ".env"

    if not payload_path.exists():
        raise FileNotFoundError(payload_path)
    loaded_env_files = load_env_candidates(power_automate_dir)
    url = os.environ.get("PA_SAVE_RUN_URL")
    secret = os.environ.get("PA_WORKFLOW_SECRET")
    if not url or not secret:
        checked = ", ".join(loaded_env_files) if loaded_env_files else ".env and ~/.config/acrc-codex-skills/.env"
        raise SystemExit(f"PA_SAVE_RUN_URL and PA_WORKFLOW_SECRET are required. Checked: {checked}")

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    cert_source, cert_path = resolve_cert_bundle()
    context = build_ssl_context(cert_path)

    if args.dry_run:
        result = {
            "status": "dry_run",
            "payload": str(payload_path),
            "python": sys.executable,
            "cert_source": cert_source,
            "cert_bundle_configured": bool(cert_path),
            "power_automate_env_exists": env_path.exists(),
            "config_env_exists": CONFIG_ENV_FILE.exists(),
            "url_configured": bool(url),
            "secret_configured": bool(secret),
        }
        write_response(response_output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    status, text = post_json(url, secret, payload, context)
    success = 200 <= status < 300
    result = {
        "status": "success" if success else "failed",
        "http_status": status,
        "response": redact(text),
        "payload": str(payload_path),
        "python": sys.executable,
        "cert_source": cert_source,
        "cert_bundle_configured": bool(cert_path),
    }
    write_response(response_output, result)
    record_phase_event(
        run_dir,
        "sharepoint",
        "post_flow1",
        status=result["status"],
        started_at=started_at,
        extra={
            "http_status": status,
            "payload": str(payload_path),
            "response_output": str(response_output),
            "cert_source": cert_source,
            "cert_bundle_configured": bool(cert_path),
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
