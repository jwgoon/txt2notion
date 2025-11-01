#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, argparse, re, json
from datetime import date
try:
    import yaml  # pip install pyyaml
except Exception:
    print("[ERROR] PyYAML 미설치. venv에서 `pip install pyyaml` 실행하세요.", file=sys.stderr)
    sys.exit(1)

# ---------- 공통 유틸 ----------
def expand(p):  # ~, $HOME, 등 확장
    return os.path.expanduser(os.path.expandvars(p))

def read(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def json_list(x):
    return json.dumps(x, ensure_ascii=False)

def render_template(tpl: str, ctx: dict) -> str:
    # 둘 다 지원: {{ key }} 와 {key}
    for k, v in ctx.items():
        tpl = tpl.replace("{{ " + k + " }}", str(v))
        tpl = tpl.replace("{" + k + "}", str(v))
    return tpl

# ---------- 민감정보 마스킹 ----------
def collect_sensitive_names(customers_cfg: dict):
    names = set()
    # 1) SENSITIVE_NAME 루트 키
    for n in customers_cfg.get("SENSITIVE_NAME", []):
        names.add(n)
    # 2) customers[].aliases
    for c in customers_cfg.get("customers", []) or []:
        for a in c.get("aliases", []) or []:
            names.add(a)
    return sorted(names, key=len, reverse=True)

def mask_text(text: str, terms):
    masked = text
    for t in terms:
        if not t or t.strip() == "": 
            continue
        # 한글 마스킹: 첫/마지막 글자만 남기고 가운데 *
        def _mask_kor(word):
            return word if len(word) <= 2 else word[0] + ("*"*(len(word)-2)) + word[-1]
        masked = re.sub(re.escape(t), _mask_kor(t), masked)
    return masked

# ---------- 태깅/카테고리 ----------
def apply_tagging_rules(filename, content, rules_cfg):
    text = (filename + "\n" + content).lower()
    tags = []
    for rule in (rules_cfg.get("rules") or []):
        kws = [k.lower() for k in rule.get("keywords", [])]
        if any(k in text for k in kws):
            tags.extend(rule.get("tags", []))
    # 자동 패턴
    ap = rules_cfg.get("auto_patterns", {}) or {}
    if ap.get("ip") and re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
        tags.append("ip-언급")
    if ap.get("mac") and re.search(r"\b[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(\1[0-9A-Fa-f]{2}){4}\b", text):
        tags.append("mac-언급")
    for p in ap.get("port", []) or []:
        if re.search(rf"(\b|:)({p})(\b)", text):
            tags.append(f"port-{p}")
    if ap.get("sql") and re.search(r"\b(select|update|insert|delete|where|join|from)\b", text):
        tags.append("sql")
    if ap.get("elastic") and re.search(r"\b(elasticsearch|kibana|logstash|index|shard)\b", text):
        tags.append("elasticsearch")
    if ap.get("nac_components") and re.search(r"\b(centerd|sensor|policy|agent)\b", text):
        tags.append("nac-component")
    # 중복 제거
    seen = set(); dedup = []
    for t in tags:
        if t not in seen:
            seen.add(t); dedup.append(t)
    # 제한
    max_tags = (rules_cfg.get("limits") or {}).get("max_tags_per_doc", 8)
    return dedup[:max_tags]

def decide_category(filename, content, rules_cfg):
    text = (filename + "\n" + content).lower()
    best = ("Uncategorized", ["미분류","초안"], 0)
    for cat in (rules_cfg.get("categories") or []):
        kws = [k.lower() for k in cat.get("keywords", [])]
        score = sum(1 for k in kws if k in text)
        if score > best[2]:
            best = (cat.get("name","Uncategorized"), cat.get("notion_category",["미분류","초안"]), score)
    return best[0], best[1]

# ---------- 섹션 자동 추출(라이트 버전) ----------
SECTION_HINTS = {
    "summary": ["요약", "상황 요약", "개요", "Summary", "What happened"],
    "root":    ["원인", "Root cause", "원인 분석"],
    "action":  ["조치", "해결", "Action", "조치 방안", "해결 방법"],
    "prevent": ["재발", "예방", "운영", "SOP", "Prevention", "운영 가이드"],
}

def split_sections(raw: str):
    lines = raw.splitlines()
    # 라인단위로 헤더 비슷한 것 감지
    buckets = {"summary": [], "root": [], "action": [], "prevent": []}
    current = None
    for ln in lines:
        ln_strip = ln.strip().lstrip("#").strip()
        hit = None
        for key, hints in SECTION_HINTS.items():
            if any(h.lower() in ln_strip.lower() for h in hints):
                hit = key; break
        if hit:
            current = hit
            continue
        if current:
            buckets[current].append(ln)
    # Fallback: 아무 섹션도 못찾으면 앞쪽 3~6줄을 요약에 담음
    if not any(buckets.values()):
        head = "\n".join(lines[:6]).strip()
        buckets["summary"] = [head] if head else []
    return (
        "\n".join(buckets["summary"]).strip(),
        "\n".join(buckets["root"]).strip(),
        "\n".join(buckets["action"]).strip(),
        "\n".join(buckets["prevent"]).strip(),
    )

# ---------- 메인 ----------
def main():
    p = argparse.ArgumentParser(description="TXT → Markdown 자동 변환기 (양식/요약/태깅/마스킹)")
    p.add_argument("--src_dir", required=True)
    p.add_argument("--out_dir", required=True)
    p.add_argument("--customers", required=True)
    p.add_argument("--rules", required=True)
    p.add_argument("--template", required=True)
    p.add_argument("--mask", action="store_true")
    p.add_argument("--dry_run", action="store_true")
    args = p.parse_args()

    args.src_dir = expand(args.src_dir)
    args.out_dir = expand(args.out_dir)

    if not os.path.isdir(args.src_dir):
        print(f"[ERROR] src_dir not found: {args.src_dir}", file=sys.stderr)
        sys.exit(2)

    customers_cfg = load_yaml(args.customers)
    rules_cfg = load_yaml(args.rules)
    template = read(args.template)

    # 민감어 수집
    sensitive_terms = collect_sensitive_names(customers_cfg)
    today = date.today().isoformat()

    # 소스 스캔
    txts = []
    for root, _, files in os.walk(args.src_dir):
        for fn in files:
            if fn.lower().endswith(".txt"):
                txts.append(os.path.join(root, fn))
    if not txts:
        print(f"[ERROR] No .txt files found under: {args.src_dir}", file=sys.stderr)
        sys.exit(3)

    converted = 0
    for src in txts:
        raw = read(src)
        title = os.path.splitext(os.path.basename(src))[0]
        body_for_rules = raw

        if args.mask:
            title_masked = mask_text(title, sensitive_terms)
            raw_masked = mask_text(raw, sensitive_terms)
        else:
            title_masked = title
            raw_masked = raw

        # 태그/카테고리
        tags = apply_tagging_rules(title_masked, raw_masked, rules_cfg)
        storage_category, notion_category = decide_category(title_masked, raw_masked, rules_cfg)

        # 섹션 추출
        summary, root_cause, actions, prevention = split_sections(raw_masked)

        ctx = {
            "title": title_masked,
            "category_json": json_list(notion_category),
            "tags_json": json_list(tags),
            "date": today,
            "source_file": os.path.basename(src),
            "storage_category": storage_category,
            "summary": summary,
            "root_cause": root_cause,
            "actions": actions,
            "prevention": prevention,
            "raw_body": raw_masked
        }

        rel_md = os.path.relpath(src, args.src_dir)
        rel_md = re.sub(r"\.[^.]+$", ".md", rel_md)
        out_path = os.path.join(args.out_dir, storage_category, rel_md)

        if args.dry_run:
            print(f"[DRY] {src} -> {out_path}")
            continue

        write(out_path, render_template(template, ctx))
        print(f"변환 완료 → {out_path}")
        converted += 1

    print(f"\n완료: TXT → MD 변환이 끝났습니다. 생성 {converted}개.")

if __name__ == "__main__":
    main()
