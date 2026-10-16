# SentriX Linux 12-Case 데이터셋 설계 보고서

작성일: 2026-10-06

## 1. 설계 목적

본 데이터셋은 Online Boutique 마이크로서비스 환경에서 발생하는 자원 장애,
서비스 인스턴스 장애, 네트워크 장애 및 트래픽 변화를 대상으로 멀티모달
Root Cause Analysis(RCA) 데이터를 수집하기 위한 파일럿 설계이다.

하나의 fault case는 다음 요소를 하나의 단위로 묶는다.

- 장애 유형과 대상 서비스 또는 dependency edge
- 동일 조건의 matched control
- 사용자 transaction 결과
- Metrics, logs, distributed traces
- Kubernetes events와 환경 snapshot
- 장애 적용·제거 시각과 실제 효과 증거
- 사용자 영향과 recovery label

## 2. 전체 구성

12개의 fault case는 5개 장애 유형으로 구성한다.

| 장애 유형 | Case 수 | 대상 |
|---|---:|---|
| CPU saturation | 2 | checkoutservice |
| Pod failure | 2 | checkoutservice |
| Network delay | 3 | frontend → checkoutservice |
| Packet loss | 3 | frontend → checkoutservice |
| Traffic surge | 2 | frontend entrypoint |
| **합계** | **12** | — |

각 fault case에 독립 matched control을 하나씩 배정한다.

```text
12 fault cases + 12 matched controls = 총 24 runs
```

기존 파일럿 3개 case와 통합하면 장애 유형별 3회 구성을 갖는 총 15개
fault case와 15개 control, 총 30개 run의 파일럿 corpus로 확장된다.

## 3. Case 조합

### 3.1 CPU saturation — 2 cases

| Case ID | 대상 | 주입 조건 | 반복 |
|---|---|---|---:|
| `lin-v4-cpu-checkoutservice-001` | checkoutservice Pod 1개 | stress-ng CPU worker 1개, load 100 | 1 |
| `lin-v4-cpu-checkoutservice-002` | checkoutservice Pod 1개 | stress-ng CPU worker 1개, load 100 | 2 |

CPU 장애는 대상 컨테이너가 속한 cgroup의 CPU 사용량과 throttling을 증가시키는
resource fault이다. Chaos object 생성만으로 성공을 정의하지 않고 실제 CPU 사용량,
cgroup quota, throttling, stress process를 함께 기록한다.

### 3.2 Pod failure — 2 cases

| Case ID | 대상 | 주입 조건 | 반복 |
|---|---|---|---:|
| `lin-v4-pod-failure-checkoutservice-001` | checkoutservice Pod 1개 | 5분 bounded pod-failure | 1 |
| `lin-v4-pod-failure-checkoutservice-002` | checkoutservice Pod 1개 | 5분 bounded pod-failure | 2 |

Pod failure는 Pod를 삭제하는 pod-kill과 구분한다. 대상 Pod는 존재하지만 서비스
요청을 처리하지 못하는 bounded unavailability를 만든다. 대상 Pod UID, readiness,
endpoint 상태, container 상태와 사용자 요청 실패를 함께 기록한다.

### 3.3 Network delay — 3 cases

| Case ID | 대상 edge | 주입 조건 | 반복 |
|---|---|---|---:|
| `lin-v4-delay-frontend-checkout-001` | frontend → checkoutservice | latency 2000 ms, jitter 200 ms | 1 |
| `lin-v4-delay-frontend-checkout-002` | frontend → checkoutservice | latency 2000 ms, jitter 200 ms | 2 |
| `lin-v4-delay-frontend-checkout-003` | frontend → checkoutservice | latency 2000 ms, jitter 200 ms | 3 |

Network delay의 root cause 단위는 단일 서비스가 아니라 dependency edge이다.
source/destination Pod UID, 트래픽 방향, interface, qdisc/filter, packet counter와
실측 latency 변화를 보존한다.

### 3.4 Packet loss — 3 cases

| Case ID | 대상 edge | 주입 조건 | 반복 |
|---|---|---|---:|
| `lin-v4-loss-frontend-checkout-001` | frontend → checkoutservice | random packet loss 5% | 1 |
| `lin-v4-loss-frontend-checkout-002` | frontend → checkoutservice | random packet loss 5% | 2 |
| `lin-v4-loss-frontend-checkout-003` | frontend → checkoutservice | random packet loss 5% | 3 |

Packet loss 역시 dependency edge fault로 정의한다. 선언된 loss 비율과 함께 실제
packet/drop counter, TCP retransmission, 요청 timeout 및 재시도 결과를 기록한다.

### 3.5 Traffic surge — 2 cases

| Case ID | 대상 | 주입 조건 | 반복 |
|---|---|---|---:|
| `lin-v4-surge-frontend-001` | frontend entrypoint | 2 → 5 transaction/s | 1 |
| `lin-v4-surge-frontend-002` | frontend entrypoint | 2 → 5 transaction/s | 2 |

Traffic surge는 특정 서비스 내부 결함이 아니라 외생 workload fault이다. 실제
arrival rate, started/completed transaction, HTTP request rate, dropped iteration과
generator headroom을 함께 기록한다.

## 4. Matched Control 설계

| Fault case | Matched control |
|---|---|
| `lin-v4-cpu-checkoutservice-001` | `lin-v4-control-cpu-checkoutservice-001` |
| `lin-v4-cpu-checkoutservice-002` | `lin-v4-control-cpu-checkoutservice-002` |
| `lin-v4-pod-failure-checkoutservice-001` | `lin-v4-control-pod-checkoutservice-001` |
| `lin-v4-pod-failure-checkoutservice-002` | `lin-v4-control-pod-checkoutservice-002` |
| `lin-v4-delay-frontend-checkout-001` | `lin-v4-control-delay-frontend-checkout-001` |
| `lin-v4-delay-frontend-checkout-002` | `lin-v4-control-delay-frontend-checkout-002` |
| `lin-v4-delay-frontend-checkout-003` | `lin-v4-control-delay-frontend-checkout-003` |
| `lin-v4-loss-frontend-checkout-001` | `lin-v4-control-loss-frontend-checkout-001` |
| `lin-v4-loss-frontend-checkout-002` | `lin-v4-control-loss-frontend-checkout-002` |
| `lin-v4-loss-frontend-checkout-003` | `lin-v4-control-loss-frontend-checkout-003` |
| `lin-v4-surge-frontend-001` | `lin-v4-control-surge-frontend-001` |
| `lin-v4-surge-frontend-002` | `lin-v4-control-surge-frontend-002` |

동일 pair의 control과 fault는 다음 조건을 공유한다.

- 동일한 환경 fingerprint
- 동일한 workload profile과 seed
- 동일한 run 길이와 phase 경계
- 동일한 target transaction rate
- 동일한 application image와 replica 구성
- 동일한 telemetry 설정

Control의 intervention 구간에는 같은 길이의 sham slot을 둔다. Traffic surge
control은 intervention 구간에도 2 transaction/s를 유지한다.

## 5. 실행 프로토콜

각 run은 최대 25분으로 구성한다.

| Phase | 길이 | 목적 |
|---|---:|---|
| Warm-up | 3분 | 애플리케이션과 telemetry 안정화 |
| Baseline | 5분 | 정상 상태 기준 측정 |
| Intervention | 5분 | fault 또는 control sham slot |
| Recovery | 10분 | fault 제거 후 안정 상태 관찰 |
| Cooldown | 2분 | 후속 데이터와 잔류 효과 확인 |
| **합계** | **25분** | — |

각 pair는 다음 순서로 실행한다.

```text
정상성 확인
→ control 실행
→ control export 및 검증
→ 환경 재확인
→ fault 실행
→ fault export 및 검증
→ fault 제거·원복 확인
→ 다음 pair 전 정상 상태 관찰
```

## 6. Workload 설계

사용자 workload는 k6 기반 `browse → product → cart → checkout` transaction이다.

- 기본 arrival rate: 2 transaction/s
- Traffic surge intervention: 5 transaction/s
- 각 HTTP 단계 timeout: 5초
- transaction별 W3C trace ID 생성
- 단계별 span ID와 traceparent 기록
- 성공, HTTP failure, timeout, assertion failure를 개별 기록
- offered, started, completed, failed, dropped rate를 구분

Linux 환경에서 capacity calibration을 수행하고, 2 transaction/s가 정상 SLO와
telemetry 안정성을 만족하는 범위인지 확인한 뒤 campaign 전체에서 고정한다.

## 7. 수집 데이터

### 7.1 Metrics

Canonical long-format Parquet과 모델용 wide-format Parquet을 함께 생성한다.

- Container CPU usage cores 및 CPU limit ratio
- CPU throttled seconds/periods
- Container memory working set bytes 및 memory limit
- Service workload/call rate
- Error count/rate
- Request/span duration histogram
- Latency p50/p90/p99
- Pod readiness와 restart
- TCP retransmission 및 interface drop
- Collector와 scrape health

### 7.2 Logs

- event timestamp와 observed timestamp
- service, Pod UID, container identity
- severity와 message
- trace ID가 존재하는 경우 trace correlation
- Kubernetes 및 Chaos Mesh event

### 7.3 Distributed Traces

- trace ID, span ID, parent span ID
- source/destination service
- operation 및 RPC method
- span kind
- start/end timestamp와 duration
- HTTP/gRPC status
- Pod UID와 service instance identity

### 7.4 Transaction Records

- transaction ID와 stage
- trace ID와 span ID
- 요청 URL 및 method
- HTTP status
- success, failure, timeout
- duration
- business assertion 결과
- actual arrival/completion rate와 dropped iteration

### 7.5 Fault Ground Truth

- case ID, pair ID, run ID, environment ID, campaign ID
- fault type과 target kind
- target service/Pod UID 또는 dependency edge
- 요청·적용·관측·제거 timestamp
- fault parameter와 injector version
- injection effect evidence
- impact 및 recovery label

## 8. 데이터 계층

| 계층 | 형식 | 역할 |
|---|---|---|
| Raw | JSON/NDJSON/YAML | 원본 API 응답, trace, log, event, 환경 snapshot 보존 |
| Canonical | Parquet | 공통 timestamp, unit, service identity로 정규화 |
| Model view | Parquet | window feature, mask, topology 입력 생성 |
| RE2 adapter | Parquet | RCAEval 계열 모델과의 입력 형태 호환 |
| Incident registry | YAML | root cause, 영향, recovery, control pairing label |

## 9. Label 설계

각 case는 하나의 성공/실패 값으로 합치지 않고 다음 label을 분리한다.

- `data_valid`: telemetry와 변환 산출물의 무결성
- `injection_valid`: 장애 효과가 대상에 실제 적용됐는지
- `impact_confirmed`: 사용자 오류 또는 latency 증가 여부
- `recovery_observable`: recovery를 판정할 관측 구간 확보 여부
- `recovery_status`: recovered, not_recovered, not_applicable, unknown
- `eligible_tasks`: detection, localization, classification, recovery 중 활용 가능 과제

장애 주입이 성공했지만 사용자 영향이 발생하지 않은 case는 no-impact 음성 사례로
보존한다. 영향이 지속되고 관찰 종료까지 회복되지 않은 경우에는 recovery time을
임의로 대입하지 않고 right-censored case로 기록한다.

## 10. 품질 게이트

1. Linux netem, tc, CNI 및 Chaos Mesh capability 확인
2. Workload generator capacity와 실제 arrival rate 확인
3. 대상 cgroup, Pod 또는 network edge에서 fault effect 확인
4. Fault 제거와 자원/qdisc 원복 확인
5. Metric source coverage 확인
6. Known trace ID와 trace export completeness 확인
7. Loki chunk 경계, 중복 및 누락 확인
8. Raw/canonical/model view의 행 수, 단위, 변환 손실 확인
9. SHA-256 provenance 확인
10. Control/fault workload 및 환경 매칭 확인

## 11. 예상 규모와 시간

- Fault cases: 12개
- Matched controls: 12개
- 총 runs: 24개
- Run당 workload: 최대 25분
- Export 및 검증: run당 약 10~20분
- Pair reset: 약 5분
- Pair당 예상 시간: 약 75~95분
- 전체 예상 순수 실행 시간: 약 15~19시간

설치, capability probe, capacity calibration과 재실행 시간을 포함해 Linux
campaign은 약 1.5~2일 일정으로 구성한다.

## 12. 기대 결과

본 설계를 통해 다음 연구 질문을 검토할 수 있다.

1. Metrics, logs, traces를 결합하면 사용자 영향 탐지가 가능한가?
2. 영향이 발생한 서비스 또는 dependency edge를 순위화할 수 있는가?
3. 서로 다른 fault 유형을 구분할 수 있는가?
4. Fault 제거 이후 안정적인 recovery onset을 탐지할 수 있는가?
5. No-impact 주입과 실제 사용자 장애를 구분할 수 있는가?

12-case campaign은 수집 파이프라인과 분석 설계 검증을 위한 파일럿 규모이다.
서비스별 일반화와 모델 평가 단계에서는 69 fault cases와 69 controls의 확장
campaign을 별도로 구성한다.

## 13. 면담용 요약

> Linux 환경에서 CPU saturation 2개, Pod failure 2개, Network delay 3개,
> Packet loss 3개, Traffic surge 2개로 총 12개의 fault case를 구성한다.
> 각 case에는 동일 조건의 독립 matched control을 두어 전체 실험 단위는 24개
> run이다. 모든 run에서 metrics, logs, distributed traces, 사용자 transaction,
> Kubernetes events와 fault ground truth를 함께 수집하며, 장애 주입 성공 여부와
> 사용자 영향 및 recovery를 각각 독립적인 label로 기록한다.
