# src/main.py
# -*- coding: utf-8 -*-
"""
TXT → Markdown 변환기 (v0.1.1 + optional LLM assist)
- 기본: 규칙 기반(tagging_rules.yaml)으로 섹션 분류/요약
- 옵션: --llm 켜면 LLM 요약으로 섹션을 보강(실패/미지원 시 규칙 기반으로 폴백)
- 민감정보 마스킹(--mask), 고객사명/키워드 태깅(customers.yaml / tagging_rules.yaml) 지원
"""

import argparse
import os
import re
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML이 필요합니다. `pip install pyyaml` 후 다시 시도하세요.", file=sys.stderr)
    sys.exit(1)


# ---------- 유틸 ----------

def load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"[WARN] Read failed: {path} ({e})")
        return ""


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def mask_ip_mac(text: str) -> str:
    # IPv4
    text = re.sub(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b",
                  "[REDACTED_IP]", text)
    # MAC
    text = re.sub(r"\b(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}\b", "[REDACTED_MAC]", text)
    return text


def mask_customers(text: str, customers_cfg: dict) -> str:
    """
    customers.yaml 예시:
    patterns:
      - "케피코"
      - "KEFICO"
      - "SK ?hynix"
      - "하이닉스"
    """
    pats = (customers_cfg.get("patterns") or []) if isinstance(customers_cfg, dict) else []
    for pat in pats:
        try:
            text = re.sub(pat, _mask_match, text, flags=re.IGNORECASE)
        except re.error:
            # 정규식 오류는 무시하고 원문 유지
            continue
    return text


def _mask_match(m: re.Match) -> str:
    s = m.group(0)
    if len(s) <= 2:
        return "*" * len(s)
    # 가운데 마스킹
    return s[0] + ("*" * (len(s) - 2)) + s[-1]


def infer_title(src_path: Path, text: str) -> str:
    # 1) 파일 첫 줄이 제목처럼 보이면 사용
    first_line = (text.splitlines() or [""])[0].strip("# ").strip()
    if 3 <= len(first_line) <= 120:
        return first_line
    # 2) 파일명 기반
    return src_path.stem[:120]


def dedup_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        k = x.strip()
        if not k:
            continue
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def json_array(items: List[str]) -> str:
    return json.dumps(items, ensure_ascii=False)


# ---------- 규칙 기반 섹션 분류 ----------

def section_signals_from_rules(rules: dict) -> dict:
    # tagging_rules.yaml 안에 section_signals 가 있으면 사용
    # 없으면 기본값
    default = {
        "summary": ["증상", "현상", "문제", "오류", "에러", "장애", "로그", "발생", "환경", "버전"],
        "root_cause": ["원인", "근본 원인", "분석", "재현", "because", "due to", "정책 충돌", "세션", "타임아웃", "DHCP", "DNS", "ARP", "TTL", "오탐"],
        "actions": ["조치", "해결", "수정", "변경", "적용", "재기동", "재시작", "명령어", "쿼리", "스크립트", "설정값", "패치"],
        "prevention": ["재발 방지", "SOP", "모니터링", "알람", "운영 기준", "체크리스트", "자동화", "권장값", "튜닝", "한계", "주의"]
    }
    if isinstance(rules, dict) and "section_signals" in rules:
        return rules["section_signals"] or default
    return default


def score_sentence(sent: str, signals: dict) -> str:
    s = sent.lower()
    # 가중치 기본
    scores = {k: 0 for k in ["summary", "root_cause", "actions", "prevention"]}

    # 키워드 매칭
    for sec, words in signals.items():
        for w in words:
            try:
                if re.search(w, s, flags=re.IGNORECASE):
                    scores[sec] += 1
            except re.error:
                # 신호어가 정규식인데 오류일 경우 무시
                continue

    # 추가 휴리스틱
    if re.search(r"```|^\s{0,4}(\$|sudo|systemctl|msiexec|mysql|curl|kubectl|helm|terraform)\b", sent, re.IGNORECASE | re.MULTILINE):
        scores["actions"] += 2
    if re.search(r"\b(err(or)?|fail(ed)?|exception|traceback|timeout|denied)\b", s):
        scores["root_cause"] += 1
    if re.search(r"(권장|주의|모니터링|주기|임계치|threshold|alert)", s):
        scores["prevention"] += 1

    # 상단부 가산(초반 몇 줄은 상황요약일 확률↑)
    # (이 함수 단독으로는 위치정보가 없으니 상위에서 일부만 summary로 고정하는 전략을 써도 됨)
    # 여기서는 생략.

    # 최대 득점 섹션
    section = max(scores, key=lambda k: scores[k])
    return section


def classify_sections_rule_based(text: str, rules: dict) -> Dict[str, str]:
    """
    간단: 문단 단위로 스코어 → 섹션 배치
    """
    signals = section_signals_from_rules(rules)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    buckets = {"summary": [], "root_cause": [], "actions": [], "prevention": []}

    # 맨 앞 10줄 정도는 summary 가산(문단 단위라 간단히 처음 1~2개를 summary에 우선 배치)
    if paras:
        head = paras[:2]
        for p in head:
            buckets["summary"].append(p)
        body = paras[2:]
    else:
        body = []

    for p in body:
        sec = score_sentence(p, signals)
        buckets[sec].append(p)

    # 섹션 텍스트 합치기
    out = {k: "\n\n".join(v).strip() for k, v in buckets.items()}
    # 너무 짧으면 빈 값 처리(빈 섹션은 템플릿에서 사실상 스킵)
    for k, v in out.items():
        if len(v) < 20:
            out[k] = ""
    return out


# ---------- 템플릿 렌더 ----------

def render_markdown(template_path: str, fm: Dict[str, str], body: Dict[str, str]) -> str:
    """
    template.md.tpl 에 다음 플레이스홀더가 있다고 가정:
      {title} {category_json} {tags_json} {date} {source_file} {storage_category}
      {summary} {root_cause} {actions} {prevention} {summary_tldr}
    """
    tpl = Path(template_path).read_text(encoding="utf-8")
    data = {
        "title": fm.get("title", ""),
        "category_json": json_array(fm.get("category", [])),
        "tags_json": json_array(fm.get("tags", [])),
        "publish": str(fm.get("publish", True)).lower(),
        "date": fm.get("date", ""),
        "source_file": fm.get("source_file", ""),
        "storage_category": fm.get("storage_category", ""),
        "summary_tldr": body.get("summary_tldr", "").strip(),
        "summary": body.get("summary", "").strip(),
        "root_cause": body.get("root_cause", "").strip(),
        "actions": body.get("actions", "").strip(),
        "prevention": body.get("prevention", "").strip(),
        "raw_body": body.get("raw_body", "").strip(),
    }
    out = tpl
    for k, v in data.items():
        out = out.replace("{" + k + "}", v)

    # 빈 섹션 헤더 정리(아주 단순한 후처리)
    out = _strip_empty_section(out, "## 🧭 상황 요약 (What happened)", data["summary"] or data["summary_tldr"])
    out = _strip_empty_section(out, "## 🧠 원인 분석 (Root cause)", data["root_cause"])
    out = _strip_empty_section(out, "## 🛠 조치 방안 (Action taken)", data["actions"])
    out = _strip_empty_section(out, "## 🔁 재발 방지 / 운영 가이드 (Prevention / SOP)", data["prevention"])
    return out


def _strip_empty_section(md: str, header: str, content: str) -> str:
    if content:
        return md
    # 헤더 라인부터 다음 헤더 전까지 삭제 (간단 패턴)
    pattern = rf"{re.escape(header)}\n.*?(?=\n## |\Z)"
    return re.sub(pattern, "", md, flags=re.DOTALL)


# ---------- LLM 보조 (옵션) ----------

def try_llm_extract(raw_text: str, llm_cfg: dict) -> Dict[str, str]:
    """
    llm_summarizer.extract_sections() 호출.
    - 키/설정/프롬프트 없으면 {} 반환 → 상위에서 규칙 기반 결과 사용
    """
    if not llm_cfg:
        return {}
    # 길이 기준
    min_len = int(llm_cfg.get("pass_through_if_shorter_than", 0))
    if len(raw_text) < min_len:
        return {}

    try:
        from llm_summarizer import extract_sections
    except Exception:
        return {}

    try:
        out = extract_sections(raw_text, llm_cfg) or {}
        # 스키마 키를 강제 보정
        return {
            "title": out.get("title") or "",
            "summary_tldr": out.get("summary_tldr") or "",
            "summary": out.get("summary") or "",
            "root_cause": out.get("root_cause") or "",
            "actions": out.get("actions") or "",
            "prevention": out.get("prevention") or "",
            "tags": out.get("tags") or [],
            "category": out.get("category") or [],
        }
    except Exception:
        return {}


# ---------- 메인 ----------

def main():
    ap = argparse.ArgumentParser(description="TXT → MD converter (rule-based, optional LLM assist)")
    ap.add_argument("--src_dir", required=True, help="원본 TXT 루트 디렉토리")
    ap.add_argument("--out_dir", required=True, help="결과 MD 루트 디렉토리(Obsidian Vault 하위 권장)")
    ap.add_argument("--customers", default="./configs/customers.yaml", help="고객사 마스킹 설정")
    ap.add_argument("--rules", default="./configs/tagging_rules.yaml", help="태깅/섹션 규칙")
    ap.add_argument("--template", default="./templates/template.md.tpl", help="Markdown 템플릿")
    ap.add_argument("--mask", action="store_true", help="IP/MAC/고객사 마스킹 활성화")
    ap.add_argument("--dry_run", action="store_true", help="파일 저장 없이 처리만")
    # LLM 옵션(실험)
    ap.add_argument("--llm", action="store_true", help="LLM 보조 요약 활성화 (실패시 규칙 기반 폴백)")
    ap.add_argument("--llm-config", default="./configs/llm_config.yaml", help="LLM 설정 파일 경로")
    args = ap.parse_args()

    src_dir = Path(os.path.expanduser(args.src_dir)).resolve()
    out_dir = Path(os.path.expanduser(args.out_dir)).resolve()

    if not src_dir.exists():
        print(f"[ERROR] src_dir not found: {src_dir}", file=sys.stderr)
        sys.exit(2)

    ensure_dir(out_dir)

    customers_cfg = load_yaml(args.customers)
    rules_cfg = load_yaml(args.rules)

    # LLM 설정 로드(옵션)
    llm_cfg = {}
    if args.llm:
        llm_cfg = load_yaml(args.llm_config) or {}
        # 설정이 없으면 조용히 규칙 기반만 사용
        if not llm_cfg:
            print("[WARN] LLM 설정이 없어 규칙 기반으로만 처리합니다 (--llm-config 확인).")

    txt_files: List[Path] = []
    for p in src_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".txt":
            txt_files.append(p)

    if not txt_files:
        print(f"[WARN] TXT 파일이 없습니다: {src_dir}")
        print("완료: TXT → MD 변환이 끝났습니다. Obsidian/Notion에 연결하세요.")
        return

    total = 0
    written = 0

    for src_path in sorted(txt_files):
        total += 1
        rel = src_path.relative_to(src_dir)
        dest_path = (out_dir / rel).with_suffix(".md")
        ensure_dir(dest_path.parent)

        raw = read_text(src_path)
        if not raw.strip():
            print(f"[SKIP] Empty file: {src_path}")
            continue

        # 마스킹
        masked = raw
        if args.mask:
            masked = mask_ip_mac(masked)
            masked = mask_customers(masked, customers_cfg)

        # 규칙 기반 분류
        rb_sections = classify_sections_rule_based(masked, rules_cfg)
        rb_tags = infer_tags(src_path, masked, rules_cfg)
        rb_category = infer_category(src_path, masked, rules_cfg)

        # LLM 보조(성공 시 해당 섹션/태그/카테고리 보강)
        llm_out = {}
        if args.llm:
            llm_out = try_llm_extract(masked, llm_cfg)

        # 타이틀
        title = (llm_out.get("title") or "").strip() if llm_out else ""
        if not title:
            title = infer_title(src_path, masked)

        # 합성(LLM 우선 → 규칙 기반 폴백)
        final = {
            "summary_tldr": (llm_out.get("summary_tldr") or "").strip(),
            "summary": (llm_out.get("summary") or "").strip() or rb_sections.get("summary", ""),
            "root_cause": (llm_out.get("root_cause") or "").strip() or rb_sections.get("root_cause", ""),
            "actions": (llm_out.get("actions") or "").strip() or rb_sections.get("actions", ""),
            "prevention": (llm_out.get("prevention") or "").strip() or rb_sections.get("prevention", ""),
            "raw_body": masked.strip(),
        }

        final_tags = dedup_keep_order((rb_tags or []) + (llm_out.get("tags") or []))[:5]
        final_cat = dedup_keep_order((rb_category or []) + (llm_out.get("category") or []))[:3]

        # Front matter
        fm = {
            "title": title,
            "tags": final_tags,
            "category": final_cat,
            "publish": True,
            "date": datetime.fromtimestamp(src_path.stat().st_mtime).strftime("%Y-%m-%d"),
            "source_file": str(src_path),
            "storage_category": "/".join(rel.parts[:-1]) if len(rel.parts) > 1 else "",
        }

        # 템플릿 렌더
        md_text = render_markdown(args.template, fm, final)

        if args.dry_run:
            print(f"[DRY] {src_path} -> {dest_path}")
        else:
            dest_path.write_text(md_text, encoding="utf-8")
            written += 1
            print(f"[OK] {src_path} -> {dest_path}")

    print(f"완료: TXT → MD 변환이 끝났습니다. Obsidian/Notion에 연결하세요. (총 {total}건, 생성 {written}건)")


# ---------- 태그/카테고리 추정(간단 규칙) ----------

def infer_tags(src_path: Path, text: str, rules: dict) -> List[str]:
    """
    tagging_rules.yaml 예시:
    tags:
      NAC: ["NAC","센서","인증"]
      Ubuntu: ["Ubuntu","우분투"]
      VM: ["VM","가상화","ESXi"]
      Elasticsearch: ["Elasticsearch","ES","인덱스"]
    """
    out: List[str] = []
    tags_map = (rules.get("tags") or {}) if isinstance(rules, dict) else {}
    hay = (src_path.name + "\n" + text)
    for tag, keys in tags_map.items():
        if not isinstance(keys, list):
            continue
        for k in keys:
            try:
                if re.search(k, hay, flags=re.IGNORECASE):
                    out.append(tag)
                    break
            except re.error:
                continue
    return dedup_keep_order(out)


def infer_category(src_path: Path, text: str, rules: dict) -> List[str]:
    """
    tagging_rules.yaml 예시:
    categories:
      - "NAC"
      - "Ubuntu"
      - "VM"
      - "Elasticsearch"
    파일명/본문 키워드 기반으로 간단 매핑. 복수 카테고리 허용.
    """
    cats = rules.get("categories") or []
    if not isinstance(cats, list):
        return []
    out: List[str] = []
    hay = (src_path.name + "\n" + text)
    for c in cats:
        try:
            if re.search(c, hay, flags=re.IGNORECASE):
                out.append(c)
        except re.error:
            continue
    return dedup_keep_order(out)


if __name__ == "__main__":
    main()
