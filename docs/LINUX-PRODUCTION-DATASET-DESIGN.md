# SentriX Linux 본 프로젝트 데이터셋 설계

작성일: 2026-10-06  
캠페인 ID: `linux-v1`  
대상 시스템: Online Boutique v0.9.0 / Kubernetes / Chaos Mesh / OpenTelemetry

## 1. 먼저 구분해야 하는 단위

저장소에 보이는 파일 수를 데이터셋 case 수로 해석하지 않는다.

| 용어 | 의미 | 현재 상태 |
|---|---|---:|
| profile | workload와 fault를 기술한 JSON 설정 | `workload/profiles/`에 22개 |
| run | control 또는 fault를 실제로 한 번 실행한 결과 폴더 | `runs/`에 28개 |
| matched pair | 동일 조건의 control run 1개 + fault run 1개 | 공식 기존 corpus 3쌍 |
| fault case | fault run 1개와 그 ground truth | 공식 기존 corpus 3개 |
| dataset case | 분석 시 fault와 matched control을 묶은 한 실험 단위 | 공식 기존 corpus 3개 |

현재 `runs/` 28개에는 smoke, fastcheck, 중단 및 이전 정책 실행이 포함된다. 본 프로젝트의
case 수로 세면 안 된다. 공식 기존 데이터는 다음 3개 fault case와 matched control 3개,
총 6 run이다.

| Fault case | Matched control | Target | 해석 |
|---|---|---|---|
| `m2-cpu-checkoutservice-003` | `m2-control-cpu-saturation-001` | checkoutservice | 주입 성공, 사용자 영향 미확인 |
| `m2-pod-failure-checkoutservice-005` | `m2-control-pod-failure-005` | checkoutservice | 오류 증가, 복구 확인 |
| `m2-traffic-surge-frontend-003` | `m2-control-traffic-surge-005` | frontend entrypoint | 지연 증가, 복구 확인 |

기존 6 run은 Windows/Docker Desktop 환경의 `legacy-m2` cohort로 보존한다. 새 Linux
`linux-v1`과 합쳐 case 수를 부풀리지 않으며, Linux 모델의 test set에도 섞지 않는다.

## 2. CPU saturation은 정확히 어떻게 주입되는가

### 2.1 사용자 workload와 장애 부하는 서로 다르다

한 run 동안 k6는 frontend를 통해 다음 end-to-end transaction을 계속 발생시킨다.

```text
browse_home -> browse_product -> cart_add -> cart_view -> checkout
```

기본 도착률은 2 transaction/s이다. 이것은 checkoutservice에 CPU 부하를 직접 보내는
것이 아니라 실제 사용자 흐름을 반복하는 workload다.

CPU fault 시점에는 이 workload를 그대로 유지한 상태에서 Chaos Mesh `StressChaos`를
추가로 생성한다. 선택 조건은 다음과 같다.

```yaml
kind: StressChaos
spec:
  mode: one
  selector:
    namespaces: [sentrix]
    labelSelectors:
      app: checkoutservice
  stressors:
    cpu:
      workers: 1
      load: 100
  duration: 300s
```

의미는 다음과 같다.

1. `sentrix` namespace에서 `app=checkoutservice`인 Pod 중 하나를 고른다.
2. 선택된 Pod에 CPU stress worker 1개를 100% duty cycle로 300초 동안 실행한다.
3. checkoutservice 컨테이너 CPU limit은 현재 `500m`, 즉 약 0.5 CPU이다.
4. 정상 사용자 요청과 stress process가 동시에 CPU를 요구하면서 사용량과 throttling이
   증가하는지를 관측한다.
5. 300초 후 Chaos Mesh의 `AllRecovered=True`를 확인하고 recovery 구간을 관측한다.

`load: 100`만으로 CPU saturation 성공을 판정하지 않는다. 본 수집에서는 다음 증거가
모두 있어야 `injection_valid=true`로 둔다.

- 선택된 대상의 service name, Pod UID, container ID
- 적용된 StressChaos 원문과 Chaos Mesh `AllInjected=True`
- 대상 container의 CPU usage/limit ratio 상승
- CFS throttled periods 또는 throttled seconds 상승
- stress process가 대상 Pod의 의도한 cgroup quota에 작용한다는 capability 확인
- 종료 후 `AllRecovered=True`와 CPU/throttling 정상화

CPU 주입이 성공해도 오류율 또는 지연이 기준을 넘지 않으면 데이터는 버리지 않는다.
이 경우 `injection_valid=true`, `impact_confirmed=false`인 no-impact case다.

### 2.2 실행 파일 간 연결

```text
workload/profiles/<case>.json
  -> fault.template = deploy/chaos-mesh/faults/cpu-saturation.yaml
  -> root_cause_service = checkoutservice
  -> scripts/run-matched-pair.py
  -> scripts/run-attended.py
  -> runs/<run-id>/
```

profile의 `root_cause_service`만 바꾸면 같은 CPU fault를 다른 서비스에 적용할 수 있다.
단, 대상 Deployment에 `app=<service>` label이 있고 workload 중 실제 요청을 받아야 한다.

## 3. 본 프로젝트의 연구 단위

목표는 단순히 “CPU 장애인가”를 맞히는 것이 아니라 다음 두 값을 함께 예측하는 것이다.

```text
fault_type = cpu_saturation
root_cause = productcatalogservice
```

따라서 동일 fault를 호출 그래프 위치가 다른 여러 서비스에 주입한다. CPU의 로컬 패턴은
비슷해도 상류 지연, 하류 호출, 오류 전파와 사용자 endpoint 영향은 서비스마다 다르다.

본 캠페인에서 service-level fault 대상은 다음 5개로 고정한다.

| 서비스 | 선택 이유 |
|---|---|
| `checkoutservice` | 여러 하위 서비스를 호출하는 핵심 주문 orchestrator |
| `productcatalogservice` | frontend와 recommendation 양쪽에서 호출되는 고빈도 조회 서비스 |
| `currencyservice` | frontend와 checkout에서 호출되는 짧고 빈번한 동기 서비스 |
| `recommendationservice` | 중간 계층이며 productcatalog로 fan-out |
| `paymentservice` | checkout 경로의 말단 서비스 |

네트워크 fault는 서비스 하나가 아니라 source와 destination으로 구성된 edge를 root cause로
기록한다. 실제 기존 trace에서 관측됐고 기능적 위치가 다른 다음 5개 edge를 사용한다.

| Edge ID | Source | Destination |
|---|---|---|
| `front-product` | frontend | productcatalogservice |
| `front-currency` | frontend | currencyservice |
| `front-recommendation` | frontend | recommendationservice |
| `recommendation-product` | recommendationservice | productcatalogservice |
| `checkout-payment` | checkoutservice | paymentservice |

## 4. Linux v1 본 캠페인: 69 fault cases

### 4.1 전체 행렬

| Fault type | Target 축 | Target 수 | 반복 | Fault cases |
|---|---|---:|---:|---:|
| CPU saturation | 5 services | 5 | 3 | 15 |
| Pod failure | 5 services | 5 | 3 | 15 |
| Network delay | 5 dependency edges | 5 | 3 | 15 |
| Packet loss | 5 dependency edges | 5 | 3 | 15 |
| Traffic surge | 3 calibrated load levels | 3 | 3 | 9 |
| **합계** |  |  |  | **69** |

각 fault case에 독립 matched control을 하나씩 둔다.

```text
69 fault runs + 69 control runs = 총 138 runs
```

12-case 문서는 파이프라인 확인용 소규모 설계이고, `linux-v1`의 case 수로 사용하지 않는다.

### 4.2 v1 범위에서 제외하는 fault

RE2-OB의 memory, disk I/O, socket fault를 이름만 맞추기 위해 추가하지 않는다. 현재 저장소에는
이 세 유형의 검증된 Chaos template과 효과 판정 metric이 없고, 기존 metric view에도 disk I/O와
socket count가 없다. 먼저 exporter, template, capability gate와 ground-truth 검증을 구현한 뒤
`linux-v2`의 별도 cohort로 추가한다. 서로 다른 수집 schema의 case를 `linux-v1`에 중간 합류시키지
않는다.

### 4.3 고정할 fault parameter

아래 값은 Linux capability/capacity calibration에서 실제 효과를 확인한 뒤 campaign 시작 전에
한 번 고정한다. 본 campaign 중간에는 결과를 보고 강도를 바꾸지 않는다.

| Fault | 시작 후보 | 본 campaign 고정 원칙 |
|---|---|---|
| CPU | worker 1, load 100, 300초 → 시험 2차 worker 4, load 100 (SETUP-REVIEW 7.15) | 대상 CPU limit 대비 포화 및 throttling이 확인되는 최소 강도 |
| Pod failure | `pod-failure`, 300초, replica 1 | Pod UID/readiness/endpoints 변화가 확인되는 bounded failure |
| Delay | 100 ms + jitter 10 ms, 300초 (filter: 도착 Pod IP + 도착 Service ClusterIP, SETUP-REVIEW 7.15) | 실제 edge RTT/span latency 상승이 확인되는 최소 강도 |
| Loss | random 2%, 300초 | qdisc drop counter와 요청 영향이 모두 관측되는 최소 강도 |
| 정상 baseline | 지속가능 용량 C의 0.4C | 모든 surge pair의 control 및 비장애 phase |
| Surge L1 | 0.8C (이전 0.6C) | baseline의 2배인 낮은 surge |
| Surge L2 | 1.0C (이전 0.8C) | 서비스 포화 경계(C) |
| Surge L3 | 1.33C (이전 1.0C) | C 초과, p99가 baseline의 3배를 넘는 높은 surge |

2026-10-20 변경(SETUP-REVIEW 7.15): C = 6에서 0.6C(3.6 tx/s)의 p99는 baseline과 같아 확실한 무영향이었고, 1.0C(p99 326 ms)도 3배 임계(약 360~384 ms) 아래인 경계였다. 4/3 C = 8 tx/s는 p99 545 ms(약 4.3배)로 측정됐다.

현재 2 -> 5 transaction/s는 기존 환경의 값일 뿐 Linux VM에서 자동 재사용하지 않는다.
먼저 VM의 지속 가능 용량 `C`를 측정하고 실제 achieved rate로 L1/L2/L3를 고정한다.

### 4.4 반복과 split

- repetition을 고정 train/validation/test로 나누지 않고 rotating grouped 3-fold CV를 사용한다.
- fold 1/2/3은 각각 repetition 1/2/3을 test로 사용하고 나머지 두 repetition으로 학습한다.
- 모델 종류와 hyperparameter는 legacy 또는 전용 pilot에서 미리 동결하며 CV 결과를 보고 조정하지 않는다.
- 하나의 fault, matched control과 그 모든 window/view는 반드시 같은 fold에 둔다.
- 30초 window를 무작위로 나눠 train/test에 섞지 않는다.
- 모든 채택 case에 out-of-fold 예측을 하나씩 만들고 case 단위 mean, standard deviation과 bootstrap confidence interval을 보고한다.
- 새 서비스 일반화는 fixed service class가 아닌 shared node scorer의 leave-one-service-out으로 평가한다.
- 새 edge 일반화는 shared directed-edge scorer의 leave-one-edge-out으로 평가한다.
- 실행 순서는 fault type별로 몰아서 돌리지 않고 target과 type을 block-randomize한다.
- repetition 1/2/3은 campaign 전체 기간에 섞어 배치해 fold와 수집 날짜가 일치하지 않게 한다.

69 fault case는 본 프로젝트의 최소 core corpus다. 시간 구간을 잘라 수천 sample로 만들 수
있지만 독립 실험 case 수는 여전히 69개라고 보고한다.

## 5. 한 pair의 표준 실행 프로토콜

각 run은 총 25분이지만 장애 시작 시각은 고정하지 않는다. 실행 전에 7~12분 후보 중 하나를
배정하고 matched control의 sham onset에도 같은 값을 사용한다.

| Phase | 시간 | Control | Fault |
|---|---:|---|---|
| warmup | 3분 고정 | 정상 workload | 정상 workload |
| baseline | 4~9분 | 정상 workload | 정상 workload |
| intervention | 5분 고정 | sham, 장애 없음 | fault 적용 |
| recovery | 6~11분 | 정상 workload | fault 제거 후 관찰 |
| cooldown | 2분 고정 | 정상 workload | 정상 workload |

control이 항상 먼저 오는 교란을 막기 위해 pair 순서는 target/type 안에서 절반씩
`control -> fault`와 `fault -> control`로 counterbalance한다. 두 run 사이에는 동일한
건강성·원복 gate를 적용한다.

```text
사전 건강성/capability 확인
-> 사전 생성된 pair order의 첫 run 25분
-> export, quality gate, 환경 fingerprint와 잔류 fault 확인
-> pair의 두 번째 run 25분
-> export, quality gate, AllRecovered 및 자원/qdisc 원복 확인
-> 다음 pair 전 정상 상태 확인
```

pair당 실행·export·원복에 약 75~95분, 69 pair에 약 86~109시간의 순수 시간이 필요하다.
실패 재실행과 초기 교정을 포함하면 2주 내외의 unattended campaign 일정을 잡는다.

## 6. profile 형식

각 조합은 다음 구조의 JSON profile을 사용한다. profile은 데이터가 아니라 실행 설정이다.

```json
{
  "profile_name": "linux-v1-cpu-checkoutservice-r01",
  "campaign_id": "linux-v1",
  "pair_id": "linux-v1-cpu-checkoutservice-r01",
  "repetition": 1,
  "cv_group": "repetition-1",
  "onset_offset_seconds": 540,
  "pair_order": "fault_then_control",
  "target_rps": 2,
  "time_unit": "1s",
  "duration": "25m",
  "warmup_seconds": 180,
  "baseline_seconds": 360,
  "fault_seconds": 300,
  "recovery_seconds": 540,
  "cooldown_seconds": 120,
  "traffic_phase_rps": {
    "warmup": 2,
    "baseline": 2,
    "fault": 2,
    "recovery": 2,
    "cooldown": 2
  },
  "pre_allocated_vus": 10,
  "max_vus": 50,
  "stage_timeout": "5s",
  "trace_workers": 2,
  "fault": {
    "type": "cpu_saturation",
    "template": "deploy/chaos-mesh/faults/cpu-saturation.yaml",
    "root_cause_service": "checkoutservice",
    "scope_kind": "service_instance",
    "params": {}
  }
}
```

control profile은 onset, phase, workload/seed를 동일하게 두고 `fault`만 제거한다.

## 7. ID와 폴더 규칙

ID는 실행 전에 모두 생성하고 중복을 금지한다.

```text
Fault run:   linux-v1-<fault>-<target>-r<01..03>
Control run: linux-v1-control-<fault>-<target>-r<01..03>
Pair ID:     linux-v1-<fault>-<target>-r<01..03>
```

예:

```text
linux-v1-cpu-checkoutservice-r01
linux-v1-control-cpu-checkoutservice-r01
linux-v1-delay-front-product-r02
linux-v1-control-delay-front-product-r02
```

저장 구조는 run마다 동일하다.

```text
runs/<run-id>/
├── run-manifest.yaml                 # 실행 환경, phase, workload, provenance
├── fault-record.json                 # 주입/제거 시각과 target ground truth
├── injected-manifest.yaml            # 실제 적용한 Chaos manifest
├── transaction-results.jsonl         # transaction/stage별 사용자 관측
├── environment-before.json
├── environment-after.json
├── quality-report.json
├── run-assessment-v2.json
├── pipeline-v2.json                  # 최신 유효 view를 가리키는 포인터
├── raw-v2/
│   ├── metrics/*.json                # Prometheus 원본 응답
│   ├── traces/*.json                 # Tempo trace 원본
│   ├── logs.ndjson                   # Loki log 원본
│   ├── events.ndjson                 # Kubernetes/Chaos events
│   └── environment/*.{json,yaml}
├── canonical-v2-<hash>/
│   ├── metrics.parquet
│   ├── traces.parquet
│   ├── logs.parquet
│   └── events.parquet
└── re2-v2-<hash>/
    ├── metrics.parquet
    ├── traces.parquet
    └── logs.parquet
```

학습 코드는 폴더명을 추측하지 않고 `pipeline-v2.json`의 `views` 경로만 읽는다.

위 구조는 provenance를 포함한 run-level 원본과 정규화 데이터 구조다. 모델 학습에 바로
투입하려면 다음 campaign-level index와 파생 view를 추가한다.

```text
datasets/linux-v1/
├── cases.parquet                 # case/pair/run/label/path/채택 여부
├── splits.yaml                   # case 단위 train/validation/test
├── topology.json                 # canonical service node와 directed edge
├── feature-schema.yaml           # feature 이름, 단위, sampling, missing 정책
├── label-schema.yaml             # fault/location/impact/recovery label 정의
├── normalization-train.json      # train split만으로 계산한 scaling 값
└── model-v1-<hash>/
    ├── windows.parquet           # 고정 window feature와 phase/label
    ├── metric-mask.parquet       # 실제 관측/결측/forward-fill 구분
    ├── trace-edges.parquet       # window별 service graph edge feature
    └── build-summary.json        # 입력 hash, 제외 case, 변환 손실
```

`re2-v2`는 외부 RCAEval 계열 모델과 비교하기 위한 adapter이고 SentriX의 주 학습 view로
간주하지 않는다. 주 학습 입력은 canonical에서 재현 가능하게 만든 `model-v1`이다.

### 7.1 현재 exporter와 Linux v1 필수 수집량의 차이

현재 `scripts/telemetry_export.py`가 실제로 export하는 metric group은 container CPU usage,
memory working set, span call rate, span error increase, span duration histogram 계열이다. 기존
run 폴더에는 traces/logs/events/transactions와 환경 snapshot도 존재하지만, 다음 항목은
Linux v1 전체 수집 전에 exporter와 quality gate에 추가해야 한다.

- CFS throttled seconds/periods와 CPU quota/limit
- Pod readiness와 restart의 시간 흐름
- edge별 qdisc/filter packet/drop counter와 실제 RTT probe
- TCP retransmission 또는 동등한 network effect evidence
- OTel Collector/Prometheus/Tempo/Loki의 queue, drop, export failure
- workload seed와 실제 offered/started/completed/dropped rate

따라서 기존 폴더 구조에 파일이 존재한다는 사실만으로 모델 source가 완전하다고 판정하지
않는다. `feature-schema.yaml`의 required feature와 quality gate가 모두 통과해야 해당 case를
`cases.parquet`에서 학습 가능 상태로 표시한다.

## 8. 수집 신호와 필수 필드

### Metrics

- container CPU usage cores, CPU limit ratio
- CFS throttled periods/seconds
- memory working set, memory limit ratio, OOM/restart
- service/edge call rate, error rate
- span latency histogram과 p50/p90/p99
- Pod readiness, replica, restart count
- TCP retransmission, interface/qdisc packet/drop counter
- Prometheus, OTel Collector, Tempo, Loki 자체 health와 queue/drop

### Logs와 events

- event timestamp와 observed timestamp
- service, deployment, Pod UID, container ID
- severity, message, trace ID
- Kubernetes lifecycle와 Chaos Mesh condition/event

### Traces

- trace/span/parent ID
- source/destination service와 operation
- start/end/duration, HTTP 또는 gRPC status
- service instance와 Pod UID

### Ground truth

- campaign/pair/run/case ID와 split
- fault type, target kind, target service 또는 directed edge
- requested/applied/observed/removed timestamp
- 선언 parameter와 실제 효과 측정값
- `data_valid`, `injection_valid`, `impact_confirmed`
- `recovery_observable`, `recovery_status`, recovery time 또는 right-censored 표시

## 9. 실행 명령 예시

control과 fault를 따로 수동 실행하지 않고 pair runner를 사용한다. 단, 현재
`run-matched-pair.py`는 control-first로 고정되어 있으므로 본 campaign 시작 전 저장된
`pair_order`를 실행할 수 있도록 수정해야 한다.

```bash
python -B scripts/run-matched-pair.py \
  --control-id linux-v1-control-cpu-checkoutservice-r01 \
  --fault-id linux-v1-cpu-checkoutservice-r01 \
  --control-profile workload/profiles/linux-v1/control-cpu-checkoutservice-r01.json \
  --fault-profile workload/profiles/linux-v1/cpu-checkoutservice-r01.json \
  --k6-bin k6
```

실행 전에는 최소한 다음을 확인한다.

```bash
kubectl get pods -n sentrix
kubectl get stresschaos,networkchaos,podchaos -n sentrix
kubectl get pods -n sentrix -l app=checkoutservice --show-labels
```

## 10. 품질 게이트와 채택 기준

다음 조건을 모두 만족한 pair만 core corpus에 채택한다.

1. pair의 각 run 시작 전 모든 app/telemetry Pod가 Ready다.
2. control과 fault의 환경 fingerprint, image digest, replica, workload schedule/seed가 일치한다.
3. transaction, metrics, logs, traces, events export가 완료된다.
4. fault target과 실제 선택된 Pod UID 또는 edge가 일치한다.
5. 선언값이 아니라 CPU/throttling, readiness 또는 qdisc counter로 실제 주입 효과를 확인한다.
6. Chaos fault 제거와 대상 상태 원복이 확인된다.
7. `pipeline-v2.complete=true`이고 각 artifact hash가 일치한다.
8. collector/drop/retention 문제로 신호가 잘리지 않는다.

`impact_confirmed=false`는 데이터셋 제외 사유는 아니지만 primary impact detection과 RCA의
positive 학습에는 사용하지 않는다. injection-valid/no-impact stratum으로 보존해 calibration과
false-positive 분석에 쓴다. `data_valid=false` 또는 `injection_valid=false`인 실행은 학습
corpus에서 제외하고 동일 ID를 덮어쓰지 않은 채 새 attempt ID로 재실행한다.

## 11. 수집 순서

1. Ubuntu VM에 k3s/containerd, Chaos Mesh, telemetry stack과 Online Boutique를 배포한다.
2. CPU cgroup과 network netem capability를 전용 probe로 검증한다.
3. 1시간 capacity pilot으로 지속 가능 transaction rate `C`와 저장량/분을 측정한다.
4. 각 fault의 실제 효과가 관측되는 최소 강도를 교정하고 parameter를 동결한다.
5. 30초 window당 표본 수와 impact 확인율을 CPU 1 pair, network 1 pair로 먼저 확인한다.
6. `linux-v1` profile 138개, onset/pair-order schedule과 campaign index를 생성해 schema validation한다.
7. block-randomized 69 matched pair를 queue로 순차 실행한다.
8. 매 run 직후 export, hash, quality gate, 원복 확인을 수행한다.
9. campaign 종료 후 grouped 3-fold index와 out-of-fold 평가 index를 생성한다.

초기 VM이 8 GiB RAM/6 vCPU 수준이면 capability gate와 1~2 pair만 먼저 실행한다. 138 run
전체는 telemetry backend와 앱의 자원 경쟁 및 저장 공간을 고려해 더 큰 상시 Linux 환경에서
수집하는 것을 기준으로 한다.

