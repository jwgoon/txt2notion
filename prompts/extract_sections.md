입력: 원문 텍스트
목표: 아래 JSON 스키마를 충족하도록 핵심만 요약/구조화.

스키마:
{
  "title": "string",
  "summary_tldr": "string",
  "summary": "string",
  "root_cause": "string",
  "actions": "string",
  "prevention": "string",
  "tags": ["string"],
  "category": ["string"]
}

요청:
1) 한 줄 TL;DR (대상/증상/영향/상태) + 3~5줄 요약
2) 근거 기반 원인(불확실하면 빈 문자열)
3) 명령형 조치(코드블록 유지)
4) 측정 가능한 재발방지(임계치/주기/알람/가이드)
5) tags/category는 3~5개 이내(과도 생성 금지)

제한:
- JSON 외 텍스트 금지
- 일반론 나열 금지, 원문 근거 우선

규칙:
1. 한 줄 TL;DR 요약 (무엇이, 어디서, 어떤 증상, 현재 상태)
2. 상황요약(summary): 3~5줄로 핵심 흐름 기술.
3. 원인(root_cause): 실제 로그/조건 기반 원인, 추정은 "추정" 명시.
4. 조치(actions): 명령형 불릿 또는 코드블록 형태로 기술.
5. 재발방지(prevention): 주기/임계치/가이드/정책 등 실행 가능한 개선안.
6. tags/category: 기술/시스템 단위로 3~5개 내외.
7. 섹션 내용이 없으면 빈 문자열("")로 반환.
8. JSON 외 텍스트는 절대 포함하지 마세요.