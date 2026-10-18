"""에이전트 실행부. 각 에이전트는 터미널에서 `claude -p`(Claude Code 헤드리스 모드)로 돌아요.

API 키 없이 내 Claude 로그인으로 돌고, --json-schema로 구조화된 결과를 받아요.
"""
import json
import os
import shutil
import subprocess
from typing import TypeVar

from pydantic import BaseModel

from .config import LLM, ROOT

T = TypeVar("T", bound=BaseModel)


def _env() -> dict:
    # Claude 데스크톱 앱 등 다른 Claude 세션 안에서 서버를 켜도, 내 CLI 로그인을 쓰도록 세션 변수를 걷어내요
    return {k: v for k, v in os.environ.items()
            if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC"))}


def ask(system: str, user: str, schema: type[T], tools: list[str] | None = None, timeout: int = 600) -> T:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude CLI를 찾을 수 없어요. Claude Code를 설치해 주세요.")
    cmd = [
        exe, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema.model_json_schema(), ensure_ascii=False),
        "--system-prompt", system,
        "--model", LLM["model"],
        "--no-session-persistence",
        "--strict-mcp-config",
        "--tools", ",".join(tools or []),
    ]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]

    proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, env=_env(), cwd=ROOT)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p 실행 실패: {(proc.stderr or proc.stdout)[:500]}")
    if out.get("is_error"):
        msg = out.get("result") or "알 수 없는 오류"
        if "authenticate" in msg.lower() or "login" in msg.lower():
            msg += " → 터미널에서 `claude`를 실행해 /login 해 주세요."
        raise RuntimeError(msg)
    data = out.get("structured_output")
    if data is None:
        raise RuntimeError("구조화된 결과를 받지 못했어요.")
    return schema.model_validate(data)
