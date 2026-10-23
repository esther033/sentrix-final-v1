# SentriX 마일스톤 — 완료와 남은 일

기준일: 2026-10-19 · 기준 문서: [`sentrix-project-context.md`](../sentrix-project-context.md)
근거 기록: `docs/SETUP-REVIEW-20261016.md` 7절(학교 PC 실측), git 브랜치 `school-pc` 커밋.
남은 일정의 날짜는 **추정**이다. 학교 PC 가동 여건(재부팅, 사용 가능 시간)에 따라 달라진다.

## 한눈에 보기

| 구분 | 마일스톤 | 상태 | 날짜 |
|---|---|---|---|
| 이전 | L1. Windows 관측 경로 (M1A/M1B) | 완료 | ~2026-09 |
| 이전 | L2. Windows 장애 데이터 (M2) | 부분 완료, 동결 | ~2026-09-26 |
| 설계 | D0. 셋업 검토·보완 패키지 | 완료 | 10/16 |
| 설계 | D1. 대상 통일·수집 계획 결정 | 완료 | 10/16~19 |
| 수집 준비 | S0. 환경 점검 (preflight) | 완료 | 10/16 |
| 수집 준비 | S0.5. PC 맞춤 코드 수정 | 완료 | 10/16 |
| 수집 준비 | S1. k3s·도구 설치 | 완료 | 10/16 |
| 수집 준비 | S2. 스택 배포·검증 | 완료 | 10/16 |
| 수집 준비 | S3. 장애 주입 검증 (capability) | 완료 | 10/16 |
| 수집 준비 | S4. 처리 용량 C 측정 | 완료 (C = 6 tx/s) | 10/16~19 |
| 수집 준비 | **S5. 시험 pair 4개 + 2차 3개** | 완료 | 10/19~22 |
| 수집 준비 | S6. 강도 동결·정식 스케줄 | 완료 (seed 20261023, 태그 linux-v1-frozen-20261023) | 10/23 |
| 수집 | S7. 첫 정식 pair | 완료 (206-40: cpu-productcatalogservice-r01 valid) | 10/23 |
| 수집 | S8. Tier 1 (cpu·delay·loss 45 pair) | 남음 | 10/21~11/2 |
| 수집 | S9. Tier 2 (pod 15 pair) | 남음 | 11/3~11/5 |
| 수집 | S10. Tier 3 (surge 9 pair) + 재시도 | 남음 | 11/6~11/13 |
| 연구 | R1. RE2-OB 확보·구조 확인 | 남음 (병행) | 10/20~ |
| 연구 | R2. RE2-OB feature·baseline | 남음 (병행) | 10/21~11/7 |
| 연구 | R3. 평가 지표 정의·평가기 | 남음 (병행) | 10/21~10/31 |
| 데이터셋 | B1. linux-v1 데이터셋 빌드 | 남음 | 11/3~11/14 |
| 모델 | E1. 학습·평가 | 남음 | 11/10~11/21 |
| 제품 | P1. sentrix-core | 남음 | 11/17~11/28 |
| 제품 | P2. model-server | 남음 | 11/17~11/28 |
| 제품 | P3. dashboard | 남음 | 11/24~12/3 |
| 제품 | P4. 데모 리허설 | 남음 | 12/1~12/5 |
| 마무리 | F1. 보고서·발표 | 남음 | 12/1~12/12 |
| 선택 | O1. 공개 저장소 정리 | 선택 | 수집 후 |

---

## 완료된 마일스톤

### L1. Windows 관측 경로 (M1A/M1B) — 완료

- Docker Desktop 단일 노드에 Online Boutique + OTel Collector + Prometheus + Tempo + Loki, k6 사용자 거래, run 단위 export와 품질 게이트를 구현.
- 상세: `docs/MILESTONE1.md`, `docs/archive/sentrix-project-context-legacy-m1.md` 16절.

### L2. Windows 장애 데이터 (M2) — 부분 완료, 동결

- 공식 사용 가능 6 run(fault 3 + control 3): cpu_saturation(영향 미확인), pod_failure, traffic_surge(checkoutservice / frontend).
- network delay·loss는 확보하지 못함. 전체 runs/ 약 27.6 GiB(시험 run 포함).
- 결정: `legacy-m2` cohort로 보존, linux-v1과 합치지 않음. 상세: `docs/DATA-EXTRACTION-INVENTORY.md`.

### D0. 셋업 검토·보완 패키지 — 완료 (10/16)

- 원본 셋업(2026-10-14) 검토 결과 수정한 것:
  - network edge 장애의 source/destination 치환 버그 (그대로였다면 delay·loss 30 case가 잘못 수집됨)
  - 엔드포인트 환경변수화와 NodePort (port-forward 의존 제거)
  - pair 순서 2종 지원과 fault-first 사후 매칭(`scripts/evaluate-pair.py`)
  - 138 profile / schedule 생성기(`scripts/generate-campaign.py`, seed 재현, 순서·onset 균형)
  - k6 workload seed 적용
  - throttling·limit·Ready·재시작·drop·수집기 상태 metric 추가
  - 재개 가능한 캠페인 queue(`scripts/run-campaign.py`)
  - 설치·검증·capability·capacity 스크립트(`linux/`)
  - RE2 다운로드·inventory 도구(`rcaeval/`)
- 테스트 74개 통과. 커밋 `68c97f0` (main).

### D1. 대상 통일·수집 계획 결정 — 완료 (10/16~19)

- Online Boutique 단일 대상, Sock Shop/EKS 폐기. 근거: RE2-OB와 같은 앱, RE2-SS trace 없음, 기존 파이프라인이 OB 기준.
- 원래 계획(69 pair) 유지. 빠른 수집안(45 case, 약 5시간)은 검토 후 채택하지 않음.
- 하루 블록 운영 + tier 순서 실행 결정.

### S0. 환경 점검 — 완료 (10/16, PC 206-40)

- 첫 PC 205-13에서 `/var` 공간 부족(14 GiB)과 kubectl KUBECONFIG 문제를 발견한 뒤 206-40으로 이동.
- 206-40: 24 vCPU, RAM 15 GiB, HDD 여유 847 GiB, sch_netem 있음, cgroup v2, 외부 접속 정상.
- 위험 발견: 듀얼부트 시계 +9h, 47일 18회 부팅(최장 3.7일), 공용 PC, python3-venv 없음.
- preflight 오판정 버그 3개 재현.
- 증거: `linux/out/preflight-206-40-20261016T052659Z/`.

### S0.5. PC 맞춤 코드 수정 — 완료 (10/16)

- preflight 버그 수정: curl 판정, 비밀번호 필요 sudo, `/var` 검사, RTC·NTP 표시, venv 검사.
- KUBECONFIG 기본값을 모든 스크립트와 Python 진입점에 적용.
- RAM 15 GiB 대응: 보존 12h, Prometheus 2Gi / Tempo 3Gi / Loki 1Gi limit.
- 수집 전 NTP 게이트와 run별 boot_id·부팅 시각 기록(`scripts/host_state.py`).
- 캠페인 queue 블록 운영 기능: `--fault-type`, `--stop-before`, `--min-free-gib`, queue.log 닫기.
- 테스트 89개 통과. 커밋 `3a5ddd4`.

### S1. k3s·도구 설치 — 완료 (10/16)

- k3s v1.33.4+k3s1(바이너리 sha256 공식값 일치), sch_netem 상시 로드, inotify 상향, containerd socket 확인.
- kubectl wrapper로 KUBECONFIG 문제 해결.
- helm v3.17.3, k6 v0.57.0, `.venv`에서 테스트 89개 통과.
- 메모리 축소 승인안 적용: Loki 결과 캐시·rules sidecar 끔, Chaos DNS 서버 끔, kube-state-metrics·configmap-reload limit 지정. limit 합계 11.2 → 10.2 GiB.
- 커밋 `a404928`.

### S2. 스택 배포·검증 — 완료 (10/16)

- GitHub release가 90~260초 걸리는 문제 때문에 차트를 미리 받아(`linux/fetch-charts.sh`, digest 확인) 로컬 tgz로 설치.
- 배포 6분 10초, 이미지 다운로드 실패 0, OOM 0. 05-verify 12개 항목 PASS(엔드포인트 4, series 8), scrape 5초, 보존 12h 확인.
- 유휴 메모리: 노드 6.5 GiB, available 9.4 GiB.
- 증거: `linux/out/deploy-20261016T064454Z/`(image digest 포함). 커밋 `d6801ee`.

### S3. 장애 주입 검증 — 완료 (10/16)

- pod.sh 버그(줄바꿈 없는 출력에서 `read` 실패)를 고친 뒤 cpu·pod·network 모두 PASS.
  - CPU: 0.4999 core + throttling, 제거 후 원복
  - delay: +100 ms, 다른 경로 영향 없음
  - loss: 해당 경로에서 8.7~11.3 %, 다른 경로 0 %
  - pod: Ready false→true, UID 동일
- 발견: pod-failure 효과가 요청 후 약 31초 늦게 나타남(종료 대기 30초). 라벨은 효과 관측 시각 기준으로 잡아야 함.
- 증거: `linux/out/capability-20261016T071128Z/`. 커밋 `82ad803`.

### S4. 처리 용량 C 측정 — 완료 (10/16~19)

- 1·2·3·4 tx/s PASS(10/16). PC 종료로 중단 후, 10/19에 6·8 tx/s 이어서 측정. p99 기준 500 ms 고정 유지.
- **C = 6 tx/s**(8 tx/s에서 p99 545 ms로 FAIL). 평소 부하 0.4C = 2.4 tx/s, surge 3.6 / 4.8 / 6.0 tx/s.
- 25분 run 약 2.5 GiB, 후처리 약 20분, 138 run 약 344 GiB(디스크 충분), pair 약 95분, 69 pair 약 109시간.
- Tempo 최대 78 %(8 tx/s) → limit 상향 필요.
- 증거: `runs/_calibration/capacity-merged-20261019/`, `linux/out/capacity-curve-20261019.csv`. 커밋 `7a9a478`, `cd0da6c`.

---

## 진행 중

### S5. 시험 pair 4개 — 진행 중 (10/19~20)

| 할 일 | 완료 기준 |
|---|---|
| 커널 7.0.0-38로 재부팅, NTP·Pod·sch_netem 확인, capability·05-verify 재실행 | 모두 PASS |
| Tempo limit 3Gi → 4Gi | helm 반영, NodePort 유지, 05-verify PASS |
| calib 스케줄 생성(`--campaign-id calib-linux-v1 --capacity-tps 6`) | target_rps 2.4, phase 합 1500초 |
| 시험 pair: cpu-checkoutservice, delay-front-product, loss-front-product, pod-checkoutservice | 각 pair의 두 run 모두 pipeline complete, assessment valid, fault-first면 pair-assessment valid |
| 실제 효과와 사용자 영향 확인, pod 효과 지연 측정 | pair별 효과 증거, impact 판정 수치 |
| 강도 확정안 제안 | fault별 유지/상향 근거, surge 단계별 예상 |

산출물: 시험 run 8개, 강도 제안, SETUP-REVIEW 기록. 예상 약 7시간(점검 40분 + pair 4개 × 95분).

**진행 상황 (10/20 기준, SETUP-REVIEW 7.14~7.16).**
- 1차 r01(4 pair, 7.14): 완료. 사용자 영향은 pod_failure만 있었다. delay·loss는 무효과였는데, 원인은 Service ClusterIP 경로가 tc 필터에 걸리지 않은 것이다. cpu(worker 1)는 영향이 없었다.
- 보완(7.15): edge NetworkChaos에 도착 ClusterIP를 externalTargets로 추가했다(방법 A, 승인). cpu는 WORKERS/LOAD 파라미터(4/100)로 바꿨다. surge 단계는 0.8/1.0/1.33C다. capability가 Service 경로까지 검사한다. 커밋 `d0daa87`.
- 2차 r02(`calib2-linux-v1`, 7.16):
  - cpu-checkoutservice-r02: 영향 있음(latency, 짧은 스파이크). pair는 후처리 deadline(HDD cold cache)으로 failed이고, deadline을 180 → 900 s로 수정했다.
  - delay-front-product-r02: 호출당 약 +100 ms(p50 0.1 → 114 ms), 다른 edge는 ≤ +1.4 ms, 사용자 영향 큼(p50 3.2 s).
  - loss-front-product-r02: 주입은 succeeded로 기록됐으나 span에 손실 흔적이 전혀 없다. app 경로 적용 여부 진단이 필요하고, 5 %는 그 뒤의 후보다.
- 강도 승인(10/22, 동결 전): cpu worker 4 / load 100, delay 100 ms / jitter 10 ms, pod-failure 그대로, surge 0.8/1.0/1.33C.
- loss 진단(7.17, 10/22): 커널 7.0 netem이 상관 loss(`loss 2% 25%`)에서 하나도 버리지 않았다. 템플릿 correlation을 0으로 바꿨다. capability에 netem drop 검사를 추가했다(corr 25면 FAIL, 수정 후 PASS). run-attended가 fault-record에 출발 pod의 tc·ipset·nstat 증거를 남긴다.
- 3차(`calib3-linux-v1-loss-front-product-r02`): complete/valid. drop 2.04 %, 재전송 +997, frontend→productcatalog p99 0.8 → 205 ms, 사용자 p50/p99 35/129 → 104/521 ms(impacted). 2 % 유지, 5 % 제안 없음.
- S6로 넘어감(10/23).

---

## 남은 마일스톤

### S6. 강도 동결·정식 스케줄 — 완료 (10/23, SETUP-REVIEW 7.18)

- delay correlation 0, capability network 재검사 PASS(지연 99.9 ms, jitter 표준편차 5.7 ms).
- 수집 ID(SENTRIX_ENVIRONMENT_ID > local.env > hostname), 저장소 `seNNTRIX/sentrix-collection`, NEW-PC·README 2대 기준.
- fault-params frozen(capacity 6, cpu 4/100, delay 100/10/corr 0, loss 2/corr 0, pod 그대로, surge 0.8/1.0/1.33C), redis·loki-gateway digest 고정.
- seed 20261023, 69 pair, shard 206-40 35 / 206-39 34(pair order 균형 추가), 태그 `linux-v1-frozen-20261023`.

아래는 원래 계획이다.

#### S6 계획 (10/20~21, 약 1시간)

- 사람이 강도 승인 → `campaigns/linux-v1/fault-params.yaml`에 capacity 6, 강도, calibration 근거 run ID 기록, `status: frozen`.
- 템플릿에 하드코딩된 강도(CPU worker·load 등)를 params로 받게 수정 + 테스트.
- `redis:alpine` 등 가변 태그를 실행된 digest로 고정.
- 정식 seed를 정해 기록하고 69 pair 스케줄 생성. tier별로 걸렀을 때 반복 1·2·3이 시간축에 고르게 섞이는지 확인.
- 완료 기준: 테스트 통과, `schedule.json`·profile 138개, frozen 파라미터 commit.

### S7. 첫 정식 pair — 완료 (10/23)

- 206-40 shard(35 pair) 수집을 10/23 15:18 KST에 시작했다(밤샘, 종료 시각 제한 없음).
- #1 linux-v1-cpu-productcatalogservice-r01: complete, 두 run assessment valid, environment_id 206-40, impacted(latency), 5,172 MiB, 16:57 KST 종료.
- #4 linux-v1-pod-checkoutservice-r02: complete, valid, impacted, 18:33 KST 종료.
- #6 linux-v1-delay-front-recommendation-r02(첫 network pair): complete, valid, impacted(latency·checkout). fault-record netns_evidence: netem `delay 100ms 10ms` sent 7,248 pkt(applied), ipset에 recommendation pod IP와 ClusterIP, TcpRetransSegs +4. 간선 p50 0.9 → 103.3 ms, 해제 후 0.9 ms. 20:13 KST 종료.
- 블록 일지는 `docs/pc/206-40.md`에 있다.

#### S7 계획 (10/21, 약 2시간)

- `--max-pairs 1`로 Tier 1 첫 pair만 실행, 끝까지 확인. 블록 운영 절차(시작 점검, 정지, 재부팅 복구)를 실제로 한 번 수행.

### S8~S10. 정식 수집 (10/21~11/13)

| tier | 내용 | 블록 (8 h 기준 5 pair) | 예상 기간 |
|---|---|---|---|
| S8 Tier 1 | cpu·delay·loss 45 pair | 9블록 | 10/21~11/2 |
| S9 Tier 2 | pod_failure 15 pair | 3블록 | 11/3~11/5 |
| S10 Tier 3 | traffic_surge 9 pair | 2블록 | 11/6~11/9 |
| 재시도 | 실패 pair(10~15 % 가정) | 1~3블록 | ~11/13 |

매 블록: 시작 점검 → `linux/campaign/start.sh <tier> --stop-before HH:MM` → 종료 보고(완료/실패, 디스크, 남은 pair). 실패 pair는 새 attempt ID 재시도 또는 제외 결정. tier가 끝나기 전에 다음 tier로 넘어가지 않는다.

완료 기준: tier별 모든 pair가 완료되었거나 사유가 기록된 제외 결정. tier별 impact 확인률 보고.

### R1. RE2-OB 확보·구조 확인 (병행, 10/20~)

- `rcaeval/download_re2.sh OB`, `rcaeval/inventory_re2.py`.
- 확인할 것: case 구조, 대상 서비스, fault 종류, metric 컬럼, log/trace 형식, inject_time, sampling 간격, 주입 전후 길이.
- 수집 블록과 겹치면 디스크 여유를 먼저 확인한다.

### R2. RE2-OB feature·baseline (병행, 10/21~11/7)

- RE2-OB에서 30 s window feature v0(node/edge), case-level split.
- baseline: 통계 threshold, 빈도 prior, random, RF/LightGBM, joint classification.
- node/edge ranking 첫 모델. 하이퍼파라미터를 여기서 고정한다(linux-v1 CV 전에).

### R3. 평가 지표 정의·평가기 (병행, 10/21~10/31)

- RCAEval 논문에서 AC@k, Avg@k 정의 확인. Hit@k, MRR, detection 지표, case 단위 bootstrap 구현과 테스트.

### B1. linux-v1 데이터셋 빌드 (11/3~11/14)

Tier 1이 끝나면 시작해서 이후 tier를 추가 반영한다.
- `cases.parquet`: pair당 1행, 판정(data_valid, injection_valid, impact_confirmed, recovery_status)과 제외 사유.
- `topology.json`: trace에서 관측된 노드와 edge(주입 정보로 만들지 않음).
- window 라벨: 경계·warmup·전환·회복 중 제외, 효과 관측 시각 기준(pod는 Ready=false).
- model view: node/edge feature, mask, p90/p99 표본 수 기준. 금지 feature·QA 파일 누수 검사 테스트.
- 로그 정제(서비스명·Pod명·endpoint 제거), fold index(반복 기준 3-fold), build-summary(입력 해시, fold별 fit 범위).
- 요약: tier·fault·대상별 영향 확인률, 학습 가능 case 수, window 수(사유별), 정상 관측 시간.

### E1. 학습·평가 (11/10~11/21)

- linux-v1 3-fold CV(out-of-fold 예측 case당 1개), LOSO/LOEO 일반화.
- RE2-OB → linux-v1, linux-v1 → RE2-OB 교차 평가(cpu·delay·loss).
- detection과 RCA 분리 보고, no-impact 그룹 별도 보고, 신뢰구간.

### P1~P4. 제품·데모 (11/17~12/5)

| 마일스톤 | 내용 |
|---|---|
| P1 sentrix-core | Prometheus·Tempo·Loki 실시간 query, 30 s window, `features/` 공유 코드로 feature 생성, 진단 저장 |
| P2 model-server | FastAPI. detection score + node/edge ranking + fault type 응답 schema 확정 |
| P3 dashboard | topology, 서비스 상태, 후보 순위, 근거 표시 |
| P4 데모 리허설 | 학교 PC에서 live 장애 주입 → 탐지 → 순위 표시까지 end-to-end |

### F1. 보고서·발표 (12/1~12/12)

- benchmark lane(RE2-OB)과 product lane(linux-v1) 결과, 실패 사례, 한계(5종 장애, 강도 1개, 단일 PC, tier-날짜 겹침 등).
- 실측 기록과 근거 경로 정리. 제출 마감일은 확인 후 이 표를 조정.

### O1. 공개 저장소 정리 (선택, 수집 후)

- 문서의 학교 PC 내부 정보 일반화, `incidents/`·`samples/`의 Windows 절대 경로 정리, 비밀 정보 재점검, LICENSE 결정.
- 공개는 과거 커밋 기록이 따라가지 않도록 새 공개 저장소로.

---

## 진행을 막을 수 있는 것

| 항목 | 영향 | 대응 |
|---|---|---|
| 학교 PC 사용 확보(약 3주) | 수집 일정 | 관리자·조교 요청 |
| 자동 커널 업데이트·재부팅 | pair 손실, 커널 혼재 | 블록 시작 전 재부팅 처리, 업데이트 보류 요청 |
| 시험 pair에서 영향이 안 나는 대상 | 학습 case 감소 | 강도 상향 또는 no-impact 그룹으로 보고 |
| Tempo 메모리 | trace 누락으로 run 무효 | limit 4Gi, 시험 pair에서 확인 |
| 네트워크(학교망) | 다운로드·Claude 연결 끊김 | 캐시, tmux 안에서 측정 |
