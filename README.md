# 🪄 txt2notion

> **Automated TXT → Markdown converter optimized for Obsidian and Notion**

`txt2notion`은 로컬/클라우드에 보관된 `.txt` 문서를
**Obsidian Vault** 및 **Notion Database** 형식으로 자동 변환·정리하는 Python 도구입니다.  
보안 로그, 기술 메모, 이슈 정리 문서 등을 자동으로 마크다운화하여 검색과 관리 효율을 극대화합니다.

---

## ✨ 주요 기능

| 범주 | 설명 |
|------|------|
| 🔄 TXT → MD 자동 변환 | Front Matter + 템플릿을 적용한 Markdown 생성 |
| 🧩 태그·카테고리 자동 분류 | `tagging_rules.yaml` 기반 문맥 분류 |
| 🕶️ 민감정보 마스킹 | 고객사명 · IP · MAC 주소 자동 익명화 |
| 🧠 대화 로그 요약 (옵션) | Slack/메일 패턴 감지 후 TL;DR · 불릿 요약 작성 |
| 🧱 Obsidian Vault 통합 | Vault 내 `converted_md/` 에 자동 출력 |
| ☁️ (선택) Notion 업로드 | API 키 연동 시 Notion DB로 자동 푸시 |

---

## 🧰 요구 환경

- macOS / Linux / Windows
- Python 3.9 +
- pip 패키지  
  ```bash
  pip install pyyaml requests

---

## ⚡ 빠른 시작

# 가상환경 생성
python3 -m venv .venv && source .venv/bin/activate

# 패키지 설치
pip install pyyaml requests

# 변환 실행
python src/main.py \
  --src_dir "$HOME/Library/CloudStorage/GoogleDrive-<계정>/내 드라이브/bjw-hub/work-docs/txt_raw" \
  --out_dir "$HOME/Desktop/bjw-hub/work-docs/txt2notion_vault/converted_md" \
  --customers "./configs/customers.yaml" \
  --rules "./configs/tagging_rules.yaml" \
  --template "./templates/template.md.tpl" \
  --mask

📂 Obsidian Vault 경로: ~/Desktop/bjw-hub/work-docs/txt2notion_vault
변환 후 Vault를 열면 converted_md/ 에 바로 문서가 생깁니다.