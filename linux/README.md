# 학교 Linux에서 데이터 수집 — 실행 순서

이 디렉터리는 `linux-v1` 캠페인을 **단일 Ubuntu 머신 + k3s(containerd)** 에서 돌리기 위한 설치·검증·실행 계층이다.
각 단계는 증거 파일을 `linux/out/` 아래에 남긴다. 앞 단계가 FAIL이면 다음 단계로 가지 않는다.

```
00 preflight (sudo 불필요, 읽기 전용)  →  결과 보고 후 진행 여부 결정
01 k3s 설치 (sudo)  →  02 helm/k6  →  03 Python venv + 테스트
04 스택 배포  →  05 엔드포인트·series·digest 확인
capability (CPU / pod / network edge)  →  capacity C 측정
fault-params 동결  →  schedule 생성  →  시험 pair 2개  →  (승인 후) 전체 캠페인
```

## 0. 압축 해제 위치

홈 디렉터리가 NFS 같은 네트워크 디스크면 lock/fsync가 느리거나 동작하지 않을 수 있다. 가능하면 로컬 디스크(예: `/data/$USER/sentrix`)에 푼다.
`00-preflight.sh`가 파일시스템 종류를 확인해 준다.

## 1. Preflight — 이 머신에서 가능한지부터 확인

```bash
bash linux/00-preflight.sh
```

`linux/out/preflight-*/summary.txt`에 PASS/WARN/FAIL이 나온다. 특히 확인할 것:

| 항목 | 왜 중요한가 |
|---|---|
| sudo | k3s/containerd 설치에 필요. 없으면 관리자 요청(아래) |
| sch_netem | 없으면 network delay/loss 30 case 전체가 불가능 |
| CPU/RAM | 설계 가정은 16 vCPU/64 GiB. 8 vCPU/16 GiB면 pilot까지만 권장 |
| 디스크 | 기존 cohort 실측 약 1 GiB/run → 138 run ≈ 140 GiB + backend PVC |
| linger / uptime | 로그아웃·야간 재부팅 시 장시간 queue가 끊긴다 |
| 외부 접속 | get.k3s.io, ghcr.io, docker.io, charts.chaos-mesh.org, zenodo.org |

**관리자 요청 예시** (sudo가 없을 때): k3s 설치(`linux/01-install-k3s.sh` 내용), `sch_netem` 모듈 로드, `loginctl enable-linger <user>`, 캠페인 기간(약 1~2주) 재부팅 유예.

## 2. 설치

```bash
bash linux/01-install-k3s.sh      # sudo. traefik/servicelb 비활성, sch_netem 상시 로드
bash linux/02-install-cli.sh      # ~/.local/bin 에 helm, k6
export PATH="$HOME/.local/bin:$PATH"
bash linux/03-python-env.sh       # .venv + requirements.txt + 회귀 테스트
```

버전은 `linux/config/versions.env`에 고정되어 있다. k3s/k6/Chaos Mesh 버전은 설치 목표값이며, 실제 설치된 버전은 05단계가 기록한다(그 기록이 provenance다).

## 3. 배포와 검증

```bash
bash linux/04-deploy-stack.sh
bash linux/05-verify.sh
```

- Docker Desktop용 values는 그대로 두고 `linux/values/*.yaml` overlay로 차이만 덮는다: Chaos Mesh socket `/run/k3s/containerd/containerd.sock`, retention 12h, local-path PVC(Prometheus 20Gi/Tempo 30Gi/Loki 15Gi), 메모리 limit Prometheus 2Gi/Tempo 3Gi/Loki 1Gi (RAM 15 GiB인 206-40 기준, `docs/SETUP-REVIEW-20261016.md` 7절).
- frontend/Prometheus/Tempo/Loki는 고정 NodePort(30080/30090/30320/30310)로 노출된다. **port-forward 불필요.** URL은 `linux/config/endpoints.env`에서 모든 스크립트로 주입된다.
- `05-verify.sh`는 throttling/readiness/restart 등 새 feature가 쓰는 Prometheus series가 실제로 존재하는지도 검사한다. FAIL이면 export가 incomplete가 되므로 캠페인 전에 반드시 해결한다.

## 4. Capability gate (앱이 아닌 전용 probe Pod에서)

```bash
bash linux/capability/run-all.sh
kubectl delete ns sentrix-probe
```

| probe | PASS 조건 (`summary.json`) |
|---|---|
| cpu | 주입 중 ≥0.40 core, `nr_throttled` 증가, 제거 후 ≤0.10 core, `cpu.max` 불변 |
| pod | 주입 중 Ready=false 관측, 제거 후 Ready=true, Pod UID 동일 |
| network | delay: RTT +80 ms 이상, 다른 경로 영향 없음, 제거 후 원복, qdisc 원복 / loss 10%: ≥4% 손실, 다른 경로 ≤1%, 제거 후 ≤1% |

## 5. Capacity C 측정과 파라미터 동결

```bash
set -a; . linux/config/endpoints.env; set +a
.venv/bin/python -B scripts/capacity-sweep.py --rates 1,2,3,4,6,8 --minutes 10
```

판정식은 스크립트 docstring과 `runs/_calibration/capacity-*/capacity-result.json`에 기록된다.
그 다음 `campaigns/linux-v1/fault-params.yaml`에 `capacity_tps`, 교정 결과로 정한 fault 강도, `calibration_evidence`를 채우고 `status: frozen`으로 바꾼다. **동결 전 스케줄은 draft로 표시되고 정식 캠페인 실행이 거부된다.**

## 6. 스케줄 생성

```bash
.venv/bin/python -B scripts/generate-campaign.py --seed <정한 seed> --dry-run
.venv/bin/python -B scripts/generate-campaign.py --seed <정한 seed>
```

- 138 profile → `workload/profiles/linux-v1/`, 스케줄 → `campaigns/linux-v1/schedule.{json,csv}`
- 셀(23개 = fault type × target)마다 반복 3회, pair order 2/1 또는 1/2, 전체 34/35
- 셀 내 onset 3개는 서로 다르고 전체 onset 분포 차이 ≤1, 반복 1/2/3이 시간축 3등분 각각에 고르게 섞임
- 같은 seed·입력이면 바이트 단위로 동일. 다른 내용으로 덮어쓰기는 거부한다.

## 7. 시험 pair → 전체 캠페인 (학교 PC 206-40: 하루 블록 운영)

206-40은 공용·듀얼부트 PC라 며칠 연속 켜 두기 어렵다(8/31~10/16 부팅 18회, 최장 연속 가동 약 3.7일). 그래서 69 pair를 한 번에 돌리지 않고 **하루 8~10시간 블록**으로 나눠 돌린다. queue는 완료된 pair를 건너뛰므로 블록을 몇 번 끊어도 같은 schedule이 그대로 이어진다.

### 7.1 시험 pair (calibration, 정식 ID와 분리)

```bash
# 시험 수집용 스케줄 (draft, 별도 ID 공간)
.venv/bin/python -B scripts/generate-campaign.py --seed 1 --campaign-id calib-linux-v1 --capacity-tps <측정한 C>
# CPU 1 pair, delay 1 pair
linux/campaign/start.sh --schedule campaigns/calib-linux-v1/schedule.json --allow-draft \
  --only calib-linux-v1-cpu-checkoutservice-r01 --only calib-linux-v1-delay-front-product-r01
tmux attach -t sentrix-campaign
```

강도 동결 → 정식 스케줄 생성(6절) → 아래 블록 운영 (승인 후에만).

### 7.2 Tier 순서

공통 fault(RE2-OB와 겹치는 cpu/delay/loss)를 먼저 끝내서, 중간에 PC를 잃어도 교차 평가에 쓸 수 있는 셀이 먼저 완성되게 한다. 각 tier 안에서는 schedule 순서(반복 1/2/3이 시간축에 섞인 순서)를 그대로 따른다.

- Tier 1 (45 pair): `--fault-type cpu_saturation --fault-type network_delay --fault-type packet_loss`
- Tier 2 (15 pair): `--fault-type pod_failure`
- Tier 3 (9 pair): `--fault-type traffic_surge`

### 7.3 블록 시작 전 점검 (매일)

```bash
cd ~/Documents/sentrix-final-v1-main
# 1) 부팅 직후면 NTP 동기화를 기다린다 (Windows 사용 후 시계가 +9h 틀어져 있을 수 있음)
timedatectl show -p NTPSynchronized --value      # yes 가 나올 때까지 대기
timedatectl                                      # Local time 이 실제 시각과 맞는지 눈으로 확인
# 2) 클러스터·백엔드 상태
export PATH="$HOME/.local/bin:$PATH"; set -a; . linux/config/endpoints.env; set +a
kubectl get nodes; kubectl -n sentrix get pods  # 모두 Running/Ready
kubectl -n sentrix get stresschaos,networkchaos,podchaos   # 남은 객체 없음 (있으면 7.5)
bash linux/05-verify.sh                          # endpoint·series PASS
# 3) 디스크·이전 블록 결과
df -h ~ /var/lib/rancher
tail -5 runs/_campaign/linux-v1/queue.log
ls runs/_campaign/linux-v1/STOP 2>/dev/null && rm runs/_campaign/linux-v1/STOP   # 지난 블록의 stop.sh 표시 제거
```

run-attended.py는 NTPSynchronized=yes가 아니면 run 시작을 거부하고, queue의 pair 간 gate도 같은 조건을 확인한다. 각 run의 `runtime.json`과 `run-manifest.yaml`에는 boot_id·부팅 시각·NTP 상태가 남는다.

### 7.4 블록 실행과 종료

```bash
# 예: 18:30 까지 끝나는 pair만 시작 (pair 예상 95분 + settle 5분으로 판단)
linux/campaign/start.sh --fault-type cpu_saturation --fault-type network_delay --fault-type packet_loss \
  --stop-before 18:30
tmux attach -t sentrix-campaign            # 분리: Ctrl-b d
```

- `--stop-before HH:MM`: 지금 시작하면 그 시각까지 끝나지 않을 pair는 시작하지 않고 정상 종료한다. 자정을 넘기는 블록은 다음 날 HH:MM으로 계산한다.
- `--min-free-gib` (기본 20): pair 시작 전 `runs/`나 `/var/lib/rancher` 여유가 이보다 적으면 정지(rc 4).
- 일찍 끝내야 하면 `linux/campaign/stop.sh` — 진행 중인 pair(export·fault 제거 포함)를 끝낸 뒤 멈춘다. 다음 블록 전에 STOP 파일을 지운다(7.3).
- 블록 중에는 로그아웃하지 않는다(linger=no면 tmux도 죽는다). 화면 잠금만 한다.
- 블록이 끝나면 `queue.log`의 마지막 줄과 `audits/pair-*/status.json`으로 완료 pair 수를 기록한다.

### 7.5 재부팅·전원 차단 후 복구

1. NTP 동기화 확인(7.3의 1).
2. `kubectl get nodes` Ready, `kubectl -n sentrix get pods` 전부 Ready가 될 때까지 기다린다(k3s는 systemd 서비스라 부팅 시 자동 시작).
3. 남은 Chaos 객체가 있으면 `bash linux/campaign/emergency-cleanup.sh` (증거는 `linux/out/emergency-*`).
4. `bash linux/05-verify.sh` PASS 확인. Tempo/Prometheus가 WAL replay 중이면 Ready까지 몇 분 걸릴 수 있다.
5. 끊긴 pair는 `audits/pair-<fault-id>/status.json`이 미완료로 남아 queue가 그 자리에서 멈춘다(rc 2). **같은 run ID는 재사용하지 않는다.** 재시도(새 attempt ID)할지 `runs/_campaign/linux-v1/decisions.yaml`의 `excluded_pairs`에 넣을지 사람이 결정하고 기록한다.
6. 같은 tier 명령으로 다시 `linux/campaign/start.sh` — 완료 pair는 건너뛴다.

### 7.6 예상 일정

- 순수 실행 86~109시간(69 pair × 75~95분) + 재시도.
- 하루 8~10시간 블록이면 블록당 5~6 pair(시작·점검·마지막 pair 대기로 실효 7~9시간) → 순수 실행만 12~15일, 재시도·재부팅 복구·주말을 포함하면 **약 2.5~3.5주**.
- Tier 1(45 pair)만 약 8~10 블록.

한 pair만 수동으로 돌릴 때:

```bash
set -a; . linux/config/endpoints.env; set +a
.venv/bin/python -B scripts/run-matched-pair.py \
  --control-id linux-v1-control-cpu-checkoutservice-r01 --fault-id linux-v1-cpu-checkoutservice-r01 \
  --control-profile workload/profiles/linux-v1/linux-v1-control-cpu-checkoutservice-r01.json \
  --fault-profile workload/profiles/linux-v1/linux-v1-cpu-checkoutservice-r01.json
# pair_order는 profile에 저장된 값을 따른다. --dry-run 으로 실행될 명령만 볼 수 있다.
```

- queue는 재시작 가능하다: 완료된 pair는 건너뛰고, 미완료 audit가 있으면 **멈추고 사람의 결정을 기다린다**(같은 run ID 재사용 금지).
- pair 사이마다 NTP 동기화 + Chaos 잔류 없음 + 모든 Pod Ready 확인 → 5분 정상 관찰 → 다시 확인.
- 전원 차단 등으로 fault가 남았으면: `bash linux/campaign/emergency-cleanup.sh`

## 시간·용량 산정

| 단계 | 시간 |
|---|---|
| preflight~05 | 반나절 (이미지 pull 속도에 좌우) |
| capability | 약 20분 |
| capacity sweep 6 rate × 10분 + export | 약 2~3시간 |
| 시험 2 pair | 약 3시간 |
| 전체 69 pair | 86~109시간 순수 실행 (pair당 75~95분) + 재시도. 206-40 하루 블록 운영 시 약 2.5~3.5주 (7.6) |
