# 팀원에게 전달할 프롬프트

SentriX의 `linux-v1` 데이터셋을 수집할 Linux 환경을 세팅해줘. 목표는 실제 모델 학습에 사용할 데이터를 재현 가능하게 수집하는 것이다. 저장소를 읽고 필요한 구현을 끝낸 뒤 CPU/network 시험 수집과 본 캠페인 준비 상태까지 검증해줘.

현재 작업 디렉터리가 전달받은 소스 스냅샷의 루트라고 가정한다. 필요한 VM 접근 정보가 없다면 먼저 로컬에서 가능한 코드 작업과 실행 계획을 완성하고, 실제 배포에 필요한 연결 정보만 질문해줘. 외부 클라우드 자원 생성이나 비용 발생 작업은 범위에 포함하지 않는다. 기존 run을 덮어쓰거나 초기화하지 않는다.

## 먼저 읽을 문서

1. 저장소에 적용되는 `AGENTS.md`가 있으면 우선 읽기.
2. `handoff/linux-v1/README.md`, `handoff/linux-v1/ACCEPTANCE.md`.
3. `docs/LINUX-PRODUCTION-DATASET-DESIGN.md`.
4. `campaigns/linux-v1/{campaign-plan,execution-plan,feature-schema,label-schema}.yaml`.
5. `docs/TELEMETRY_EXPORT.md`, `docs/TELEMETRY_PIPELINE.md`, `docs/RE2_SCHEMA.md`.
6. `docs/DATA-EXTRACTION-INVENTORY.md`, `identity/service-alias-map.yaml`.

설계 문서와 현재 코드 사이의 차이는 아래 구현 작업으로 해결한다. 이 프롬프트의 보정 사항과 충돌하는 기존 설명은 해당 문서 및 schema도 함께 정정하고 근거를 남겨줘.

## 수집 범위

- CPU saturation: 5 services × 3회 = 15 cases.
- Pod failure: 같은 5 services × 3회 = 15 cases.
- Network delay: 5 directed edges × 3회 = 15 cases.
- Packet loss: 같은 5 edges × 3회 = 15 cases.
- Traffic surge: 3 load levels × 3회 = 9 cases.
- 총 69 fault cases와 독립 matched control 69개, 총 138 runs.

서비스: checkoutservice, productcatalogservice, currencyservice, recommendationservice, paymentservice.

Edges: frontend→productcatalogservice, frontend→currencyservice, frontend→recommendationservice, recommendationservice→productcatalogservice, checkoutservice→paymentservice.

장애를 한 곳에 주입해도 관측 데이터는 시스템 전체에서 수집한다. 기존 Windows/Docker Desktop 데이터는 legacy cohort로 보존한다.

## A. Linux 환경과 배포

OS/kernel, CPU/RAM/disk, Kubernetes context, container runtime/socket, CNI, 시간 동기화, 스토리지/PVC를 점검하고 결과를 파일에 남겨줘. 기존 클러스터를 사용하는 경우 대상 context와 namespace를 명시한다.

Ubuntu와 Kubernetes/containerd를 기준으로 앱, Chaos Mesh, Prometheus, Loki, Tempo, OTel Collector, k6를 배치한다. 버전과 이미지 digest를 고정하고 실제 호환성 확인 결과를 저장한다. 기존 Helm values는 Docker Desktop용이므로 Linux용 overlay를 만들고 runtime socket, retention, PVC, resource limit, endpoint를 검증한다. k3s이면 containerd socket이 기존 설정과 다를 수 있으므로 실측한다.

Python 의존성을 코드 import에서 확인해 설치 가능한 requirements/lock 파일과 venv 설치 명령을 작성해줘. CLI 버전도 기록한다. 노트북 세션/수동 port-forward에 의존하지 않는 실행 방식을 만들고 backend URL을 설정으로 주입한다. 기존 built-in loadgenerator는 비활성화 상태를 유지한다.

## B. 수집 코드 구현

1. `scripts/telemetry_export.py`에 CPU quota/limit, throttling, readiness/restart 시계열 및 telemetry health 수집을 추가한다. network 효과 증거 수집기를 구현하고 metric의 단위, 실제 source 주기, query window와 coverage를 기록한다.
2. NetworkChaos는 source/destination/방향/실제 Pod UID와 필터 범위를 기록한다. 전용 probe에서 delay와 loss 모두 적용·실측·제거를 검증한다. `probe-network-pod.py`의 pod-wide 실험을 edge 검증의 대체로 쓰지 않는다.
3. `run-matched-pair.py`와 `run-attended.py`, 평가기를 고쳐 두 실행 순서를 지원한다. fault-first는 control이 아직 없으므로 실행 전 건강성 검증과 최종 pair 평가를 분리하고, control 종료 후 평가한다. 기존 control 매칭 검증을 통째로 제거하지 않는다.
4. onset jitter는 기존 `warmup_seconds + baseline_seconds` 계산을 활용할 수 있다. 저장된 onset과 phase 합을 검증하고 k6 schedule과 실제 injector 시각을 함께 남긴다. 25분 총길이, warmup 3분, intervention 5분, cooldown 2분, onset 7~12분을 유지한다.
5. 138개 profile과 재현 가능한 schedule 생성기를 만든다. seed로 type/target/repetition을 섞고 pair order와 onset을 배정한다. 셀당 반복 3개 및 총 69쌍은 홀수이므로 정확히 반반은 불가능하다. 셀 내 순서 차이는 최대 1, 전체는 34/35가 되도록 균형을 맞춘다. repetition이 날짜와 겹치지 않게 섞는다.
6. workload seed는 profile에 기록하는 것만으로 끝내지 말고 실제 상품 선택/요청 계획에 적용한다. trace/transaction ID는 고유하게 유지한다.
7. fault type뿐 아니라 node/edge/entrypoint scope, 실제 주입 효과, impact/recovery 라벨을 저장한다. 파일명만으로 정답을 추정하지 않는다.
8. 종료/중단 시 fault 제거와 원복 확인, postprocessing 재개, run ID 덮어쓰기 금지를 검증한다.

## C. 모델 데이터와 라벨에서 바로잡을 사항

- 30초 trailing window/10초 stride를 사용한다. native scrape 목표는 5초지만 query 결과를 resample한 행 6개와 독립 raw sample 6개를 혼동하지 않는다. underlying counter의 실제 표본 시각과 rate lookback도 기록한다.
- feature/label YAML은 현재 설계 계약 초안이다. 양성 case 전체 fault 구간을 모든 window의 사용자 영향 positive로 복제하지 않는다. 사용자 transaction의 시간별 오류/지연으로 window impact를 판정하고 injection/effect/impact/recovery 시각을 분리한다. 임계값은 별도 calibration에서 동결한다.
- warmup, 경계와 transient, recovery 잔류 효과를 normal로 잘못 지정하지 않는다. rolling metric의 lookback이 이전 phase를 포함하는지 반영한다. 원본은 모두 보존하고 학습 마스크를 별도 생성한다.
- qdisc/filter와 Chaos 상태는 주입 확인용 privileged evidence다. fault run에서만 생기는 qdisc feature는 primary 모델 입력에서 제외한다. RTT/retransmission을 모델 feature로 쓰려면 control과 fault 모든 후보에 동일하게 관측 가능해야 한다.
- service name/UID/instance/파일경로/run 시각/Chaos 로그/manifest는 모델 feature에 넣지 않는다. 원본 identity는 데이터 결합과 결과 표시용으로 보존한다. 로그에는 서비스명뿐 아니라 endpoint/Pod 이름 등 식별자 우회 경로도 제거한다.
- 기본 트레이싱은 7개 서비스이며 나머지는 modality mask로 표현한다. 관측되지 않은 요청/latency를 0으로 채우지 않는다.
- p90/p99는 표본 수가 부족하면 null+mask로 두고 quantile 산출 정책을 기록한다. 계측 손실과 실제 요청 부재를 구분한다.
- `cases.parquet`와 fold index, topology, model-view 생성기를 만들고 각 feature의 입력 경로를 명시한다. scaler/vocabulary/imputer는 fold별 train 데이터로만 학습한다.
- no-impact case는 보존하고 primary 사용자 장애/RCA positive에서 분리한다. 낮은 surge가 사용자 장애를 만들지 않으면 자동 positive로 부르지 않는다.
- 모델 출력 계약은 공유 node/edge ranking이다. 새 서비스에서 추론할 수 있다는 것과 정확도를 보장한다는 것은 다르다. known topology의 unseen-root LOSO와 그래프에서 노드 자체를 제외하는 truly-unseen-node 평가를 구분한다. 전자는 신규 서비스 추가를 완전히 입증하지 않는다.
- 3-fold CV가 독립 사례 수를 늘려주지는 않는다. 69는 수집 목표이며 impact 조건을 통과한 primary 사례 수는 별도로 보고한다. 하이퍼파라미터/early stopping 규칙을 test fold를 보기 전에 고정한다.

## D. 시험 수집과 완료 범위

CPU, pod, delay, loss capability를 짧게 확인한 뒤 정상 workload 용량 C를 측정한다. C는 사전 정의한 사용자 성공률/지연 기준과 telemetry 건강성을 만족하는 지속 가능 도착률로 정의하고 측정 시간·판정식을 남긴다. 0.4C baseline, 0.6/0.8/1.0C surge를 실제 값으로 고정한다.

CPU 1 pair와 network delay 1 pair를 시험 수집한다. 두 pair는 수집 경로 검증용이며 모든 셀의 impact 확인율을 추정하기에 충분하지 않다. 각 fault/type/target의 교정 결과를 확인한 뒤 강도를 동결한다. calibration ID와 정식 campaign ID를 분리한다.

최종적으로 기존 테스트와 신규 핵심 로직 테스트를 통과시키고, 138 profiles/schedule dry-run, 시험 수집 artifact 경로/품질/원복 증거, 한 pair 실행 명령과 전체 campaign 실행 명령을 제공해줘. VM 연결이 없으면 live 항목을 수행했다고 표시하지 말고 코드와 재현 가능한 절차까지 완료한다.

이번 요청에서는 138 runs 전체 장시간 수집을 자동 시작하지 않는다. 세팅 완료 보고는 `handoff/linux-v1/ACCEPTANCE.md` 형식으로 작성한다.
