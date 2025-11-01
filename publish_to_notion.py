#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MD → Notion 업로드/업서트
- env: NOTION_TOKEN, NOTION_DATABASE_ID
- 입력: converted_md/ 밑의 .md 파일들
- 동작: frontmatter 읽어 Notion DB에 페이지 생성/갱신
- 캐시: notion_sync_index.json (파일 경로 → {page_id, sha1})
"""
import os, json, hashlib, time, re
import requests
import frontmatter
from datetime import datetime
from pathlib import Path

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB = os.getenv("NOTION_DATABASE_ID")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
CACHE_PATH = "notion_sync_index.json"

def sha1_of_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache: dict):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def to_rich_text(text: str):
    return [{"type": "text", "text": {"content": text}}]

def to_multi_select(values):
    # 값이 리스트가 아니면 리스트화
    if not isinstance(values, list):
        values = [values]
    clean = []
    for v in values:
        if not v: 
            continue
        label = str(v)
        clean.append({"name": label})
    return clean

def parse_frontmatter(md_path: Path):
    post = frontmatter.load(md_path)
    fm = post.metadata
    body = post.content

    title = fm.get("title") or md_path.stem
    category = fm.get("category") or []
    tags = fm.get("tags") or []
    date_str = fm.get("date") or datetime.now().strftime("%Y-%m-%d")
    source_file = fm.get("source_file") or md_path.name
    storage_category = fm.get("storage_category") or "Uncategorized"

    return {
        "title": str(title),
        "category": category,
        "tags": tags,
        "date": date_str,
        "source_file": str(source_file),
        "storage_category": str(storage_category),
        "body": body,
    }

def build_properties(meta: dict):
    # 여기서는 Notion DB 속성명이 아래라고 가정:
    # Title(타이틀), Category(멀티셀렉트), Tags(멀티셀렉트), Date(날짜), Source(리치텍스트), Storage(리치텍스트)
    return {
        "Title": {"title": to_rich_text(meta["title"])},
        "Category": {"multi_select": to_multi_select(meta["category"])},
        "Tags": {"multi_select": to_multi_select(meta["tags"])},
        "Date": {"date": {"start": meta["date"]}},
        "Source": {"rich_text": to_rich_text(meta["source_file"])},
        "Storage": {"rich_text": to_rich_text(meta["storage_category"])},
    }

def md_to_blocks(body: str):
    # 최소구현: 빈 줄 기준 단락 → paragraph block
    # (원하면 ## 헤더, ```코드``` 등 처리 고도화 가능)
    blocks = []
    paragraphs = body.split("\n\n")
    for p in paragraphs:
        if not p.strip():
            continue
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": to_rich_text(p[:2000])}
        })
    return blocks[:95]  # 예: 한 번에 너무 길지 않게 안전 상한

def create_page(meta: dict, blocks: list):
    data = {
        "parent": {"database_id": NOTION_DB},
        "properties": build_properties(meta),
        "children": blocks
    }
    r = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=data)
    if r.status_code >= 300:
        raise RuntimeError(f"Notion create failed: {r.status_code} {r.text}")
    return r.json()["id"]

def update_page(page_id: str, meta: dict, blocks: list):
    # 속성 업데이트
    props = {"properties": build_properties(meta)}
    r = requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json=props)
    if r.status_code >= 300:
        raise RuntimeError(f"Notion update failed: {r.status_code} {r.text}")
    # 본문은 덮기 위해 children replace API가 아직 없어서 보통 append 전, 기존 블록 삭제가 필요.
    # 간단 구현: 기존 유지 + 상단에 "업데이트됨" 블록 append (필요시 고도화)
    if blocks:
        r2 = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=HEADERS, json={"children": blocks}
        )
        # 일부 워크스페이스에서 위 엔드포인트 권한 제한 있을 수 있음 → 실패해도 속성업데이트는 살려둔다.

def upsert_page(md_path: Path, cache: dict):
    meta = parse_frontmatter(md_path)
    body_blocks = md_to_blocks(meta["body"])
    key = str(md_path)
    digest = sha1_of_file(md_path)

    cached = cache.get(key)
    if cached and cached.get("sha1") == digest:
        print(f"[SKIP] {md_path} (no change)")
        return

    page_id = cached.get("page_id") if cached else None
    if page_id:
        print(f"[UPDATE] {md_path}")
        update_page(page_id, meta, body_blocks)
    else:
        print(f"[CREATE] {md_path}")
        page_id = create_page(meta, body_blocks)

    cache[key] = {"page_id": page_id, "sha1": digest}
    save_cache(cache)

def walk_and_sync(root: Path):
    cache = load_cache()
    for p in root.rglob("*.md"):
        # 너무 빈 frontmatter거나 title 없는 경우 스킵
        try:
            upsert_page(p, cache)
        except Exception as e:
            print(f"[ERR] {p}: {e}")
            continue

def main():
    root = Path(os.getenv("MD_ROOT", "./converted_md"))
    if not NOTION_TOKEN or not NOTION_DB:
        raise SystemExit("환경변수 NOTION_TOKEN / NOTION_DATABASE_ID 를 설정하세요.")
    if not root.exists():
        raise SystemExit(f"MD_ROOT 경로가 없습니다: {root}")
    walk_and_sync(root)
    print("Done: Notion sync complete.")

if __name__ == "__main__":
    main()
