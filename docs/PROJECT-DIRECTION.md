# SentriX Final — 통합 방향 및 계획 (Online Boutique 단일 대상)

결정일: 2026-10-16
> **2026-10-19:** 이 문서의 내용은 루트 [`sentrix-project-context.md`](../sentrix-project-context.md)로 흡수됐다. 특히 10절 계획(축소안 포함)은 더 이상 유효하지 않다. 현재 계획은 [`docs/MILESTONES.md`](MILESTONES.md).

상태(2026-10-16 당시): **현재 기준 문서.** 팀 내부 브리프("SentriX Final — 프로젝트 컨텍스트 및 개발 방향")와 `sentrix-project-context.md`가 이 문서와 충돌하면 이 문서를 따른다. 두 문서의 원칙(case≠window, leakage 방지, 조사 후 구현, 재현성, 불필요한 복잡성 회피)은 그대로 유지한다.

## 1. 결정

**개발 데이터, 자체 수집, 최종 데모의 대상을 모두 Online Boutique(OB)로 통일한다.**
Sock Shop on AWS EKS를 최종 배포 대상으로 두던 계획은 폐기한다.

| 항목 | 이전 브리프 | 변경 |
|---|---|---|
| 최종 데모 앱 | Sock Shop | Online Boutique v0.9.0 |
| 실행 환경 | AWS EKS | 단일 Linux 머신의 k3s (학교 Linux). EKS는 선택 사항(7절) |
| 개발 데이터 | RE2-OB | RE2-OB (변경 없음) |
| 자체 수집 | Sock Shop 60 case (5 서비스 × CPU/Memory/Delay/Loss × 3) | `linux-v1` 69 fault case + 69 matched control |
| 장애 도구 | stress-ng, tc 직접 사용 | Chaos Mesh (내부적으로 stress-ng, tc/netem 사용) + 주입 효과 실측 |
| 관측 스택 | Prometheus, Grafana, cAdvisor | Prometheus(+cAdvisor, kube-state-metrics), OTel Collector, Tempo(trace), Loki(log) |
| RE2-SS | 실제 환경 검증용 | 선택적 교차 시스템 실험(4절) |

## 2. 근거

1. **Common Representation 문제가 대부분 사라진다.** 브리프 8절이 우려한 차이(service name, metric 의미, topology, telemetry 형식) 중 서비스 이름·호출 그래프·계측 코드가 RE2-OB와 자체 수집에서 같은 앱에서 나온다. 남는 차이는 sampling 주기, metric 이름/단위, 주입 도구, 라벨 단위로 좁혀지고 각각 명시적 규칙으로 다룰 수 있다(5절).
2. **Multi-source를 끝까지 유지할 수 있다.** RCAEval 공식 README 기준 RE2-OB는 metrics·logs·traces를 모두 제공하지만 RE2-SS는 trace가 없다(metrics, logs만). Sock Shop을 최종 대상으로 두면 trace 기반 cross-service feature를 benchmark와 데모 사이에서 이어갈 수 없다.
3. **이미 동작하는 수집 파이프라인이 OB 기준이다.** 배포 manifest, OTLP 계측 패치, k6 transaction, export/canonical/RE2 projection, incident registry가 OB로 구현·검증되어 있다. Sock Shop으로 바꾸면 이를 다시 만들어야 한다.
4. **비용과 운영 위험.** EKS는 비용·계정·장시간 운영 부담이 있고, 졸업작품의 핵심 주장(RCA 성능)에 필요하지 않다.

## 3. 연구 질문 (OB 기준으로 재서술)

시스템은 다음 네 가지에 답한다.

1. 이상이 발생했는가? — window/case 단위 impact detection
2. 원인은 어느 **서비스(node) 또는 의존 edge**인가? — node/edge ranking
3. 어떤 종류의 fault인가? — fault-type 분류(보조)
4. 가능한 원인 후보 순위는? — Top-k 후보와 점수, 근거

데모 출력 예 (OB 서비스 이름):

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

## 4. 데이터셋 역할

| 데이터 | 역할 | 비고 |
|---|---|---|
| **RE2-OB** (90 case = 5 서비스 × cpu/mem/disk/delay/loss/socket × 3) | feature/RCA 방법 개발, baseline 비교, case-level CV | 실제 target 서비스·파일 구조·sampling은 `rcaeval/inventory_re2.py` 결과로 확정 (추측 금지) |
| **linux-v1 자체 수집** (69 fault + 69 control) | SentriX 주 평가, recovery·impact 라벨, 데모와 같은 환경 | case-level rotating 3-fold CV. 독립 case 수는 69로 보고 |
| RE2-TT | 선택: 고차원 metric(340~376) 환경 외부 테스트 | 시간이 남을 때만 |
| RE2-SS | 선택: 다른 시스템으로의 일반화(metrics+logs만) | trace feature 없는 모델 변형으로만 평가 |
| legacy-m2 (Windows, 6 run) | 파이프라인 회귀 확인용 | linux-v1과 합치지 않음 |

두 lane은 합쳐서 case 수를 부풀리지 않는다. 결합 학습은 5절의 매핑을 고정한 뒤 별도 실험으로만 한다.

## 5. RE2-OB ↔ linux-v1 공통 표현

| 차이 | 규칙 |
|---|---|
| 서비스 이름 | `identity/service-alias-map.yaml`로 canonical id에 매핑. 매핑 안 되면 오류 |
| Metric sampling | RE2-OB native 주기 vs Prometheus 5 s scrape. 모델 입력은 30 s window / 10 s stride 통계량으로 통일, window당 실제 표본 수와 mask 기록 |
| Metric 이름·단위 | `docs/RE2_SCHEMA.md`의 projection 규칙. RE2에만 있는 disk I/O·socket 계열은 자체 수집에 없으므로 공통 feature에서 제외 |
| Fault 공통집합 | cpu, delay, loss만 공통. pod_failure·traffic_surge는 RE2에 없고, mem·disk·socket은 linux-v1에 없음. 다른 종류로 억지 매핑하지 않음 |
| 라벨 단위 | RE2는 서비스, linux-v1의 delay/loss는 edge. 교차 평가 시 edge → source 서비스 매핑을 사전에 고정하고, edge 단위 성능은 linux-v1에서만 보고 |
| 주입 도구·강도 | 서로 다름. 교차 데이터 결과는 "다른 주입 조건에서의 일반화"로만 해석 |

## 6. RCA 정식화

- **주 모델: 공유 가중치 node/edge 스코어러(ranking).** 그래프의 모든 서비스 node와 directed edge에 같은 함수로 점수를 매긴다. 서비스 이름·ID는 feature로 쓰지 않는다(`campaigns/linux-v1/feature-schema.yaml` forbidden 목록).
- **Baseline: joint classification** (`service × fault_type` 라벨) — 설명용·비교용. 고정 서비스 class head이므로 미관측 서비스로 일반화하지 못한다는 한계를 함께 보고.
- **Hybrid 파이프라인(데모 구조):** Stage 1 impact detection → Stage 2 node/edge ranking → Stage 3 fault-type 분류(Top 후보에 대해).
- Feature는 required / optional / experimental로 나누고(`feature-schema.yaml`), 추가 feature는 RE2-OB와 linux-v1 fold 결과로 이득이 확인될 때만 채택한다.

## 7. 평가

- Detection: AUROC, AUPRC, 고정 FPR에서의 sensitivity, detection delay — case 단위, no-impact case는 별도 stratum.
- RCA ranking: Hit@1, Hit@3(= AC@1, AC@3), MRR, Avg@5. **AC@k/Avg@k의 정확한 정의는 RCAEval 논문 본문에서 확인 후 구현한다**(공식 README에는 정의가 없음).
- Fault type: macro-F1, balanced accuracy.
- 신뢰구간은 case 또는 matched pair 단위 bootstrap. window 단위 bootstrap 금지.
- Detection과 RCA는 분리 보고. 하이퍼파라미터는 CV 결과를 보기 전에 RE2-OB 또는 pilot으로 고정.

## 8. 시스템 아키텍처 (데모)

```
Online Boutique (k3s, namespace sentrix)  <-- k6 사용자 transaction, Chaos Mesh 장애
        |
OTel Collector -> Tempo (traces), Loki (logs)
Prometheus (cAdvisor, kube-state-metrics, spanmetrics)
        |
sentrix-core   : Prometheus/Tempo/Loki query -> 30 s window -> feature (node/edge)
        |
model-server   : FastAPI. detection score + node/edge ranking + fault type
        |
diagnosis 저장 -> dashboard API -> dashboard (topology, 후보 순위, 근거)
```

EKS는 **선택 사항**이다. 같은 manifest와 Helm values로 올리는 배포 시연만 하고, EKS에서 나온 데이터는 별도 cohort로 두어 linux-v1과 섞지 않는다. 비용 승인이 없으면 하지 않는다.

## 9. 저장소 구조 (`sentrix_final`)

연구 코드와 제품 코드를 분리한다. 현재 수집 패키지는 `collection/`으로 들어간다.

```
sentrix_final/
├── collection/        # 이 패키지: deploy/, linux/, scripts/, workload/, recorder/, smoke/, campaigns/
├── data/              # (git 제외) RE2 원본, linux-v1 runs/ 아카이브 포인터
├── datasets/          # cases.parquet, folds, topology, model view (생성물, 해시 기록)
├── features/          # window/feature 추출 라이브러리 (sentrix-core와 공유)
├── experiments/       # 실험 설정 + 결과 기록 (dataset/feature version, seed, split, metric)
├── evaluation/        # Hit@k, MRR, Avg@5, detection metric, bootstrap
├── models/            # 학습된 모델과 model card
├── model-server/      # FastAPI
├── sentrix-core/      # 실시간 query·windowing·feature·진단 저장
├── dashboard/
└── docs/
```

`features/`를 연구와 sentrix-core가 **같은 코드로** 쓰는 것이 학습-서빙 불일치를 막는 핵심이다.

## 10. 계획 (제안, 2026-10-16 기준 주 단위)

| 주 | 수집 (학교 Linux) | 연구 (병행) | 산출물 |
|---|---|---|---|
| 1 (10/16~) | preflight → k3s·스택 배포 → 05-verify | RE2-OB 다운로드·inventory, Dataset 질문 1~7 답변 | 환경 지문, RE2-OB inventory |
| 2 | capability gate, capacity C, calibration pair 2개, 강도 동결 | RE2-OB window/feature v0, baseline(통계·RF/LightGBM) | 동결 파라미터, baseline 결과 |
| 3~4 | 정식 캠페인 69 pair (순수 86~109 h + 재시도) | node/edge ranking 모델, AC@k 정의 확인·평가기 구현 | linux-v1 raw/canonical |
| 5 | 미완료 pair 재수집 | linux-v1 라벨·cases.parquet·fold, 3-fold CV | 주 평가 결과 |
| 6 | — | sentrix-core + model-server (`features/` 공유) | end-to-end 진단 |
| 7 | 데모 리허설 (live fault) | dashboard | 데모 |
| 8 | — | 보고서, 한계 정리 | 최종 보고서 |

학교 머신이 장시간 실행을 보장하지 못하면(재부팅, 자원 부족) 3~4주차 캠페인 규모를 줄인다. 축소 순서: 반복 3 → 2는 하지 않고(CV 구조가 깨짐) **target 수를 줄인다**(예: 서비스 3개 + edge 3개 → 4 유형 × 3 target × 3 반복 + surge 9 = 45 pair; `campaign-plan.yaml`의 target 목록과 `targets` 수만 바꾸면 생성기가 그대로 균형을 맞춘다). 축소는 캠페인 시작 전에 결정하고 기록한다.

## 11. 브리프에서 무효가 된 항목

- 17절 Sock Shop/EKS 인프라, 초기 대상 서비스(front-end, orders, carts, catalogue, user), 60-case 설계 → 이 문서 1·4절과 `campaigns/linux-v1/`로 대체.
- 6절 "Sock Shop은 최종 배포 환경" → RE2-SS는 선택적 일반화 실험.
- 초기 fault의 Memory → linux-v1에서 제외(injector·효과 metric 미검증). 필요하면 `linux-v2` cohort.
- 그 외 원칙·평가 철학·우선순위(Dashboard 후순위)는 유지.

## 12. 남은 결정

- EKS 배포 시연을 할지 (비용 승인 필요).
- RE2-TT / RE2-SS 실험을 범위에 넣을지 (4주차 진행 상황을 보고 결정 권장).
- 학교 머신 자원이 부족할 때의 캠페인 축소안 (preflight 결과 후).
