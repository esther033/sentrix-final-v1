# 교수님 면담용: 추가 12-case Linux 수집안

작성일: 2026-10-06  
문서 성격: **수집 완료 보고서가 아니라, 현재 3개 case에 추가할 12개 case를 고정한 면담용 계획/가정 시나리오**

> 중요: 아래 12개는 아직 실측 완료된 데이터가 아니다. 면담에서는 “수집했다”가 아니라
> “이 조합으로 추가 수집하여 15-case 파일럿을 완성할 계획”이라고 설명해야 한다.

## 1. 한 문장 요약

현재 검증된 CPU saturation, Pod failure, Traffic surge 각 1개에 더해,
CPU 2개, Pod failure 2개, Network delay 3개, Packet loss 3개,
Traffic surge 2개를 Linux 환경에서 추가 수집한다. 완료되면 5개 장애 유형별
3회 반복, 총 15개 fault case와 15개 matched control, 즉 30개 run의 파일럿
그리드가 된다.

## 2. 조합 계산

```text
현재 검증된 fault case 3개
+ 추가 Linux fault case 12개
= 총 fault case 15개

fault 유형 5개 × 유형별 3회 = 15 fault cases
fault case별 독립 matched control 1개 = 15 control runs
최종 합계 = 30 runs
```

현재 검증된 3개는 다음과 같다.

| 유형 | 기존 fault run | 기존 control | 대상 | 실측 판정 |
|---|---|---|---|---|
| CPU saturation | `m2-cpu-checkoutservice-003` | `m2-control-cpu-saturation-001` | checkoutservice | 주입 성공, 영향 미확인 |
| Pod failure | `m2-pod-failure-checkoutservice-005` | `m2-control-pod-failure-005` | checkoutservice | 오류 증가, 복구 확인 |
| Traffic surge | `m2-traffic-surge-frontend-003` | `m2-control-traffic-surge-005` | frontend entrypoint | 지연 증가, 복구 확인 |

## 3. 추가할 12개 fault case

모든 case는 별도의 control을 먼저 실행한다. 아래의 “반복”은 같은 장애 조건의
독립 실행 번호이며 workload seed와 실행 시각을 다르게 기록한다.

| # | 계획 case ID | 장애 유형 | 대상/scope | 주입 조건 | 반복 |
|---:|---|---|---|---|---:|
| 1 | `lin-v4-cpu-checkoutservice-001` | CPU saturation | checkoutservice Pod 1개 | stress-ng 1 worker, load 100 | Linux 1 |
| 2 | `lin-v4-cpu-checkoutservice-002` | CPU saturation | checkoutservice Pod 1개 | stress-ng 1 worker, load 100 | Linux 2 |
| 3 | `lin-v4-pod-failure-checkoutservice-001` | Pod failure | checkoutservice Pod 1개 | bounded pod-failure | Linux 1 |
| 4 | `lin-v4-pod-failure-checkoutservice-002` | Pod failure | checkoutservice Pod 1개 | bounded pod-failure | Linux 2 |
| 5 | `lin-v4-delay-frontend-checkout-001` | Network delay | frontend → checkoutservice edge | latency 2000 ms, jitter 200 ms | Linux 1 |
| 6 | `lin-v4-delay-frontend-checkout-002` | Network delay | frontend → checkoutservice edge | latency 2000 ms, jitter 200 ms | Linux 2 |
| 7 | `lin-v4-delay-frontend-checkout-003` | Network delay | frontend → checkoutservice edge | latency 2000 ms, jitter 200 ms | Linux 3 |
| 8 | `lin-v4-loss-frontend-checkout-001` | Packet loss | frontend → checkoutservice edge | random loss 5% | Linux 1 |
| 9 | `lin-v4-loss-frontend-checkout-002` | Packet loss | frontend → checkoutservice edge | random loss 5% | Linux 2 |
| 10 | `lin-v4-loss-frontend-checkout-003` | Packet loss | frontend → checkoutservice edge | random loss 5% | Linux 3 |
| 11 | `lin-v4-surge-frontend-001` | Traffic surge | frontend entrypoint | 2 → 5 transaction/s | Linux 1 |
| 12 | `lin-v4-surge-frontend-002` | Traffic surge | frontend entrypoint | 2 → 5 transaction/s | Linux 2 |

### 유형별 최종 구성

| 유형 | 기존 case | 추가 case | 최종 합계 |
|---|---:|---:|---:|
| CPU saturation | 1 | 2 | 3 |
| Pod failure | 1 | 2 | 3 |
| Network delay | 0 | 3 | 3 |
| Packet loss | 0 | 3 | 3 |
| Traffic surge | 1 | 2 | 3 |
| **합계** | **3** | **12** | **15** |

## 4. 대응하는 12개 matched control

| Fault case | Matched control ID |
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

Control은 fault run과 동일한 workload seed, 길이, phase schedule을 사용하되
intervention 구간에는 fault를 주입하지 않는 sham slot을 둔다. Traffic surge의
control은 해당 구간에도 2 transaction/s를 유지한다.

## 5. 공통 실행 조건

Linux protocol v4 기준으로 run 하나는 최대 25분이다.

```text
warm-up 3분
→ baseline 5분
→ intervention 5분
→ recovery 10분
→ cooldown 2분
```

- 정상 workload: 2 transaction/s에서 시작하되 Linux capacity calibration 통과 후 고정
- CPU, Pod, Delay, Loss: intervention 구간에도 workload 2 transaction/s 유지
- Traffic surge: intervention 구간만 5 transaction/s
- 각 pair 순서: 정상성 확인 → control → export/검증 → 환경 확인 → fault → export/검증 → 원복 확인
- pair 사이: 최소 5분 정상 상태 확인
- 각 pair는 독립 workload seed 사용
- 같은 pair의 control/fault는 동일 seed와 schedule 사용

2 transaction/s가 Linux VM의 정상 용량 조건을 만족하지 못하면 임의로 강행하지 않고,
capacity calibration 결과에 따라 전체 campaign의 rate를 한 번만 수정한 뒤 고정한다.

## 6. case마다 수집하는 데이터

각 fault case와 matched control에서 동일한 telemetry를 수집한다.

| 데이터 | 저장 형식 | 내용 |
|---|---|---|
| Metrics | Canonical Parquet | CPU, memory, workload/call rate, error, latency histogram 및 p50/p90 |
| Logs | Canonical Parquet | 전체 namespace의 서비스·Pod·container 로그 |
| Traces | Canonical Parquet | trace/span/parent 관계, 서비스, operation, duration, RPC status |
| Transactions | JSONL | browse/cart/checkout 단계별 성공, 실패, timeout, duration, trace ID |
| Kubernetes events | Parquet/NDJSON | Pod 상태, Chaos event, 배포 및 환경 변화 |
| Fault evidence | JSON/YAML | 요청·적용·관측·제거 시각, target UID/edge, qdisc 또는 stress 증거 |
| Incident label | YAML | root cause, impact, recovery, validity, control pairing |

Network delay와 Packet loss에는 선언한 Chaos object만 기록하지 않고 다음을 추가한다.

- source/destination Pod UID와 실제 edge 방향
- tc/qdisc/filter 적용 상태
- packet counter 및 drop counter
- 실제 RTT/latency 변화
- fault 제거 후 qdisc 원복 확인

## 7. 완료 후 case 수를 보고하는 방법

12개가 실제로 전부 유효성 검증을 통과했다는 전제에서만 다음처럼 말할 수 있다.

> Online Boutique를 대상으로 CPU saturation, Pod failure, Network delay,
> Packet loss, Traffic surge의 5개 장애 유형을 수집했다. 유형별로 3개의
> fault case를 확보해 총 15개 fault case를 구성했고, 각 case에 독립 matched
> control을 두어 총 30개 run을 수집했다. 각 run에는 metrics, logs, traces,
> transaction 결과, Kubernetes events와 fault ground truth가 포함된다.

단, 다음 세 값은 분리해서 보고해야 한다.

- `injection_valid`: 장애 효과가 대상에 실제 적용됐는가
- `impact_confirmed`: 사용자의 오류 또는 지연 증가가 확인됐는가
- `data_valid`: metrics/logs/traces 수집과 변환이 완전한가

예를 들어 CPU 주입이 성공했지만 사용자 영향이 없으면 유효한 no-impact case이지,
영향이 확인된 양성 incident로 세면 안 된다.

## 8. 현재 시점에서 교수님께 말할 문장

> 현재는 3개 fault case와 3개 matched control을 실측·검증했다. 다음 Linux
> campaign에서는 CPU 2개, Pod failure 2개, Network delay 3개, Packet loss
> 3개, Traffic surge 2개 등 정확히 12개 fault case와 그에 대응하는 control
> 12개를 추가할 계획이다. 완료 시 5개 장애 유형별 3회 반복의 15-case
> 파일럿과 총 30개 run을 확보하게 된다.

## 9. 해석상 주의

- 기존 3개는 Docker Desktop/WSL 환경이고 추가 12개는 Linux 환경이므로 `environment_id`를 분리해야 한다.
- 서로 다른 환경의 반복을 완전히 동일한 재현 실험이라고 주장할 수 없다.
- 엄격하게 동일 환경 반복성을 보이려면 기존 3개 유형도 Linux에서 각각 3회 다시 수행해야 한다.
- 15개 fault case는 파일럿 최소선이며 서비스별 root-cause 일반화를 위한 충분한 학습량은 아니다.
- 서비스별 RCA까지 확장하는 다음 목표는 계획상 69 fault cases와 69 controls, 총 138 runs이다.
