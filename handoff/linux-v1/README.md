# Linux 데이터 수집 세팅 인수인계

> **2026-10-16 v2 보완판**: Linux 실행은 `linux/README.md`, 프로젝트 방향(Online Boutique 단일 대상)은 `docs/PROJECT-DIRECTION.md`, 보완 내역과 남은 위험은 `docs/SETUP-REVIEW-20261016.md`, 에이전트 지시는 `TEAMMATE-PROMPT-v2.md`를 사용한다. 아래는 v1 원문이다.

작성: 2026-10-14. 이 패키지는 Linux 설치, 수집 코드 보완, 시험 수집 및 본 수집 준비를 위한 소스 스냅샷이다.

## 전달 방법

1. `SentriX-linux-v1-setup-20261014.zip`을 팀원에게 전달한다.
2. 팀원은 Linux 작업 디렉터리에 압축을 풀고 그 디렉터리를 코딩 에이전트의 workspace로 연다.
3. `handoff/linux-v1/TEAMMATE-PROMPT.md` 전체 내용을 에이전트에게 붙여 넣는다.
4. `handoff/linux-v1/ACCEPTANCE.md`를 완료 보고 기준으로 사용한다.

GitHub 주소는 https://github.com/esther033/sentrix_v2 이다. 원격 저장소가 이 패키지의 최신 문서와 일치한다고 가정하지 않는다. 기존 clone에 압축을 덮어쓰지 말고 별도 디렉터리에서 비교한다.

## 패키지에 들어 있는 것

| 경로 | 역할 |
|---|---|
| `handoff/linux-v1/TEAMMATE-PROMPT.md` | 팀원/코딩 에이전트에게 전달할 작업 지시 |
| `handoff/linux-v1/ACCEPTANCE.md` | 세팅 완료 조건과 결과 보고 양식 |
| `campaigns/linux-v1/` | 실험 조합, feature, label, 실행·평가 설계 |
| `docs/` | 전체 설계, 데이터 형식, 기존 결과 해석 |
| `deploy/` | 앱, telemetry, Chaos Mesh 배포 설정 |
| `workload/`, `recorder/` | k6 사용자 트래픽과 transaction 기록 |
| `scripts/`, `smoke/`, `identity/`, `tests/` | 실행·추출·변환·검증 코드 |
| `incidents/` | 기존 incident 형식과 사례 |
| `samples/` | 기존 결과의 소형 Parquet 샘플 |
| `sentrix-project-context.md` | 연구 목적과 시스템 맥락 |

전체 `runs/`, 대용량 `audits/`, `.git`, 인증 정보는 포함하지 않는다. 기존 6 run의 수집량은 `docs/DATA-EXTRACTION-INVENTORY.md`에서 확인한다. 이 패키지만으로 기존 전체 raw 데이터를 재분석할 수는 없다.

## 이번 세팅 작업의 도착점

Linux에서 환경 확인 → 코드 보완 → capability 검증 → 용량 교정 → CPU 및 network 시험 수집 → 138-run 실행 계획 생성까지 완료한다. 본 캠페인 138 run의 장시간 실행은 별도 시작 요청 시 진행한다.

문서에 있는 `2 tx/s`, delay/loss 값은 교정 시작 후보다. 실측 후 고정한 설정, 버전, 이미지 digest, schema와 schedule을 함께 남겨야 한다. 기존 README의 Docker Desktop quick start는 구조 참고용이다.
