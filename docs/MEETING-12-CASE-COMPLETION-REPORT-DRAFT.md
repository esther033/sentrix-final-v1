# SentriX Linux 추가 12-case 수집 완료 보고서 초안

작성일: 2026-10-06  
문서 상태: **실측 전 완료 보고서 템플릿 — 현재 완료 증거 없음**

> 이 문서는 실제 수집 완료 보고서의 형식과 case 구성을 미리 고정한 초안이다.
> 현재 저장소에는 아래 `lin-v4-*` 12개 fault run 및 matched control 산출물이
> 없으므로, 본 문서를 완료 실적으로 인용하면 안 된다. 각 run의 파일, 검증 결과,
> hash가 생성된 뒤 표의 상태와 수치를 실측값으로 교체하고 승인해야 한다.

## 1. 현재 확인된 사실

- 기존 WSL/Docker Desktop에서 검증된 fault case: 3개
- 기존 matched control: 3개
- 기존 사용 가능 fault:
  - CPU saturation 1개: 주입 성공, 사용자 영향 미확인
  - Pod failure 1개: 오류 증가 및 복구 확인
  - Traffic surge 1개: 지연 증가 및 복구 확인
- Linux 추가 12-case: 현재 미실행 또는 증거 미등록
- 현재 공식 dataset status: `partial_valid_dataset`

## 2. 완료 후 보고할 목표 구성

추가 12개가 모두 유효성 검증을 통과하면 다음 구성이 된다.

```text
기존 fault case 3개 + Linux fault case 12개 = 15 fault cases
기존 control 3개 + Linux control 12개 = 15 control runs
총 30 runs
```

| 유형 | 기존 검증 case | Linux 추가 목표 | 완료 후 fault case |
|---|---:|---:|---:|
| CPU saturation | 1 | 2 | 3 |
| Pod failure | 1 | 2 | 3 |
| Network delay | 0 | 3 | 3 |
| Packet loss | 0 | 3 | 3 |
| Traffic surge | 1 | 2 | 3 |
| **합계** | **3** | **12** | **15** |

## 3. 추가 12-case 완료 검증표

아래 상태는 실제 산출물 검증 전까지 모두 `미검증`이다.

| # | Fault run ID | Matched control ID | 장애 및 대상 | 현재 상태 |
|---:|---|---|---|---|
| 1 | `lin-v4-cpu-checkoutservice-001` | `lin-v4-control-cpu-checkoutservice-001` | CPU saturation / checkoutservice | 미검증 |
| 2 | `lin-v4-cpu-checkoutservice-002` | `lin-v4-control-cpu-checkoutservice-002` | CPU saturation / checkoutservice | 미검증 |
| 3 | `lin-v4-pod-failure-checkoutservice-001` | `lin-v4-control-pod-checkoutservice-001` | Pod failure / checkoutservice | 미검증 |
| 4 | `lin-v4-pod-failure-checkoutservice-002` | `lin-v4-control-pod-checkoutservice-002` | Pod failure / checkoutservice | 미검증 |
| 5 | `lin-v4-delay-frontend-checkout-001` | `lin-v4-control-delay-frontend-checkout-001` | Delay / frontend→checkoutservice | 미검증 |
| 6 | `lin-v4-delay-frontend-checkout-002` | `lin-v4-control-delay-frontend-checkout-002` | Delay / frontend→checkoutservice | 미검증 |
| 7 | `lin-v4-delay-frontend-checkout-003` | `lin-v4-control-delay-frontend-checkout-003` | Delay / frontend→checkoutservice | 미검증 |
| 8 | `lin-v4-loss-frontend-checkout-001` | `lin-v4-control-loss-frontend-checkout-001` | Loss / frontend→checkoutservice | 미검증 |
| 9 | `lin-v4-loss-frontend-checkout-002` | `lin-v4-control-loss-frontend-checkout-002` | Loss / frontend→checkoutservice | 미검증 |
| 10 | `lin-v4-loss-frontend-checkout-003` | `lin-v4-control-loss-frontend-checkout-003` | Loss / frontend→checkoutservice | 미검증 |
| 11 | `lin-v4-surge-frontend-001` | `lin-v4-control-surge-frontend-001` | Traffic surge / frontend | 미검증 |
| 12 | `lin-v4-surge-frontend-002` | `lin-v4-control-surge-frontend-002` | Traffic surge / frontend | 미검증 |

## 4. 고정한 주입 조건

| 유형 | 조건 |
|---|---|
| CPU saturation | checkoutservice Pod 1개, stress-ng 1 worker, load 100 |
| Pod failure | checkoutservice Pod 1개, bounded pod-failure |
| Network delay | frontend→checkoutservice edge, 2000 ms latency, 200 ms jitter |
| Packet loss | frontend→checkoutservice edge, random loss 5% |
| Traffic surge | frontend entrypoint, intervention 구간 2→5 transaction/s |

Linux protocol v4의 기본 run 길이는 최대 25분이다.

```text
warm-up 3분 → baseline 5분 → intervention 5분
→ recovery 10분 → cooldown 2분
```

## 5. 완료 판정 조건

각 case는 다음 조건을 모두 확인한 뒤에만 `완료`로 바꾼다.

1. Fault run과 matched control이 모두 종료 코드 0으로 끝남
2. 동일 workload schedule과 seed, 동일 환경 fingerprint 확인
3. 요청한 fault가 실제 대상 Pod/edge에 적용됨
4. fault 제거와 자원·qdisc 원복 확인
5. `run-assessment`가 valid
6. raw export가 complete
7. canonical metrics/logs/traces/events 생성 완료
8. RE2/model view 생성 완료
9. 원본과 파생 파일의 SHA-256 검증 완료
10. transaction rate와 dropped iteration 기준 통과
11. control/fault 매칭 검증 통과
12. `injection_valid`, `impact_confirmed`, `recovery_observable`, `data_valid`를 각각 기록

Network delay와 Packet loss는 추가로 다음 증거가 필요하다.

- source/destination Pod UID
- 실제 direction과 interface
- tc/qdisc/filter 상태
- packet/drop counter
- 실측 RTT 또는 latency 변화
- 제거 후 qdisc 원복

## 6. 완료 후 채울 결과표

| Case ID | Actual RPS | Transactions | Metric rows | Trace spans | Log rows | Injection valid | Impact confirmed | Recovery | Data valid |
|---|---:|---:|---:|---:|---:|---|---|---|---|
| `lin-v4-cpu-checkoutservice-001` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-cpu-checkoutservice-002` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-pod-failure-checkoutservice-001` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-pod-failure-checkoutservice-002` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-delay-frontend-checkout-001` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-delay-frontend-checkout-002` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-delay-frontend-checkout-003` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-loss-frontend-checkout-001` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-loss-frontend-checkout-002` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-loss-frontend-checkout-003` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-surge-frontend-001` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `lin-v4-surge-frontend-002` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

## 7. 완료 후 사용할 요약 문장

아래 문장은 12개 case와 12개 control이 실제로 완료되고 위 검증표가 모두 채워진
뒤에만 사용한다.

> Linux 환경에서 CPU saturation 2개, Pod failure 2개, Network delay 3개,
> Packet loss 3개, Traffic surge 2개 등 12개의 추가 fault case와 각각의
> matched control을 수집하였다. 기존 3개 fault case와 합쳐 5개 장애 유형별
> 3회 구성의 총 15개 fault case와 15개 control, 총 30개 run을 확보하였다.
> 각 run에는 metrics, logs, traces, transaction 결과, Kubernetes events와
> fault ground truth가 포함되며, 영향 여부와 복구 여부는 별도 label로 기록하였다.

## 8. 지금 면담에서 사용할 수 있는 정직한 문장

> 현재 실측 완료된 것은 3개 fault case와 3개 matched control이다. Linux에서
> 추가할 12개 case의 장애 유형, 대상, 반복 수와 control 조합은 확정했으며,
> 이를 모두 수집하면 총 15개 fault case와 15개 control의 파일럿 데이터셋이
> 된다. 아직 Linux 12개 case의 실측 결과는 생성되지 않았다.
