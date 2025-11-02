All notable changes will be documented here.

## v0.2.0 (2025-11-02)

### 🚀 Major Update – LLM 보조 요약 기능 통합
- OpenAI API 기반 LLM Summarizer 추가 (`src/llm_summarizer.py`)
- configs/llm_config.yaml 추가 (모델, timeout, redaction 설정)
- tagging_rules.yaml 리뉴얼 (v0.1.2)
- 자동 섹션 추출: 상황요약 / 원인분석 / 조치 / 재발방지
- 고객사명, IP, MAC, OS 명칭 마스킹 강화
- templates 구조 Notion/Obsidian 통합 유지
- 신규 명령행 옵션: `--llm`, `--llm-config`