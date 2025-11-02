# src/llm_summarizer.py
# -*- coding: utf-8 -*-
"""
LLM Summarizer for txt2notion (optional module)
- openai provider 기준 최소 동작 버전
- JSON 형식으로 섹션별 요약 결과 반환
"""
import os
import re
import json
import requests
from typing import Dict

def _redact(text: str, patterns):
    """LLM 호출 전 민감정보 마스킹"""
    if not patterns:
        return text
    red = text
    for pat in patterns:
        try:
            red = re.sub(pat, "[REDACTED]", red, flags=re.IGNORECASE)
        except re.error:
            continue
    return red

def extract_sections(raw_text: str, cfg: Dict) -> Dict:
    """
    입력 텍스트 → OpenAI ChatCompletion → JSON(dict)
    실패 시 {} 반환
    """
    # 최소 길이 조건
    min_len = int(cfg.get("pass_through_if_shorter_than", 0))
    if len(raw_text) < min_len:
        return {}

    # 마스킹
    redacted = _redact(raw_text, cfg.get("redact_patterns", []))

    # 프롬프트 로드
    try:
        with open("prompts/system.md", "r", encoding="utf-8") as f:
            system_prompt = f.read().strip()
        with open("prompts/extract_sections.md", "r", encoding="utf-8") as f:
            user_prompt = f.read().strip()
    except Exception as e:
        print(f"[WARN] LLM 프롬프트 로드 실패: {e}")
        return {}

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[WARN] OPENAI_API_KEY 환경변수가 없습니다. LLM 요약 비활성화.")
        return {}

    # OpenAI ChatCompletion 요청
    body = {
        "model": cfg.get("model", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + "\n\n=== 원문 ===\n" + redacted}
        ],
        "temperature": float(cfg.get("temperature", 0.2)),
        "max_tokens": int(cfg.get("max_tokens", 1200))
    }

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=int(cfg.get("timeout_s", 30))
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        # JSON 파싱 (LLM이 포맷을 지키지 않는 경우 예외 발생 가능)
        return json.loads(content)
    except Exception as e:
        print(f"[WARN] LLM 호출 실패 또는 JSON 파싱 실패: {e}")
        return {}
