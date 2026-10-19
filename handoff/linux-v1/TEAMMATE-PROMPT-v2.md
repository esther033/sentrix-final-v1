# Linux 머신의 코딩 에이전트에게 붙여 넣을 프롬프트 (v2)

> 이 패키지는 2026-10-14 버전(v1)에 오프라인 보완을 더한 것이다. 원래 지시는 `TEAMMATE-PROMPT.md`에 그대로 있고, 아래는 **이미 끝난 것과 남은 것**을 구분한 갱신본이다. 충돌하면 이 문서를 따른다.

---

SentriX `linux-v1` 데이터셋을 이 Linux 머신에서 수집할 수 있게 세팅해줘. 현재 디렉터리가 패키지 루트다.

먼저 읽기: `sentrix-project-context.md`(현재 기준, 대상은 Online Boutique 하나) → `docs/MILESTONES.md` → `docs/SETUP-REVIEW-20261016.md` → `linux/README.md` → `handoff/linux-v1/ACCEPTANCE.md` → `campaigns/linux-v1/*.yaml`.

## 규칙

- 외부 클라우드 자원 생성·비용 발생 작업 금지. 기존 run/audit 덮어쓰기·삭제 금지. run ID 재사용 금지.
- sudo가 필요한 단계(`linux/01-install-k3s.sh`)는 실행 전에 무엇을 바꾸는지 사람에게 보여주고 승인받는다.
- 실행하지 않은 항목을 통과로 보고하지 않는다. dry-run·YAML parse는 실제 주입 성공이 아니다.
- 138 run 전체 캠페인은 자동 시작하지 않는다.

## 이미 구현된 것 (검증만 하면 됨)

- 엔드포인트 환경변수화 + k3s NodePort (port-forward 불필요): `linux/config/endpoints.env`
- edge fault의 source/destination 치환 버그 수정, 주입 요청 시각·onset·선택된 Pod UID 기록: `scripts/run-attended.py`
- 두 pair order 지원 + fault-first 사후 매칭: `scripts/run-matched-pair.py`, `scripts/evaluate-pair.py`
- 138 profile/schedule 생성기와 테스트: `scripts/generate-campaign.py`, `tests/test_campaign_schedule.py`
- seed 기반 상품 선택: `workload/k6/browse-cart-checkout.js`
- throttling/quota/limit/readiness/restart/drop/telemetry-health metric export: `scripts/telemetry_export.py`
- 재개 가능한 캠페인 queue, tmux 래퍼, 비상 정리: `scripts/run-campaign.py`, `linux/campaign/`
- 설치·검증·capability·capacity 스크립트: `linux/0*.sh`, `linux/capability/`, `scripts/capacity-sweep.py`

## 해야 할 것 (순서대로, 각 단계 증거 경로를 남길 것)

1. `bash linux/00-preflight.sh` 결과를 요약해 보고하고, FAIL 항목이 있으면 진행 여부를 묻는다.
2. `linux/README.md` 2~3절 설치·배포·검증. 실패하면 원인을 고치고 고친 내용을 문서에 남긴다(예: chart key가 다르면 overlay 수정).
3. `linux/capability/run-all.sh` 전부 PASS.
4. `scripts/capacity-sweep.py`로 C 측정 → 판정 근거 보고.
5. calibration schedule(`--campaign-id calib-linux-v1`)로 CPU 1 pair, delay 1 pair 시험 수집. 각 run의 `pipeline-v2.json complete`, `run-assessment-v2.json`, `fault-record.json`(source/destination Pod UID, AllInjected/AllRecovered), `pair-assessment.json`(fault-first인 경우) 확인.
6. 시험 결과로 fault 강도를 제안하고, **사람의 승인 후** `fault-params.yaml`을 frozen으로 바꾸고 정식 schedule 생성(seed 기록).
7. 남은 구현 (`docs/SETUP-REVIEW-20261016.md` 5절): 앱 edge qdisc/counter 실측 수집기, window 라벨 생성기, `cases.parquet`·fold index·topology·model view, 로그 sanitization. 각 기능에 의미 있는 테스트를 추가한다.
8. `ACCEPTANCE.md` 양식으로 보고: 한 pair 실행 명령, 전체 실행 명령(`linux/campaign/start.sh`), 예상 시간·저장량, 시작 가능 여부와 근거.
