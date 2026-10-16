# Linux 수집 셋업 검토 및 보완 내역 (2026-10-16)

대상: `SentriX-linux-v1-setup-20261014.zip` → 이 패키지 `SentriX-linux-v2-setup`.
범위: 코드·설정·문서 검토와 오프라인에서 가능한 구현. **Linux에서 실제로 실행해 본 것은 없다.** 셸 스크립트는 문법 검사만, Python은 단위 테스트까지 했다.

## 1. 결론

기존 설계(69 fault case + 69 matched control, case 단위 3-fold CV, no-impact 분리, 누수 금지 목록)는 프로젝트 문서의 원칙(case≠window, leakage 방지, ranking 지향)과 잘 맞는다. 설계는 유지했다.
다만 그대로 Linux에서 돌렸다면 **network 30 case 전부가 잘못 수집되는 버그**가 있었고, 실행 환경이 Windows/port-forward에 묶여 있었으며, handoff가 요구한 구현 다수가 비어 있었다. 아래를 보완했다.

## 2. 발견한 문제와 수정

| # | 문제 | 영향 | 수정 |
|---|---|---|---|
| 1 | `run-attended.py`가 edge 템플릿의 `SOURCE_SERVICE`와 `TARGET_SERVICE`를 둘 다 `root_cause_service`로 치환 | delay/loss 30 case가 의도한 edge가 아니라 자기 자신→자기 자신 selector가 됨. 라벨과 실제 주입이 불일치 | profile에 `target_kind/edge_id/source_service/destination_service`를 두고 그대로 치환. edge인데 둘 중 하나가 없으면 실행 거부. source/destination Pod UID와 Chaos Mesh가 실제 선택한 record 저장 |
| 2 | backend URL이 `127.0.0.1:8080/9090/3200/3100` 하드코딩 + 수동 port-forward 전제 | 로그아웃·세션 종료 시 수집 중단 | `SENTRIX_*_URL` 환경변수(`linux/config/endpoints.env`) + k3s 고정 NodePort |
| 3 | pair order가 control-first 고정 | 순서 교란 통제 불가 | `run-matched-pair.py --pair-order`(기본: profile 저장값). fault-first는 `--defer-control-match`로 실행 후 `scripts/evaluate-pair.py`가 **같은 매칭 규칙**(workload 키, phase rate, fingerprint, control 유효성, 2h)을 시간 방향만 바꿔 적용. 그 뒤에 incident record 생성 |
| 4 | 138 profile / schedule 생성기 없음 | 수작업 시 균형·재현성 보장 불가 | `scripts/generate-campaign.py` (seed 재현, 셀당 2/1 순서, 전체 34/35, 셀 내 onset 서로 다름, 반복이 시간축에 섞임, 다른 내용 덮어쓰기 거부, draft/frozen 구분, calibration ID 공간 분리) |
| 5 | workload seed가 profile에만 있고 요청 계획에 미적용 | control/fault가 다른 상품 시퀀스 | k6가 `WORKLOAD_SEED`로 (scenario, iteration) 기반 상품 선택. trace/span ID는 계속 무작위(고유성 유지) |
| 6 | CPU throttling, quota/limit, readiness, restart, 네트워크 drop, telemetry health 미수집 | feature-schema required feature 불가, CPU 주입 효과 판정 불가 | `telemetry_export.py`에 12개 metric group 추가(서비스별 grid coverage는 강제하지 않고 non-empty/finite만 검사) |
| 7 | run manifest에 `docker-desktop-kind`, `v1.36.1` 하드코딩 | provenance 오기록 | API server에서 버전·노드 수·runtime·kernel을 읽어 기록 |
| 8 | `scripts/helm-path.sh`에 Windows 절대경로 | Linux 무의미 | 삭제, `linux/02-install-cli.sh`로 대체 |
| 9 | Chaos Mesh socket이 Docker Desktop 경로 | k3s에서 첫 주입 시 실패(설치는 성공해 보임) | `linux/values/chaos-mesh-k3s.yaml` (`/run/k3s/containerd/containerd.sock`) + capability gate |
| 10 | Prometheus emptyDir/6h, Tempo 3h, Loki 24h | 무인 수집 중 재시작·지연 시 raw 소실 | Linux overlay: 48h retention, local-path PVC, limit 상향 |
| 11 | 장시간 무인 실행·재개 수단 없음 | 1~2주 수집 불가능 | `scripts/run-campaign.py`(완료 pair skip, 미완료 audit에서 정지, pair 간 gate+5분 settle, STOP 파일) + tmux 래퍼 |
| 12 | Python 의존성 파일 없음 | 재설치 불가 | `requirements.txt` (PyYAML, pandas, pyarrow; import 전수 확인) |

참고: 원본 zip의 테스트 62개 중 1개(`test_real_conversion_commands_use_selected_raw_generation`)가 Windows의 긴 경로(MAX_PATH)에서만 실패한다. 짧은 경로에서는 통과하며 Linux와 무관하다. 현재 패키지는 74개 테스트 모두 통과.

## 3. 프로젝트 문서(SentriX Final 컨텍스트)와의 불일치 — 결정 필요

> **2026-10-16 결정:** 1번은 Online Boutique 통일로 확정됐다. 통합 방향·계획은 `docs/PROJECT-DIRECTION.md`.

1. **최종 배포 대상**: 문서는 *Sock Shop on AWS EKS*, 이 셋업은 *Online Boutique on 단일 k3s*.
   - RCAEval 공식 README 기준 RE2-SS(Sock Shop)는 **trace가 없다**(metrics, logs만). RE2-OB는 metrics/logs/traces 모두 있다.
   - 자체 수집 대상이 RE2-OB와 같은 앱이면 서비스 이름·호출 그래프·계측이 같아 "Common Representation" 문제가 크게 줄어든다.
   - 권장: 개발·자체 수집·최종 데모를 **Online Boutique로 통일**하고, Sock Shop은 RE2-SS를 이용한 *교차 시스템 일반화 실험*으로 둔다. EKS는 같은 manifest를 올리는 배포 데모로만 쓰면 비용·복잡도가 작다. → **채택됨.**
2. **fault 집합**: RE2는 시스템마다 cpu, mem, disk, delay, loss, socket 6종 × 서비스 5개 × 3반복 = 90 case. linux-v1은 cpu/pod_failure/delay/loss/surge. **공통은 cpu·delay·loss뿐**이고, linux-v1의 delay/loss는 *edge* 라벨, RE2는 *서비스* 라벨이다. RE2로 학습·자체 데이터로 평가하거나 그 반대를 할 때는 이 매핑 규칙(예: edge → source 서비스)을 사전에 고정해야 한다.
3. **문서의 초기 fault 4종에 memory가 있으나** linux-v1은 memory를 의도적으로 제외(injector·효과 metric 미검증). memory가 필요하면 `linux-v2` cohort로 따로 설계한다.
4. **평가 지표**: AC@k/Avg@k는 RCAEval README에 정식 정의가 없다(예시로 Avg@5만 등장). 논문 본문 정의를 확인해 구현해야 한다. linux-v1 execution-plan은 MRR/Hit@1/Hit@3를 쓰므로 두 체계를 함께 보고하는 편이 안전하다.

## 4. 학교 Linux 머신 관련 위험

| 위험 | 확인 방법 | 대응 |
|---|---|---|
| sudo 없음 | `00-preflight.sh` | 관리자에게 k3s 설치/`sch_netem`/linger 요청 |
| 야간 재부팅·로그아웃 | uptime, linger | tmux + 재개 가능한 queue. 재부팅 금지 기간 확보 요청 |
| 자원 부족 (설계 가정 16 vCPU/64 GiB) | preflight | 8 vCPU/16 GiB면 capability + pilot까지만. 앱·관측 자원 경쟁을 기록 |
| 디스크 (≈1 GiB/run) | preflight | 138 run ≈ 140 GiB + PVC. 주기적으로 외부 저장소로 archive(해시 유지) |
| 네트워크 디스크 홈 | preflight FS 종류 | 로컬 디스크 경로에 설치 |
| 프록시/방화벽 | preflight 외부 접속 | 이미지 pull 실패 시 미러/프록시 설정 |
| 공용 머신의 다른 부하 | — | run마다 node 상태가 fingerprint/manifest에 남으므로, 다른 사용자의 부하가 있던 구간은 사후 제외 판단 |

## 5. 아직 남은 일 (Linux 실측 또는 별도 구현 필요)

- capability 증거, capacity C, fault 강도 동결 — `linux/` 절차대로 실측.
- 앱 Pod edge에 대한 qdisc/packet counter 실측 수집기(privileged evidence, 모델 입력 제외). 현재는 capability probe와 cAdvisor drop rate까지만.
- RTT/TCP retransmission feature: node-exporter가 꺼져 있고 per-pod retrans는 cAdvisor 기본값에 없다. 모델 feature로 쓰려면 control/fault 모두에 동일하게 관측되는 source를 먼저 정해야 한다(feature-schema `required_for_faults`).
- window 라벨 생성기(v4: 사용자 transaction 기반 window impact, transition/recovery 마스크), `cases.parquet`, fold index, topology, model view, 로그 sanitization — 수집이 시작된 뒤 첫 pair 데이터로 구현·검증하는 것이 효율적이다.
- 버전 고정값(k3s v1.33.4+k3s1, k6 v0.57.0, Chaos Mesh chart 2.7.2)은 설치 시점에 존재·호환 여부를 확인하고 `05-verify.sh` 기록으로 확정.

## 6. RE2 데이터

`rcaeval/download_re2.sh`는 RCAEval 코드가 쓰는 공식 Zenodo URL(record 14590730)에서 RE2-OB/SS/TT를 받는다. `rcaeval/inventory_re2.py`는 받은 파일을 직접 읽어 case 수, 파일 구성, metric/log/trace 컬럼, `inject_time` 형식, sampling 간격, 주입 전후 길이를 표로 만든다. 프로젝트 문서의 Dataset 질문 1~6은 이 결과로 답한다(추측 금지 원칙).
