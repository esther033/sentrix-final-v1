# SentriX — 프로젝트 컨텍스트 (현재 기준)

기준일: 2026-10-19
상태: **이 문서가 프로젝트의 단일 기준 문서다.** 다른 문서와 충돌하면 이 문서를 따른다.
진행 상황과 남은 일: [`docs/MILESTONES.md`](docs/MILESTONES.md)
학교 PC 실측 기록(근거 원본): [`docs/SETUP-REVIEW-20261016.md`](docs/SETUP-REVIEW-20261016.md) 7절
이전 문서: `docs/PROJECT-DIRECTION.md`(2026-10-16 방향 결정, 이 문서로 흡수), `docs/archive/sentrix-project-context-legacy-m1.md`(Windows 시절 M1 설계·구현 기록). 코드 주석에 나오는 "sentrix-project-context.md section N"은 이 보관 문서의 절 번호다.

---

## 1. 프로젝트 정의

SentriX는 Kubernetes 위의 마이크로서비스에서 이상을 탐지하고, **어느 서비스 또는 어느 서비스 간 연결이 원인인지 후보 순위를 근거와 함께 제시하는** observability 기반 RCA(Root Cause Analysis) 시스템이다. 졸업작품이다.

시스템이 답해야 하는 질문:

1. 이상이 발생했는가? (impact detection)
2. 원인은 어느 **서비스(node)** 또는 **서비스 간 방향 있는 연결(edge)** 인가? (node/edge ranking)
3. 어떤 종류의 장애인가? (fault type, 보조 과제)
4. 원인 후보의 순위와 근거는? (Top-k + 점수 + evidence)

데모 출력 예:

```
ANOMALY (user impact confirmed)

Root cause candidates
  1. edge frontend -> productcatalogservice   network_delay   0.84
  2. productcatalogservice                    cpu_saturation  0.41
  3. recommendationservice                    cpu_saturation  0.22
Evidence
  - frontend->productcatalogservice span p90 +180 ms vs local baseline
  - productcatalogservice CPU/throttling unchanged
```

## 2. 확정된 결정

| 날짜 | 결정 | 이유 |
|---|---|---|
| 10/16 | 대상 앱을 **Online Boutique(OB) v0.9.0 하나로 통일** (개발 데이터, 자체 수집, 최종 데모). Sock Shop on EKS 계획 폐기 | RE2-OB와 같은 앱이라 서비스 이름·호출 그래프·계측이 같음. RCAEval 공식 README 기준 RE2-SS(Sock Shop)는 trace가 없음. 기존 수집 파이프라인이 OB 기준 |
| 10/16 | 실행 환경은 **학교 실습 Linux PC 1대 + k3s(containerd)**. EKS는 선택 사항(비용 승인 시 배포 시연만, 데이터는 별도 cohort) | 비용·운영 부담. 핵심 주장(RCA 성능)에 클라우드가 필요 없음 |
| 10/16 | 원인 위치는 **고정 서비스 분류가 아니라 공유 가중치 node/edge ranking** | 미관측 서비스로 일반화 가능, 서비스 이름 암기 방지 |
| 10/16~19 | **원래 계획 69 fault case + 69 matched control(138 run) 유지.** 빠른 수집안(연속 에피소드, 45 case, 약 5시간)은 채택하지 않음 | 독립 control, 회복 라벨, 5종 장애를 모두 확보하기 위해 |
| 10/16 | 수집 PC를 205-13에서 **206-40으로 변경** | 자리 이동. 206-40은 디스크 여유 847 GiB로 저장 문제가 없음 |
| 10/16 | 실행은 **하루 블록 운영 + tier 순서**(Tier 1 cpu·delay·loss 45 → Tier 2 pod 15 → Tier 3 surge 9). 각 tier 안에서는 seed로 섞인 순서 | 재부팅이 잦은 공용 PC에서 중간에 끊겨도 완성된 tier는 3-fold CV 가능한 데이터로 남도록 |
| 10/16 | RAM 15 GiB에 맞춰 관측 스택 축소: 보존 12h, Prometheus 2Gi / Tempo 3Gi / Loki 1Gi limit, Loki 결과 캐시·rules sidecar·Chaos DNS 서버 끔 | 앱 서비스 limit(실험 조건)은 건드리지 않음 |
| 10/19 | **처리 용량 C = 6 tx/s**, 평소 부하 0.4C = **2.4 tx/s**, surge 3.6 / 4.8 / 6.0 tx/s | capacity sweep 실측(8 tx/s에서 p99 545 ms로 FAIL) |
| 10/19 | 시험 pair를 2개가 아니라 **4개(cpu, delay, loss, pod)** 로 진행, Tempo limit 4Gi로 상향 예정 | loss 측정값 ±3 %p 흔들림, pod 효과 약 30초 지연, 8 tx/s에서 Tempo 78 % |

## 3. 데이터 전략

| 데이터 | 역할 | 상태 |
|---|---|---|
| **RE2-OB** (RCAEval, 90 case = 5 서비스 × cpu/mem/disk/delay/loss/socket × 3회, metrics·logs·traces) | 방법 개발, baseline 비교, 교차 데이터 평가 | 다운로드·inventory 도구 준비됨(`rcaeval/`), **아직 받지 않음** |
| **linux-v1 자체 수집** (69 fault + 69 control) | SentriX 주 평가, 영향·회복 라벨, 데모와 같은 환경 | 셋업·검증 완료, 시험 pair 진행 중 |
| RE2-TT | 선택: 고차원 metric 환경 외부 테스트 | 미정 |
| RE2-SS | 선택: 다른 시스템 일반화(metrics+logs만) | 미정 |
| legacy-m2 (Windows, 6 run) | 파이프라인 회귀 확인용 | 보존. linux-v1과 합치지 않음 |
| calib-linux-v1 (capacity·시험 run) | 교정 근거 | 학습 데이터에 넣지 않음 |

원칙: window 수와 독립 case 수를 혼동하지 않는다. 두 데이터 lane을 합쳐 case 수를 부풀리지 않는다. 결합 학습은 5절의 매핑을 고정한 뒤 별도 실험으로만 한다.

RE2-OB ↔ linux-v1 공통 표현:

| 차이 | 규칙 |
|---|---|
| 서비스 이름 | `identity/service-alias-map.yaml`로 canonical id 매핑, 안 되면 오류 |
| sampling | 모델 입력은 30 s window / 10 s stride 통계량으로 통일, window당 실제 표본 수와 mask 기록 |
| 공통 fault | cpu, delay, loss만. pod·surge(linux-v1 전용), mem·disk·socket(RE2 전용)은 억지로 매핑하지 않음 |
| 라벨 단위 | RE2는 서비스, linux-v1의 delay/loss는 edge. 교차 평가 시 edge → 서비스 규칙을 사전에 고정(출발 서비스 기준과 도착 서비스 기준을 모두 보고: 5개 edge 중 3개가 frontend 출발이라 한쪽만 보면 편향) |

## 4. 수집 환경 (학교 PC 206-40)

| 항목 | 값 |
|---|---|
| OS / 커널 | Ubuntu 24.04.5, 커널 7.0.0-31 (7.0.0-38 업데이트 설치됨, 재부팅 후 적용 예정) |
| CPU / RAM | i7-13700 24 vCPU / 15 GiB + swap 4 GiB |
| 디스크 | HDD 931 GiB, LVM ext4 단일 파티션(`/`, `/var`, `/home` 공유), 여유 약 829 GiB. NVMe는 Windows라 사용 금지 |
| 특성 | 공용 실습 PC, Windows 듀얼부트, 부팅 직후 시계 +9h(RTC가 UTC 모드) → NTP 동기화 전 수집 금지. 47일 동안 부팅 18회, Linux 최장 연속 가동 약 3.7일 |
| k3s | v1.33.4+k3s1, containerd 2.0.5-k3s2, traefik·servicelb 끔, swap 허용 |
| 도구 | helm v3.17.3, k6 v0.57.0, Python 3.12.3 (.venv: PyYAML 6.0.2, pandas 2.2.3, pyarrow 18.1.0) |
| 차트 | Loki 7.3.0, Tempo 1.24.4, Prometheus 29.30.0, OTel Collector 0.173.1, Chaos Mesh 2.7.2 (`linux/charts/`에 digest 확인 후 캐시) |
| 엔드포인트 | frontend :30080, Prometheus :30090, Tempo :30320, Loki :30310 (NodePort, port-forward 불필요) |
| scrape | 5초, 보존 12h |
| git | 저장소 `seNNTRIX/sentrix-collection`(비공개, 옛 `esther033/sentrix-final-v1`), 학교 PC 작업 브랜치 `school-pc`, 단계마다 commit·push |

## 5. 실험 프로토콜

run 하나 = 25분(1500초):

| 구간 | 길이 | fault run | control run |
|---|---|---|---|
| warmup | 3분 | 정상 부하 | 정상 부하 |
| baseline | 4~9분 | 정상 부하 | 정상 부하 |
| intervention | 5분 | 장애 주입 | 가짜 구간(장애 없음) |
| recovery | 6~11분 | 장애 제거 후 관찰 | 정상 부하 |
| cooldown | 2분 | 정상 부하 | 정상 부하 |

- 장애 시작(onset)은 7·8·9·10·11·12분 중 하나. 같은 셀의 3회 반복은 서로 다른 onset. matched control은 같은 onset과 phase 길이.
- pair = fault run + 독립 matched control, 같은 workload seed, 연속 수집. pair 순서는 셀마다 2:1/1:2로 섞고 전체 34:35.
- fault-first pair는 control이 끝난 뒤 `scripts/evaluate-pair.py`가 같은 매칭 규칙(workload 키, phase rate, 환경 fingerprint, control 유효성, 2시간)을 적용.
- 사용자 부하: k6 constant arrival rate, 0.4C = 2.4 tx/s. 거래 = 홈 → 상품 → 장바구니 담기 → 장바구니 보기 → 결제.
- 장애 강도 초안: CPU worker 1 · load 100 %, delay 100 ms ± 10 ms, loss 2 %, pod-failure 300초. **시험 pair 결과로 확정 예정.**
- run 시작 전 게이트: NTP 동기화, 모든 Pod Ready, Chaos 잔류 없음, 디스크 여유 ≥ 20 GiB. run마다 boot_id 기록.

## 6. 캠페인 구성 (linux-v1)

| fault | 원인 위치 | 대상 5개 | 반복 | case |
|---|---|---|---|---|
| cpu_saturation | 서비스 | checkoutservice, productcatalogservice, currencyservice, recommendationservice, paymentservice | 3 | 15 |
| pod_failure | 서비스 | 위와 같음 | 3 | 15 |
| network_delay | edge | frontend→productcatalog, frontend→currency, frontend→recommendation, recommendation→productcatalog, checkout→payment | 3 | 15 |
| packet_loss | edge | 위와 같음 | 3 | 15 |
| traffic_surge | 입구(frontend) | L1 3.6 / L2 4.8 / L3 6.0 tx/s | 3 | 9 |
| **합계** | | | | **69 pair = 138 run** |

ID 규칙: fault run / pair `linux-v1-<cpu|pod|delay|loss|surge>-<대상>-r0N`, control `linux-v1-control-…`. 시험 pair는 `calib-linux-v1-…`.

실행 tier:

| tier | fault | pair | 순수 시간(pair당 약 95분) |
|---|---|---|---|
| 1 | cpu, delay, loss | 45 | 약 71시간 |
| 2 | pod_failure | 15 | 약 24시간 |
| 3 | traffic_surge | 9 | 약 14시간 |

## 7. 데이터 구조

run 하나(`runs/<run-id>/`):

| 파일 | 내용 | 모델 입력 |
|---|---|---|
| `run-manifest.yaml` | 환경·버전·image digest·profile·host(boot_id, NTP) | 아니오 |
| `fault-record.json`, `injected-manifest.yaml`, `fault-polls/` | 장애 요청·주입·제거 시각, 대상(edge는 source/destination Pod UID), Chaos 상태 | 아니오 (정답·QA) |
| `transaction-results.jsonl`, `workload-timeseries.json` | 사용자 요청 단위 결과, 초당 계획·완료·dropped | 라벨 계산용 |
| `environment-before/after.json`, `quality-report.json`, `run-assessment-v2.json`, `runtime.json`, `pair-assessment.json` | 환경 fingerprint, 품질 판정 | 아니오 |
| `raw-v2/` | Prometheus·Tempo·Loki·이벤트 원본 | 아니오 (증거) |
| `canonical-v2-*/` | metrics / traces / logs / events parquet | 예 (feature 원천) |
| `re2-v2-*/` | RE2-OB 형식 변환본 | 비교용 |
| `pipeline-v2.json` | 최신 view 경로와 해시 | — |

실측: 25분 0.4C run 약 2.5 GiB(그중 `raw-v2/_export` 체크포인트가 약 49 %), 후처리 약 20분. 138 run 약 344 GiB.

캠페인 단위(`datasets/linux-v1/`, **아직 구현 전**): `cases.parquet`, `topology.json`(trace에서 관측된 그래프), `model-v1-<hash>/`(windows, metric-mask, trace-edges, build-summary), fold index.

## 8. 라벨·feature·누수 규칙

계약 문서: `campaigns/linux-v1/feature-schema.yaml`, `label-schema.yaml`.

- case 판정: `data_valid`, `injection_valid`(Chaos 상태가 아니라 실제 효과로 판정), `impact_confirmed`(사용자 성공률 5 %p 하락 또는 p99 3배), `recovery_status`.
- 영향 없는 case(no-impact)는 버리지 않고 별도 그룹. 탐지 positive와 원인 위치 학습에서는 제외.
- window: 30 s / 10 s stride, 경계에 걸친 window·warmup·주입 전환·회복 중 구간은 제외. 장애 시작은 요청 시각이 아니라 **효과 관측 시각**(pod-failure는 Ready=false 관측 시각, 최대 수십 초 지연).
- node feature: CPU/limit, throttling, 메모리/limit, 요청률, 오류율, 지연 p50/p90(p99 선택), Ready 비율, 재시작. edge feature: 호출률, 오류율, 지연 p50/p90. p90은 span 20개, p99는 100개 미만이면 null + mask.
- 정규화: 같은 run baseline의 중앙값·IQR로 변화량(미래 데이터 금지), 전체 scaler는 fold별 train에서만 fit.
- **모델 입력 금지**: 서비스 이름·ID, Pod/컨테이너 ID, run·pair ID, 반복·fold 번호, 절대 시각, 경과 시간, phase 이름, onset, Chaos·qdisc 상태와 QA 파일. 로그는 서비스명·Pod명·endpoint 제거.
- trace 미계측 4개 서비스(adservice, cartservice, shippingservice, redis-cart)는 mask로 표시, 0으로 채우지 않음.

## 9. RCA 정식화와 평가

- 주 모델: 공유 가중치 node/edge 스코어러. 비교: 통계 threshold, 빈도 prior, random, RF/GBDT, joint classification(`서비스 × fault`) baseline.
- 데모 구조: Stage 1 impact detection → Stage 2 node/edge ranking → Stage 3 fault type.
- 분할: 반복 기준 3-fold(pair와 그 window는 같은 fold). 매 fold 테스트 23 case(Tier 1만이면 15).
- 일반화: leave-one-service-out(cpu, pod), leave-one-edge-out(delay, loss).
- 지표: detection AUROC·AUPRC·고정 FPR sensitivity·탐지 지연·시간당 오탐, ranking Hit@1·Hit@3·MRR·Avg@5, fault type macro-F1. **AC@k/Avg@k 정의는 RCAEval 논문 본문에서 확인 후 구현**(공식 README에는 정의 없음).
- 신뢰구간: case 또는 pair 단위 bootstrap. window 단위 금지. 하이퍼파라미터는 CV 결과를 보기 전에 RE2-OB 또는 pilot으로 고정.

## 10. 시스템 아키텍처 (데모)

```
Online Boutique (k3s, namespace sentrix)  <-- k6 사용자 거래, Chaos Mesh 장애
        |
OTel Collector -> Tempo (traces), Loki (logs)
Prometheus (cAdvisor, kube-state-metrics, spanmetrics)
        |
sentrix-core  : Prometheus/Tempo/Loki query -> 30 s window -> node/edge feature
        |
model-server  : FastAPI. detection score + node/edge ranking + fault type
        |
diagnosis 저장 -> dashboard API -> dashboard (topology, 후보 순위, 근거)
```

## 11. 저장소 구조

현재(수집 단계):

```
deploy/        앱·관측 스택·Chaos Mesh 설정 (원본 + linux overlay)
linux/         설치·검증·capability·캠페인 운영 스크립트, values overlay, charts 캐시(gitignore), out/(증거, gitignore)
campaigns/     linux-v1 계획·feature·label·실행 계약, fault-params, 생성된 schedule
workload/      k6 스크립트, profile
recorder/      k6 → transaction 기록
scripts/       run 실행·pair·캠페인 queue·export·canonical·RE2 projection·평가
smoke/, identity/, incidents/, tests/
rcaeval/       RE2 다운로드·inventory
runs/          수집 결과 (gitignore)
docs/          설계·실측 기록·마일스톤
```

목표(`sentrix_final` 최종): 위 수집 코드를 `collection/`으로 두고 `datasets/`, `features/`(연구와 sentrix-core가 같은 코드 사용), `experiments/`, `evaluation/`, `models/`, `model-server/`, `sentrix-core/`, `dashboard/` 추가.

## 12. 운영 규칙

- 단계별 진행. 학교 PC의 Claude CLI에는 한 단계 프롬프트만 주고, 결과를 확인한 뒤 다음 단계로.
- sudo 명령은 사람이 직접 실행(일반 터미널, 또는 Claude 입력창에서 `!`). root 소유 경로에 에이전트가 쓰지 않음.
- runs/·audits/ 덮어쓰기·삭제 금지, run ID 재사용 금지. 실패 pair는 새 attempt ID로 재시도하거나 decisions.yaml에 제외 기록.
- 판정 기준은 결과를 보고 바꾸지 않음(capacity p99 500 ms, capability judge, impact 기준).
- 수집 블록: 시작 전 점검(마지막 부팅, NTP, Pod Ready, Chaos 잔류, 디스크) → `linux/campaign/start.sh <tier fault-type> --stop-before HH:MM` → 종료 시 `stop.sh`, 보고. 재부팅 시 Ubuntu로 부팅하고 NTP 확인 후 재개.
- 측정 중에는 브라우저로 Online Boutique를 열지 않음(트래픽 오염).
- 장시간 작업은 tmux 안에서, 로그아웃 대신 화면 잠금. 자리를 떠날 때 공용 PC 보안(`gh auth logout`, Claude `/logout` 또는 화면 잠금).
- 커널 업데이트 등 재부팅 대기는 수집 블록 시작 전에 처리.

## 13. 주요 실측값

| 항목 | 값 |
|---|---|
| capability | CPU 0.4999 core(limit 0.5) + throttling, delay +100 ms(다른 경로 영향 0.02 ms), loss 8.7~11.3 %(설정 10 %, 다른 경로 0 %), pod Ready false→true·UID 동일·효과 약 31초 지연 |
| capacity | 1·2·3·4 tx/s p99 124~156 ms, 6 tx/s p50 133 / p99 326 ms, 8 tx/s p99 545 ms(FAIL). 4~6 tx/s 사이에서 지연이 꺾임 |
| 메모리 | 유휴 노드 6.5 GiB 사용 / available 9.4 GiB. sweep 중 최대 9.96 GiB, available 최저 6.6 GiB, swap 최대 89 MiB, Tempo 최대 2403 Mi(3Gi의 78 %), OOM 0 |
| run 크기 | 10분 run 기준 1 tx/s당 약 410 MiB. 25분 0.4C run 약 2.5 GiB, 후처리 약 20분 |
| 일정 | pair 약 95분, 69 pair 순수 약 109시간, 8 h 블록 14회 / 10 h 블록 12회 |

## 14. 위험과 한계

| 위험 | 대응 |
|---|---|
| 공용 PC 재부팅·Windows 부팅·자동 커널 업데이트 | 블록 운영, tier 순서, 미완료 pair 재시도. 관리자에게 약 3주 사용 확보·업데이트 보류 요청 |
| 시계 +9h | NTP 게이트, boot_id 기록 |
| RAM 15 GiB | 관측 스택 축소, Tempo 4Gi 예정, 시험 pair에서 OOM 확인 |
| 영향 없는 case 증가(특히 결제 단계 대상) | 시험 pair로 강도 교정, no-impact는 별도 보고 |
| 네트워크 불안정(GitHub release, Claude API) | 차트 캐시, 측정은 tmux 안에서 |
| tier와 수집 날짜 겹침 | matched control이 같은 날 수집되어 일부 상쇄, 한계로 기록 |
| 단일 PC에서 앱·관측 스택 자원 공유 | 실제 운영 환경을 그대로 대표하지 않음을 한계로 기록 |
| 데이터셋 한계 | mem·disk·socket 장애 없음, 장애 강도 1개, 복합 장애·배포 변경 없음, 장기 정상 데이터 없음 |

## 15. 열린 결정

- 시험 pair 결과에 따른 장애 강도·surge 수준 확정
- EKS 배포 시연 여부(비용 승인 필요)
- RE2-TT / RE2-SS 실험 포함 여부
- 공개 저장소 시점과 범위(내부 정보·개인 경로 정리 후 새 공개 저장소로)
- 관리자 요청: 약 3주 자리 확보, 자동 커널 업데이트 보류, (선택) VPN·SSH 원격 접속
