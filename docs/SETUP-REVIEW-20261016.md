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

## 7. Linux 실측 수정 (학교 PC 206-40)

대상 PC: 206-40 (Ubuntu 24.04.5, i7-13700 24 vCPU, RAM 15 GiB + swap 4 GiB, HDD 931.5G에 LVM ext4 단일 파티션 — `/`·`/var`·`/home` 공유, 여유 847 GiB, NVMe에는 Windows). 0단계 증거: `linux/out/preflight-206-40-20261016T052659Z/` (수정 전), 수정 후 재실행: `linux/out/preflight-206-40-20261016T054655Z/`. 이 절의 변경은 **코드·문서만** 고쳤고 sudo·k3s 설치·배포는 아직 하지 않았다.

### 7.1 저장소
- 받은 폴더는 GitHub ZIP(`.git` 없음)이었다. `esther033/sentrix-final-v1`을 clone해 `diff -rq`로 내용이 완전히 같음을 확인한 뒤 그 `.git`을 이 폴더에 붙이고 `school-pc` 브랜치를 만들었다. 이유: 실습 PC 자리를 옮겨도 작업을 잃지 않게 단계마다 push하기 위해.

### 7.2 preflight 버그 (`linux/00-preflight.sh`)
| 문제 | 실측 | 수정 |
|---|---|---|
| curl 실패 시 `-w %{http_code}`가 `000`을 찍고 `|| echo 000`이 또 붙어 `000000` → PASS | 없는 호스트로 재현 | curl 종료코드로 판정, 종료코드를 메시지에 기록 |
| `sudo -l -n`은 비밀번호가 필요해도 실패하므로 sudo 그룹 소속인데 "no sudo" FAIL | `id`에 `27(sudo)`, `sudo -n`은 "a password is required" | sudo/admin/wheel 그룹 소속이면 WARN "sudo needs password" (실제 비밀번호 확인은 `sudo -v`) |
| 저장소 경로만 검사, k3s 기본 저장 위치(`/var/lib/rancher`) 미검사 | 205-13은 `/var` 14 GiB | `/var/lib/rancher`(없으면 `/var`) 여유 검사, 저장소와 같은 파일시스템인지 표시 |
| 듀얼부트 시계 위험 미표시 | wtmp에 부팅 직후 시각이 9시간 앞선 기록(오늘 14:10 부팅이 "23:10", 음수 duration 다수) | `LocalRTC`·`NTPSynchronized`·NTFS 파티션 유무 INFO, 듀얼부트+RTC UTC면 WARN, wtmp 부팅 횟수 INFO |
| `import venv`는 python3-venv 패키지 없이도 성공 → venv 생성 실패를 못 잡음 | 이 PC는 ensurepip 없음 | `import venv, ensurepip`로 확인 |

수정 후 이 PC 결과: FAIL 0, WARN = RAM 15 GiB, sudo needs password, dual boot RTC, swap, linger=no, python3-venv missing. 외부 접속 6곳은 curl 종료코드 0으로 실제 PASS.

### 7.3 KUBECONFIG
- k3s 내장 kubectl은 `KUBECONFIG`가 없으면 root 전용 `/etc/rancher/k3s/k3s.yaml`을 읽다 실패한다(205-13). `01-install-k3s.sh`의 `kubectl wait`, `04-deploy-stack.sh`, `linux/capability/*`는 `versions.env`만 읽어서 KUBECONFIG가 비어 있었다.
- `linux/config/versions.env`에 `export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"`, `endpoints.env`도 같은 기본값(명시적으로 export된 값 우선). `emergency-cleanup.sh`는 versions.env를 읽도록 추가.
- Python에서 kubectl을 직접 부르는 진입점(`run-campaign.py`, `generate-run-manifest.py`, `run-fault-experiment.py`, `telemetry_export.py` — 마지막은 `run-attended.py`·`run-matched-pair.py`·export 스크립트가 import)에 `os.environ.setdefault("KUBECONFIG", ~/.kube/config)`. 자식 프로세스가 상속한다.

### 7.4 RAM 15 GiB 대응 (`linux/values/*-linux.yaml`)
- 보존 기간 48h → 12h (Prometheus·Tempo·Loki). run 1개 25분 + export 30분 이내라 12h로도 재시도 여유가 충분하다. Tempo는 비정상 종료 후 WAL replay 양도 줄어든다. Prometheus 메모리는 주로 head block(~2h)이라 retention보다 limit이 RAM을 묶는다.
- limit/request: Prometheus 2Gi/1Gi, Tempo 3Gi/1.5Gi, Loki 1Gi/512Mi. PVC: 20Gi/30Gi/15Gi.
- Tempo 3Gi는 legacy cohort에서 2Gi OOM 뒤 정한 값과 같다. 05-verify와 시험 pair에서 OOMKilled를 반드시 확인한다.

메모리 합계 (values + 차트 기본값; Loki 7.3.0, Prometheus 29.30.0, Chaos Mesh 2.7.2 tgz의 values/templates를 직접 읽음, helm 렌더링은 아직 안 함):

| 구성 | request | limit |
|---|---|---|
| Online Boutique 11개 (loadgenerator 0) — 변경 안 함 | 1112Mi | 2798Mi |
| Prometheus server | 1024Mi | 2048Mi |
| Tempo | 1536Mi | 3072Mi |
| Loki singleBinary / gateway | 512Mi / 64Mi | 1024Mi / 128Mi |
| Loki resultsCache memcached (차트 기본 enabled, allocatedMemory 1024 × 1.2) | 1229Mi | 1229Mi |
| OTel gateway / daemonset | 150Mi / 100Mi | 300Mi / 200Mi |
| Chaos Mesh controller / daemon / dns-server(차트 기본 create) | 128 / 128 / 70Mi | 256 / 256 / 없음 |
| k3s coredns / metrics-server | 70 / 70Mi | 170Mi / 없음 |
| **합계(설정된 값)** | **6193Mi ≈ 6.0 GiB** | **11481Mi ≈ 11.2 GiB** |
| limit 없음: kube-state-metrics, configmap-reload, Loki rules sidecar, memcached-exporter, local-path-provisioner | — | 미정(실측 필요) |
| Pod 밖: k3s server+containerd, k6, recorder/export Python | — | 대략 1~2 GiB(추정, 실측 필요) |

판단: request 6.0 GiB는 현재 사용 가능 메모리 약 11 GiB 안에 들어간다. limit 기준 최악은 11.2 GiB + 무제한 컨테이너 + Pod 밖 프로세스 ≈ 13 GiB 이상으로 11 GiB를 넘는다. 모든 컨테이너가 동시에 limit까지 쓰지는 않지만 Tempo export·Prometheus 질의가 겹치는 순간 swap/OOM 위험이 있다. 줄일 후보(제안만, 미적용):
1. Loki `resultsCache.enabled: false` — 질의 캐시일 뿐이고 기존 values가 같은 이유로 chunksCache를 껐다. −1.2 GiB(request·limit 모두). 가장 효과가 크다.
2. Chaos Mesh `dnsServer.create: false` — DNSChaos를 쓰지 않음. −70Mi, 무제한 컨테이너 하나 제거.
3. Loki `sidecar.rules.enabled: false` — ruler 미사용. 무제한 컨테이너 제거.
4. kube-state-metrics·configmap-reload에 명시적 limit(예: 128Mi/64Mi).
앱 서비스 limit은 장애 실험 조건이라 바꾸지 않는다. 배포 후 `kubectl describe node`(Allocated resources)와 `kubectl top pod -A`로 실측해 위 표를 갱신한다.

### 7.5 수집 전 시계·부팅 게이트
- 이 PC는 듀얼부트이고 RTC가 UTC 모드(LocalRTC=no)라 Windows 사용 후 부팅하면 NTP가 맞출 때까지 시계가 +9h다. 그 상태로 run이 시작되면 모든 라벨 타임스탬프가 틀린다.
- `scripts/host_state.py`: boot_id(`/proc/sys/kernel/random/boot_id`), 부팅 시각(`/proc/stat` btime — NTP 보정 후 값), `timedatectl NTPSynchronized`.
- `run-attended.py`: NTPSynchronized=yes가 아니면 클러스터에 접근하기 전에, run 디렉터리를 만들지 않고 거부. `runtime.json`에 `host_at_start`/`host_at_end`, 시작·종료 boot_id가 다르면 `errors`에 "host rebooted during run". `generate-run-manifest.py`는 `run-manifest.yaml`의 `host`(at_start/at_end/at_manifest)에 기록.
- 한계: 재부팅은 보통 run 프로세스 자체를 끝내므로 같은 프로세스 안의 boot_id 비교가 잡는 경우는 드물다. 실제 재부팅 중단은 미완료 audit(queue 정지)로 드러나고, boot_id 기록은 사후 감사용이다.

### 7.6 캠페인 하루 블록 운영 (`scripts/run-campaign.py`)
- 8/31~10/16 부팅 18회, Linux 최장 연속 가동 약 3.7일, 다른 sudo 사용자 2명 → 100시간 연속 queue는 현실적이지 않아 하루 블록 운영으로 바꿨다.
- `queue.log`를 `with`로 열어 모든 종료 경로에서 닫는다(ResourceWarning 제거).
- `--fault-type`(반복 가능, schedule 순서 유지, 오타는 거부), `--stop-before HH:MM`(settle + `--pair-minutes` 95분 안에 끝나지 않으면 새 pair 시작 안 함, 지난 시각이면 다음 날), `--min-free-gib`(기본 20, `runs/`·`/var/lib/rancher` 검사, 부족하면 rc 4), pair 간 gate에 NTP 동기화.
- 운영 절차·tier 순서·재부팅 복구·일정(약 2.5~3.5주): `linux/README.md` 7절.

### 7.7 테스트
- `tests/test_school_pc.py` 15개 추가. 전체 89개 통과(기존 74 + 15).
- 이 PC에는 pip/python3-venv가 없어 `.venv`를 만들 수 없었다. 테스트는 requirements.txt와 같은 버전의 wheel(PyYAML 6.0.2, pandas 2.2.3, pyarrow 18.1.0와 의존성)을 PyPI sha256으로 확인해 임시 디렉터리에 풀고 `PYTHONPATH`로만 실행했다. 시스템에는 설치하지 않았다. 정식 `.venv`는 `python3-venv` 설치 후 `linux/03-python-env.sh`로 만든다.

### 7.8 1단계 실측 (k3s 설치, 2026-10-16)
사람이 일반 터미널에서 `sudo -v`, `sudo apt-get install -y python3-venv`, `sudo loginctl enable-linger cloudman`, `bash linux/01-install-k3s.sh`를 실행했다. 01 스크립트의 종료 상태는 사람의 터미널에만 있어 직접 보지 못했으나, 마지막 단계까지의 산출물이 모두 확인됐다.
- k3s `v1.33.4+k3s1 (148243c4)`, systemd `k3s` active/enabled. ExecStart: `--disable traefik --disable servicelb --write-kubeconfig-mode 600 --kubelet-arg=fail-swap-on=false`.
- 노드 `206-40` Ready, containerd `2.0.5-k3s2`, kernel 7.0.0-31-generic, INTERNAL-IP 10.198.138.150. kube-system: coredns, local-path-provisioner, metrics-server.
- `sch_netem` 로드됨, `/etc/modules-load.d/sentrix-netem.conf` = `sch_netem`. inotify `max_user_instances=1024`, `max_user_watches=1048576` (`/etc/sysctl.d/90-sentrix.conf`).
- containerd socket `/run/k3s/containerd/containerd.sock` 존재 = `linux/values/chaos-mesh-k3s.yaml`의 `socketPath`.
- k3s 데이터 `/var/lib/rancher` (root 파티션, 여유 846 GiB). 데이터 위치 이동 불필요.
- `/usr/local/bin/k3s` sha256 `10da34c3…1400` = 공식 `sha256sum-amd64.txt`.

**수정: kubectl wrapper.** 01은 `~/.local/bin/kubectl`을 k3s 심볼릭 링크로 만들었는데, k3s 내장 kubectl은 `~/.kube/config`가 있어도 KUBECONFIG가 없으면 `/etc/rancher/k3s/k3s.yaml`(root 0600)을 읽어 `permission denied`로 실패했다(재현). k3s 설치기가 만든 `/usr/local/bin/kubectl`도 같다. `01-install-k3s.sh`가 심볼릭 링크 대신 `KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"`를 넣고 `k3s kubectl`을 exec하는 wrapper를 쓰도록 바꾸고, 같은 블록을 이 PC에 sudo 없이 적용했다. 이제 KUBECONFIG 없이 `kubectl get nodes`가 동작한다. 주의: PATH에서 `~/.local/bin`이 `/usr/local/bin`보다 앞에 있어야 한다(이 PC 기본 PATH는 그렇다; 스크립트들은 직접 앞에 붙인다). wrapper를 쓰기 전에 기존 링크를 `rm`하는 이유: 링크를 통해 쓰면 root 소유 k3s 바이너리를 대상으로 하게 된다(이 작업 중 한 번 그렇게 시도됐고 권한으로 거부되어 바이너리는 위 sha256 그대로다).

**02·03.** `linux/02-install-cli.sh`: helm `v3.17.3+ge4da497`(sha256 확인), k6 `v0.57.0 (commit/50afd82c18)`. `linux/03-python-env.sh`: `.venv` Python 3.12.3, PyYAML 6.0.2 / pandas 2.2.3 / pyarrow 18.1.0, 테스트 89개 통과, ResourceWarning 0건. pip freeze: `linux/out/pip-freeze-20261016T060814Z.txt`.

### 7.9 메모리 축소 적용 (승인 2026-10-16)
7.4의 후보 1~4를 적용했다. 앱 서비스 limit은 그대로다. values key는 차트 tgz의 values/templates에서 확인했다.
- `linux/values/loki-linux.yaml`: `resultsCache.enabled: false`(memcached StatefulSet 1229Mi 제거; chunksCache도 이미 꺼져 있어 memcached-exporter도 렌더링되지 않음), `sidecar.rules.enabled: false`(limit 없는 rules sidecar 제거).
- `linux/values/chaos-mesh-k3s.yaml`: `dnsServer.create: false`(chaos-dns-server Deployment 제거).
- `linux/values/prometheus-linux.yaml`: `configmapReload.prometheus.resources` 16Mi/64Mi, `kube-state-metrics.resources` 64Mi/128Mi.

적용 후 합계 — 이번에는 고정 버전 차트 tgz(5개 모두 helm repo index의 digest와 sha256 일치)를 `helm template`으로 실제 렌더링하고 Online Boutique는 `kubectl kustomize`로 렌더링해, Deployment/StatefulSet/DaemonSet의 컨테이너 메모리를 합산했다(증거: `linux/out/render-20261016/memory-sum.txt`, git 제외).
- 앱·관측·Chaos Mesh: request 4834Mi (4.72 GiB), limit 10274Mi (10.03 GiB). memory limit 없는 컨테이너 0개. memcached·chaos-dns-server·rules sidecar는 렌더링 결과에 없음.
- k3s kube-system 실측(설치된 Deployment): coredns 70Mi/170Mi, metrics-server 70Mi/limit 없음, local-path-provisioner 미설정.
- 전체: **request 4974Mi ≈ 4.86 GiB (이전 6.0), limit 10444Mi ≈ 10.20 GiB (이전 11.2) + metrics-server·local-path 무제한**.
- 판단: request는 사용 가능 메모리(k3s 기동 후 약 10 GiB) 안에 여유 있게 들어간다. limit 합계 10.2 GiB에 Pod 밖 k3s/containerd·k6·export(약 1~2 GiB 추정)를 더하면 최악의 경우 여전히 사용 가능량을 약간 넘는다. 실제 사용량은 04 배포 후 `kubectl top pod -A`와 `kubectl describe node`로 측정해 판단한다.

참고(04 배포 대비): `grafana/tempo` 1.24.4 차트는 `deprecated: true`로 표시된다(버전 고정이라 동작에는 영향 없음, legacy cohort와 같은 차트). 또 이 PC에서 GitHub release asset(차트 tgz) 다운로드가 헤더 응답까지 90~260초 걸려 `helm pull`이 기본 타임아웃(30초)으로 반복 실패했고 curl(`-m 400`)로는 받아졌다. `04-deploy-stack.sh`의 `helm upgrade --install`도 같은 이유로 실패할 수 있으므로, 실패하면 차트를 미리 받아 로컬 tgz로 설치하는 방식을 검토한다.

### 7.10 2단계 실측 (스택 배포·검증, 2026-10-16)
**차트 캐시.** `linux/fetch-charts.sh`(신규)가 `versions.env`의 차트 5개를 각 저장소 `index.yaml`에서 URL·digest를 찾아 curl(`--retry 5 --retry-all-errors --max-time 900`)로 `linux/charts/`에 받고 sha256을 index digest와 비교한다. 이유: 1단계에서 GitHub release asset이 응답까지 90~260초 걸려 helm 자체 30초 HTTP 타임아웃으로 반복 실패했다. 이번 다운로드는 loki 1 s, tempo 31 s, prometheus 30 s, otel 1 s, chaos-mesh 0 s — 5개 모두 MATCH(로그 `linux/out/fetch-charts-20261016T063700Z.log`). 속도가 시간대마다 크게 달라 캐시가 필요하다. `linux/charts/`는 `.gitignore`(용량·재배포). `04-deploy-stack.sh`는 `linux/charts/<name>-<ver>.tgz`가 있으면 그 파일로, 없을 때만 저장소에서 설치하고, `helm --wait`와 앱 `rollout status` 타임아웃을 30m로 늘렸다(HDD·이미지 다운로드).

**배포.** `bash linux/04-deploy-stack.sh` exit 0, 15:38:25 → 15:44:35 (6분 10초). 6개 release 모두 `linux/charts/`의 tgz에서 설치. 로그 `linux/out/deploy-stack-20261016T063825Z.log`, 1분 간격 Pod·이벤트 기록 `linux/out/deploy-watch-20261016T063825Z.log`.
- 이미지 pull 실패(ErrImagePull/ImagePullBackOff/인증/DNS) 0건. 레지스트리별 pull 시간: gcr.io(Online Boutique 10개) 64~86 s, docker.io redis 70 s, ghcr.io chaos-daemon 67 s / chaos-mesh 7 s, docker.io loki·tempo·nginx·otel 9~15 s, quay.io prometheus·reloader 8~13 s, registry.k8s.io kube-state-metrics 13 s. 느리지만 정상 진행(동시 pull).
- OOMKilled·CrashLoopBackOff 0건, 재시작 0. 기동 중 일시 경고만: loki/tempo readiness 503(기동 중), otel-daemonset readiness connection refused(기동 중), loki PVC 바인딩 재시도("object has been modified", 자동 해결), metrics-server readiness timeout(이후 `kubectl top` 정상 동작).
- 참고: Online Boutique의 `redis-cart`는 원본 manifest 그대로 `redis:alpine`(가변 태그)이다. 실제 실행 digest는 image-digests.tsv에 남는다.

**05-verify.** `bash linux/05-verify.sh` exit 0. endpoint 4개(frontend 30080, Prometheus 30090, Tempo 30320, Loki 30310) PASS, Prometheus series 8개 PASS(cpu usage 55, throttled 37, periods 37, ready 19, restarts 19, cpu limits 19, spanmetrics calls 10, tx dropped 18). scrape interval 5s, Prometheus retention 12h 확인. 증거 `linux/out/deploy-20261016T064454Z/`(versions, helm-releases, image-digests.tsv, nodes, storage, endpoints, series). 사소한 점: `scrape-interval.txt`는 API 응답이 한 줄 JSON이라 `grep -m3`가 전체 config를 담는다(값은 확인됨).

**메모리 실측** (모든 Pod Ready 15:44:35, 10분 후 15:54:40, k6 부하 없음 = 유휴 상태; `linux/out/memory-20261016T065440Z/`):
- `kubectl describe node` Allocated: request 4974Mi (31%), limit 10444Mi (66%) — 7.9의 렌더링 계산과 정확히 일치.
- `kubectl top nodes`: 6504Mi (41%, 데스크톱 세션 포함 노드 전체). 컨테이너 합계 1085Mi.
- 상위: prometheus-server 250Mi/2048Mi (12%), loki 126Mi/1024Mi, adservice 80Mi/300Mi, otel gateway 61Mi, otel daemonset 59Mi, metrics-server 56Mi(limit 없음), coredns 51Mi, tempo 51Mi/3072Mi (2%).
- limit 대비 80% 초과 컨테이너 없음(최대 emailservice 41/128Mi = 32%).
- `free -m`: available 9425Mi, swap 사용 0.6 MiB.
- 판단: 유휴 상태에서는 여유가 크다. 실제 위험 구간은 부하(k6) + fault + Tempo/Prometheus export가 겹칠 때이므로 capacity sweep과 시험 pair에서 Tempo·Prometheus·paymentservice/currencyservice 사용률과 OOMKilled를 다시 측정한다.

**디스크.** root 파티션(= `/var/lib/rancher`) 사용 22G → 26G(+4 GiB, 이미지·PVC 초기화), 여유 841G. PVC: Prometheus 20Gi, Tempo 30Gi, Loki 15Gi (local-path, Bound). PVC 실제 사용량은 root 소유 디렉터리라 sudo 없이 측정하지 않았다.

### 7.11 3단계 실측 (capability gate, 2026-10-16)
판정 기준(`linux/capability/judge.py`)은 바꾸지 않았다.

**1차 실행** (`linux/out/capability-20261016T070430Z/`, 로그 `linux/out/capability-run-20261016T070430Z.log`): cpu PASS, network PASS, **pod FAIL**. pod 디렉터리가 비어 있고 probe.log에 메시지도 없었다. 원인은 스크립트 버그: `pod.sh`의 `ready()`가 kubectl jsonpath 출력(끝 줄바꿈 없음)을 내고, `read -r UID0 R0 < <(ready)`는 값은 읽지만 EOF에서 1을 반환해 `lib.sh`의 `set -e`가 스크립트를 첫 줄에서 조용히 종료시켰다(`bash -c 'set -e; read -r A B < <(printf "x true")'`로 재현). 즉 주입이 시도조차 되지 않았고 Chaos 객체도 남지 않았다. 수정: `ready()` 끝에 `echo` 추가. 다른 `read` 사용처(network.sh)는 python print라 줄바꿈이 있어 해당 없음.

**2차 실행 (수정 후 전체 재실행)** — `linux/out/capability-20261016T071128Z/`, 로그 `linux/out/capability-run-20261016T071128Z.log`, run-all exit 0, 세 probe 모두 PASS.
- cpu: 사용량 전 0.0027 → 중 0.4999 → 후 0.0027 core(30 s 평균), `nr_throttled` 증가 160(중), 0(전·후), `cpu.max` `50000 100000` 불변. 1차도 0.4999 core / 증가 300으로 같은 결과.
- pod: UID 전후 동일 `0f51718f-…1d49`, Ready true → false(07:13:53~07:14:14) → true, AllRecovered=True, Apply 07:13:16 / Recover 07:14:16 Succeeded.
- network: delay 100 ms — RTT 전 0.069 → 중 100.131 → 후 0.070 ms, 다른 경로 0.064 → 0.080 ms; loss 10% — 손실 11.33 %(300 ping), 다른 경로 0 %, 제거 후 0 %; qdisc는 delay·loss 후 모두 주입 전과 동일(주입 중 prio + netem `delay 100ms` 확인). 1차 loss는 8.67 %.

**여유·안정성 표시**
- delay: +100 ms로 기준(+80 ms)보다 20 ms 여유, 다른 경로 영향 0.02 ms. 여유 충분.
- loss: 8.67 %(1차) / 11.33 %(2차). 300 패킷에서 10 % 손실의 표준편차가 약 1.7 %p라 예상 범위 안이고 기준 4 %보다 충분히 크다. 다만 캠페인 강도 판단에는 300 패킷 한 번의 값이 ±3 %p 흔들린다는 점을 고려한다.
- **pod-failure 효과 지연(주의):** AllInjected(07:13:16) 후 Ready=false까지 약 31 s, unready 구간은 60 s duration 중 약 21~24 s뿐이었다. 이벤트 순서: `Killing: Container main definition changed`(07:13:16) → 기존 컨테이너 종료 대기 → `Pulling gcr.io/google-containers/pause:latest`(07:13:47, 4.5 s) → 생성 실패·BackOff(의도된 pod-failure 상태) → Recover(07:14:16). 지연의 대부분은 probe 컨테이너(busybox `sh -c` PID 1이 SIGTERM을 무시)가 terminationGracePeriod 30 s를 다 채운 것이고, 첫 주입 때만 pause 이미지 pull(gcr.io, `latest` 태그)이 더해졌다. 앱에서는 terminationGracePeriodSeconds가 서비스마다 다르다(adservice·cartservice·currencyservice·emailservice·paymentservice·productcatalogservice·recommendationservice 5 s, checkoutservice·frontend·shippingservice·redis-cart 30 s). 따라서 pod_failure 실제 onset은 주입 요청보다 최대 수십 초 늦을 수 있으므로, 시험 pair와 라벨링에서는 요청 시각이 아니라 관측된 Ready=false 시각(kube_pod_container_status_ready)을 onset으로 확인해야 한다. pause 이미지는 이제 노드에 있다.

**정리·영향 확인.** `kubectl delete ns sentrix-probe` 완료, 남은 Chaos 객체 없음. `sentrix` Pod 18개 모두 Running/Ready, 재시작 0, startTime 배포 시각 그대로(영향 없음). 정리 후 05-verify 재실행 endpoint·series 12개 PASS(`linux/out/deploy-20261016T071951Z/`).

**메모리(실행 중 1분 간격, `linux/out/capability-mem-20261016T071128Z.log`, 1차는 `…070430Z.log`):** 노드 사용 최대 7425Mi(47 %, 2차) / 7294Mi(46 %, 1차), available 최저 8715 MiB(2차) / 9352 MiB(1차), swap 사용 0. 정리 후 7016Mi, available 9170 MiB.

### 7.12 4단계 (capacity C) 1차 — 중단 (2026-10-16 17:56 KST, 7.13에서 이어서 완료)
PC를 꺼야 해서 sweep을 rate 4 완료 직후 중단했다(tmux 세션 종료, fault 없는 측정이라 클러스터 영향 없음). **C는 아직 결정되지 않았다.** `capacity-sweep.py`는 끝까지 돌아야 `capacity-result.json`을 쓰므로 본 측정의 결과 파일은 없다. 판정 기준은 스크립트 고정값 그대로(성공률 ≥ 99.5 %, p99 ≤ max(500, 3×rate1 p99) = 500 ms, 달성률 90~110 %, dropped ≤ 1 %, assessment valid).
- 시험(rate 1, 5분): PASS, `runs/_calibration/capacity-20261016t072722/capacity-result.json`. pipeline-v2 complete, quality m1a_overall PASS, run-manifest `host` 기록 확인.
- 본 측정 `--rates 1,2,3,4,6,8 --minutes 10` (로그 `linux/out/capacity-main-20261016T073629Z.log`): rate 1/2/3/4 모두 PASS — 성공률 100 %, p99 124/156/125/129 ms, dropped 0, 거래 수 603/1204/1803/2403, assessment valid. rate 6 run(`calib-linux-v1-capacity-6p0-20261016t073629`)은 시작 직후 중단되어 미완료로 남겨 두었다(삭제하지 않음, 재측정은 새 stamp/ID).
- 메모리(1분 간격, `linux/out/capacity-mem-20261016T073629Z.log`): 노드 최대 9411Mi, **swap 최대 471 MiB 사용(이전 단계 0)**, Tempo 최대 2262Mi / limit 3Gi = **74 %**(export 중), Prometheus 최대 440Mi, 재시작·OOMKilled 0.
- run 크기·후처리 시간(`linux/out/run-footprint.py`, 10분 run):
  - rate 1: 453 MiB, 후처리 313 s (export 269 s)
  - rate 2: 864 MiB, 후처리 461 s (export 397 s, canonical 20 s)
  - rate 3: 1274 MiB, 후처리 701 s (export 539 s, canonical 66 s)
  - rate 4: 1685 MiB, 후처리 884 s (export 698 s, canonical 95 s)
  - 크기는 rate에 거의 비례(10분·1 tx/s당 약 410 MiB). 그중 `raw-v2/_export` 체크포인트가 약 49 %(raw traces의 1.6배)를 차지한다.
- backend: Prometheus `/data` 306 MiB, Tempo `/var/tempo` 9.7 MiB(rate 1 시험 직후, kubectl exec). Loki는 이미지에 셸이 없어 미측정. local-path PVC는 같은 파일시스템이라 kubelet stats가 PVC별 값이 아닌 전체 사용량을 준다.

남은 일(다음 세션): 새 stamp로 sweep 재실행(rate 6, 8까지, 또는 1~8 전체), C·0.4C·surge 계산, 25분 run 크기·export 시간 추정, 138 run 저장량과 일정 재계산. 재부팅 후에는 README 7.5 순서(NTP → Pod Ready → 05-verify)로 확인한다.

### 7.13 4단계 (capacity C) 재개·완료 — C = 6 tx/s (2026-10-19)
**끊긴 경위.** 1차 sweep `capacity-20261016t073629`(`--rates 1,2,3,4,6,8 --minutes 10`)은 rate 1~4를 끝내고, rate 6 run을 시작한 직후(17:56:06 시작, 17:56:20 중단) 멈췄다. 원인은 운영자가 PC를 끄려고 sweep을 중단한 것이다(7.12). journal상 tmux scope 종료 17:56:20 → GNOME 종료 대화상자 → 정상 shutdown 17:59:50(`last -x` "shutdown system down"). 스크립트 오류나 크래시는 아니다. 다음 부팅은 10/19 15:29(boot_id `380a74a8-…`). sweep이 끝까지 돌지 않아 1차의 `capacity-result.json`은 없다.

**재부팅 후 확인(읽기만).** NTP 동기화 yes, node Ready, Pod 23개 모두 Ready, Chaos 객체 없음, `sch_netem` 로드. 부팅 직후 unattended-upgrade가 커널 7.0.0-38을 설치 중이라 CPU 부하가 있어서 끝날 때까지(15:43) 기다렸다가 시작했다. Automatic-Reboot는 꺼져 있지만 `/var/run/reboot-required`가 생겼다. 다음 블록 전에 재부팅 시점을 사람이 정해야 한다.

**1~4 재검증.** 4개 run 모두 run-assessment-v2 valid(errors 없음), pipeline-v2 complete(export/canonical/re2 rc 0), runtime errors 없음, 5개 항목 모두 PASS. 미완료 rate-6 run(`calib-linux-v1-capacity-6p0-20261016t073629`)은 지우거나 재사용하지 않았다.

**이어서 측정.** tmux `cap68`, `.venv/bin/python -B scripts/capacity-sweep.py --rates 6,8 --minutes 10 --max-p99-ms 500` (15:43:58~16:49:44, `runs/_calibration/capacity-20261019t064358/capacity-result.json`). p99 기준 500 ms는 rate 1 결과(124 ms → max(500, 372))로 고정했고 다시 계산하지 않았다.

| rate (tx/s) | run ID | 성공률 | p50 / p99 (ms) | 달성 tx/s | dropped | assessment | 판정 |
|---|---|---|---|---|---|---|---|
| 1 | `…-1p0-20261016t073629` | 100 % | 36 / 124 | 1.005 | 0 | valid | PASS |
| 2 | `…-2p0-20261016t073629` | 100 % | 37 / 156 | 2.007 | 0 | valid | PASS |
| 3 | `…-3p0-20261016t073629` | 100 % | 34 / 125 | 3.005 | 0 | valid | PASS |
| 4 | `…-4p0-20261016t073629` | 100 % | 35 / 129 | 4.005 | 0 | valid | PASS |
| 6 | `…-6p0-20261019t064358` | 100 % | 133 / 326 | 6.007 | 0 | valid | PASS |
| 8 | `…-8p0-20261019t064358` | 100 % | 265 / 545 | 8.005 | 0 | valid | **FAIL (p99)** |

- **C = 6 tx/s** (처음 FAIL인 8 바로 아래 통과 단계). rate 8은 p99 하나만 기준을 넘었다.
- 지연 곡선: 4 → 6 사이에서 p50이 35 → 133 ms로 꺾인다. 즉 C(=1.0C surge l3)는 이미 지연이 커지기 시작한 구간이다. 의도한 포화 수준이다.
- 합친 요약: `runs/_calibration/capacity-merged-20261019/capacity-merged.json`(생성 스크립트 `merge.py`가 같은 폴더에 있다). 원래 `capacity-result.json`들은 수정하지 않았다. 곡선 CSV는 `linux/out/capacity-curve-20261019.csv`(rate, p50, p99, 성공률, 달성률). 둘 다 gitignore 경로라 커밋하지 않았다.

**메모리(1분 간격 66회, `runs/_calibration/capacity-merged-20261019/resource-monitor.log`).** 노드 최대 9955Mi, available 최저 6621 MiB, swap 최대 89 MiB(1차 471 MiB보다 적다), Tempo 최대 2403Mi / 3Gi = 78 %, Prometheus 419Mi, otel gateway 281Mi, Loki 356Mi. OOMKilled 0, 재시작 증가 0.

**run 크기·후처리 시간** (`linux/out/run-footprint.py`, 10분 run, MiB):

| rate | 합계 | raw traces | raw logs | raw metrics | raw `_export` | canonical | re2 | 나머지 | export(91 s settle 포함) | canonical | re2 | 후처리 합계 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 453 | 127 | 57 | 9.2 | 223 | 15 | 4.4 | 18 | 269 s | 6 s | 2 s | 313 s |
| 2 | 864 | 253 | 107 | 9.3 | 422 | 29 | 8.3 | 34 | 397 s | 20 s | 3 s | 461 s |
| 3 | 1274 | 379 | 157 | 9.4 | 622 | 43 | 12 | 51 | 539 s | 66 s | 4 s | 701 s |
| 4 | 1685 | 505 | 208 | 9.3 | 822 | 58 | 16 | 68 | 698 s | 95 s | 6 s | 884 s |
| 6 | 2509 | 758 | 309 | 9.6 | 1222 | 87 | 24 | 101 | 925 s | 119 s | 9 s | 1159 s |
| 8 | 3331 | 1010 | 409 | 9.6 | 1621 | 115 | 32 | 134 | 1206 s | 180 s | 12 s | 1555 s |

**backend PVC(kubectl exec, sweep 직후).** Prometheus `/data` 702 MiB / 20Gi, Tempo `/var/tempo` 167 MiB / 30Gi (retention 둘 다 12h). Loki는 셸이 없어 미측정이다(측정용 Pod는 띄우지 않았다).

**캠페인 산정** (거래 수에 대한 선형 적합, 6개 run: 크기 = 30.1 + 0.685 × 거래 + 0.94 MiB/분, export = 138 + 0.222 × 거래 s, 후처리 = 141 + 0.293 × 거래 s):
- 부하: C = 6, 기본 0.4C = **2.4 tx/s**, surge 0.6C/0.8C/1.0C = 3.6 / 4.8 / 6.0 tx/s.
- 25분 정식 run(0.4C, 거래 3600): 약 **2.5 GiB**(2520 MiB), export 약 938 s, 후처리 약 1196 s(약 20분). 같은 거래 수인 rate 6 10분 run 실측(2509 MiB, 1159 s)과 거의 같다. surge fault run(300 s 구간만 상향): l1 2767 / l2 3014 / l3 3260 MiB, 후처리 1302 / 1407 / 1512 s.
- 138 run 총 저장량: 약 **344 GiB**(129 × 0.4C + surge 9). 현재 여유 829 GiB → 끝난 뒤 약 485 GiB가 남는다(backend PVC 최대 65 GiB 별도). README의 "1 GiB/run, 140 GiB" 추정은 2.5배 과소였다. 다만 디스크는 충분하다.
- pair 1개: settle 300 s + 2 × (1500 s + 후처리 1196 s) ≈ **95분**(README·`--pair-minutes` 기본 95와 일치).
- 69 pair 순수 실행 약 **109시간**. 하루 8 h 블록 → 블록당 5 pair, **14 블록**. 10 h 블록 → 6 pair, **12 블록**. 재시도·재부팅 복구·주말을 더하면 README 7.6의 2.5~3.5주 범위의 위쪽 끝이다.
- 주의: 25분 run의 export 동안 Tempo가 rate 6~8 10분 run과 같은 거래 수(3600~4700)를 다루므로 Tempo 메모리는 이번 최대치(78 %) 근처까지 오를 수 있다. 시험 pair에서 다시 확인한다.

남은 일: `campaigns/linux-v1/fault-params.yaml`의 `capacity_tps: 6`은 merged/resumed 결과 파일 경로와 함께 강도 동결 때 기록한다(이번에는 수정하지 않았다). 다음은 시험 pair(README 7.1, `--capacity-tps 6`)다.

### 7.14 5단계 시험(calibration) pair 4개 (2026-10-19~20)
**재부팅 후 점검.** 커널 7.0.0-38-generic(boot_id `40b3608b-…`, 10/19 17:23 부팅), NTP 동기화 yes, Pod 모두 Ready, Chaos 객체 없음, `sch_netem` 로드 확인. `bash linux/capability/run-all.sh` 재실행 → cpu·pod·network 모두 PASS(`linux/out/capability-20261019T082906Z/`. cpu 0.0027 → 0.5000 → 0.0028 core, throttled +261 / pod 같은 UID 유지, fault 중 unready / delay RTT 100.16 ms(다른 경로 0.085 ms), loss 11.33 %(다른 경로 0 %)). 이후 `sentrix-probe` ns 삭제. 05-verify PASS(`linux/out/deploy-20261019T083727Z`).

**Tempo 메모리 limit 3Gi → 4Gi**(`linux/values/tempo-linux.yaml`, request 1536Mi는 그대로). 근거: capacity sweep 최대치가 2403Mi(3Gi의 78 %, rate 8)였다. 25분 surge-L3 fault run은 거래 약 4700건을 export해서 rate 8 10분 run보다 많다. `helm upgrade tempo …`(revision 2)를 하면 Service가 ClusterIP로 돌아가므로 04 스크립트의 NodePort 30320 patch를 다시 적용했다. 그다음 05-verify 12/12 PASS. 노드 limit 합계 memory 11468Mi(73 %, 이전 10444Mi), request 4974Mi(31 %), CPU limit 11225m. 시험 pair 동안 Tempo 최대치는 2302Mi / 4Gi = 56 %였다.

**스케줄.** `.venv/bin/python -B scripts/generate-campaign.py --seed 1 --campaign-id calib-linux-v1 --capacity-tps 6` → `campaigns/calib-linux-v1/schedule.json`, profile 138개. 모든 profile이 target_rps 2.4, phase 합 1500 s, `draft: true`이다. 시험 pair 4개는 모두 `fault_then_control`이다. onset: cpu-checkout 660 s, loss-front-product 720 s, pod-checkout 720 s, delay-front-product 480 s.

**실행.** tmux `sentrix-campaign`에서 `linux/campaign/start.sh --schedule campaigns/calib-linux-v1/schedule.json --allow-draft --only …`를 실행했다(`--stop-before` 없음). 큐 로그는 `runs/_campaign/calib-linux-v1/queue.log`, 1분 간격 자원 로그는 `resource-monitor.log`, pair별 분석은 `analysis/<pair>.json`(`analyze-pair.py`)이다. 모두 gitignore 경로다.

**버그 수정: `scripts/generate-incident-record.py`.** 첫 pair(cpu)가 incident-record에서 rc 1로 멈췄다. 오류는 "control is not preceding/fresh within 2h"였다. `fault_then_control`인데도 control을 fault 시작 시각 기준으로 "앞선 run"인지 검사했기 때문이다. `evaluate-pair.py`와 같은 규칙(fault_then_control이면 fault run 종료 시각 기준, `pair_order` 전달)으로 고쳤다. 단위 테스트 89개 OK(이 경우의 회귀 테스트는 아직 없음). 그 pair의 incident-record만 다시 돌려 rc 0, control_match valid를 확인했다(`audits/pair-calib-linux-v1-cpu-checkoutservice-r01/incident-record-rerun-after-fix.log`, 이전 yaml은 `incidents/_history/`). audit status.json은 failed 그대로 두었고(수정하지 않음), queue.log에 NOTE를 남겼다. 나머지 3 pair로 큐를 다시 시작했다. 이후 3 pair는 모두 rc 0이다.

| pair | 파이프라인/assessment (fault, control) | pair-assessment | 주입 요청 → AllInjected → AllRecovered (UTC) | 실제 효과 | evaluation_v2 영향 | 시간 / 저장 |
|---|---|---|---|---|---|---|
| cpu-checkoutservice-r01 | complete·valid / complete·valid | valid | 08:56:09.53 → 09.96 → 09:01:09.21 (confirmed) | checkout CPU 0.004 → 0.295 → 0.004 core(limit 500m), throttled period 0 → 91 %. checkout 발신 span p99 1~3 → 25~41 ms, p50 그대로 | **없음**: 기준 성공 100 %, p99 120 ms → 임계 95 % / 360 ms. fault 구간 n 719, 성공 100 %, p99 125 ms, 최악 30 s p99 141 ms | 91.8분(+settle 5분) / 5155 MiB |
| loss-front-product-r01 | complete·valid / complete·valid | valid | 10:36:13.75 → 16.91 → 10:41:14.72 (confirmed) | **없음**: frontend→productcatalog span p50 0.1 / p99 0.8 ms, 오류 0 %(pre·during·post 동일, n≈17,900) | **없음**: 기준 p99 121 ms, fault 구간 p99 132 ms, 최악 30 s p99 217 ms, 성공 100 % | 91.7분 / 5156 MiB |
| pod-checkoutservice-r01 | complete·valid / complete·valid | valid | 12:12:55.29 → 59.31 → 12:17:55.86 (confirmed) | 같은 UID e603bf7f… 유지. Ready=false 첫 관측은 요청 후 **15.2 s**(kube-state-metrics 수집 간격), unready 약 285 s. 사용자 오류는 요청 후 4.3 s(12:12:59.6)부터 시작했다. frontend→checkout 712건 모두 오류(p50 0.0 ms, 즉시 실패). checkout 재시작 2 → 8. endpoint 객체는 직접 수집하지 않았다 | **있음**(error_rate_increase, 12:12:59.6): fault 구간 성공 0 %(임계 95 %), 기준 p99 124 ms. 복구 후 5 s 안에 통과 | 89.8분 / 5053 MiB |
| delay-front-product-r01 | complete·valid / complete·valid | valid | 13:43:47.08 → 49.92 → 13:48:48.08 (confirmed) | **없음**: frontend→productcatalog p50 0.1 / p99 0.8 ms(control 동일). 다른 edge 13개도 변화 없음 | **없음**: 기준 p99 128 ms → 임계 384 ms, fault 구간 p99 121 ms, 최악 30 s p99 266 ms, 성공 100 % | 92.7분 / 5160 MiB |

edge pod: frontend-5c676694c8-xfx5r `e2e4f7ec-fb7f-454d-8754-cfb35fb7dddf` → productcatalogservice-69cd8c9fb9-79vw2 `97473837-75e2-42e9-8a45-bd87f6db3d66`. Chaos 기록상 두 pod 모두 Injected였다. pair 하나는 약 91.5분 + settle 5분 = **96.5분**으로, 추정 95분과 맞는다. 저장량은 pair당 약 5.0 GiB로 추정(2 × 2.5 GiB)과 같다.

**delay·loss 효과 없음의 원인(가설, 추가 주입은 하지 않음).** 호출하는 쪽은 모두 Service 이름(`productcatalogservice:3550` 등)으로 ClusterIP에 접속한다. 시험 대상 edge 5개의 호출자 frontend·checkout·recommendation이 모두 그렇다. kube-proxy DNAT(ClusterIP → pod IP)는 pod의 egress tc를 지난 뒤 호스트 네트워크 namespace에서 일어난다. 따라서 chaos-mesh가 source pod eth0에 거는 "목적지 = target pod IP" 필터에 걸리지 않는다. capability probe는 pod IP로 직접 ping했기 때문에 이 경로를 검사하지 않았다. 이 가설이 맞으면 **delay·loss 30 pair 전체가 같은 결과**(효과 없음)가 된다.

**메모리(1분 간격 388회).** 노드 최대 10609Mi, available 최저 7074 MiB, swap 0 → 최대 1033 MiB(꾸준히 증가, available은 충분), Tempo 최대 2302Mi / 4Gi, Prometheus 최대 810Mi. OOMKilled 0. 재시작 증가는 pod fault 대상 checkoutservice(2 → 8)뿐이다. 종료 후 Chaos 객체 4개는 남아 있지만 모두 desiredPhase Stop, AllRecovered=True다(큐 gate가 허용하는 회복된 기록용 객체이며, 지우지 않았다). 디스크 여유는 809 GiB다.

**강도 제안(`fault-params.yaml`은 수정하지 않았다).**
- pod_failure: **유지.** 즉시, 완전한 영향을 낸다. 대상 5개 모두 동기 호출 경로라 같은 결과가 예상된다.
- cpu_saturation: **상향 제안.** 1 worker로는 throttling이 91 %여도 사용자 영향이 없다. checkout과 payment는 거래당 1회만 호출되어 다른 대상도 영향이 없을 가능성이 크다. currency(약 46 call/s)와 productcatalog(약 60 call/s)는 페이지마다 여러 번 순차 호출되어 증폭될 수 있다. 템플릿을 workers 2~4로 올려 quota 전체를 점유하게 한 뒤 checkout 1건을 다시 시험하기를 제안한다(템플릿은 현재 `workers: 1` 고정).
- network_delay / packet_loss: **강도 문제가 아니라 주입 경로 문제다. 강도를 바꾸기 전에 템플릿을 고쳐야 한다.** 후보: (a) 목적지 Service ClusterIP를 `externalTargets`에 추가, (b) 목적지 pod에서 `direction: from`/`both`로 걸기(목적지에서는 DNAT 이후 원래 source pod IP가 보인다). 먼저 capability probe를 Service 이름 경로로 확장해 검증하자. 경로를 고친 뒤 100 ms는 frontend가 거래당 productcatalog를 약 25회 호출하므로 오히려 강할 수 있다. 다시 시험하고 정하자.
- traffic_surge(capacity 곡선 기준, 기준 p99 약 120~128 ms → 3배 임계 약 360~384 ms. 성공률은 rate 8에서도 100 %라 p99 기준만 관련된다):
  - L1 3.6 tx/s: rate 3~4의 p99가 125~129 ms이므로 **영향 없음** 예상.
  - L2 4.8 tx/s: rate 4(129)와 6(326) 사이이므로 **영향 없음** 예상.
  - L3 6.0 tx/s: 정상상태 p99 326 ms는 임계보다 조금 아래라 **경계**다. 30 s 창의 꼬리에서만 넘을 수 있다.
  - surge가 영향을 확실히 내야 한다면 L3를 약 8 tx/s(1.33C, p99 545 ms ≈ 4.3배)로 올려야 한다. 이는 load_fractions 설계 변경이므로 결정이 필요하다.
- 스택 여유: 거래 수가 같으면 강도를 올려도 관측 데이터량은 거의 그대로다. Tempo 56 %, available 7 GiB 이상, 디스크 809 GiB로 여유가 있다. surge L3를 8 tx/s로 올리면 Tempo는 sweep의 rate 8 최대치(2403Mi, 4Gi의 59 %) 수준이 될 것이다. swap 증가 추세는 블록마다 확인한다.

남은 일: delay·loss 주입 경로 수정·검증(템플릿 + capability probe), cpu workers 결정, surge 목표 결정. 그 후 시험 pair를 새 run ID(`-r02` 등)로 다시 돌리고 강도를 동결한다. `generate-incident-record.py`의 fault_then_control 회귀 테스트를 추가한다. 커밋한 `campaigns/calib-linux-v1/`, `workload/profiles/calib-linux-v1/`는 draft 시험용이다.

### 7.15 5단계 보완 — delay·loss 주입 경로 수정(방법 A), CPU worker 4, surge 단계 변경 (2026-10-20)
**네트워크 환경.** k3s 내장 kube-proxy는 **iptables** 모드다(`:10249/proxyMode` = iptables, ip_vs 모듈 없음). CNI는 k3s 내장 **flannel vxlan**(VNI 1, 브리지 `cni0`, pod 대역 10.42.0.0/16, MTU 1450, ipmasq true)이다.

**가설 검증(probe 3방식 비교, `linux/out/capability-net3-20261020T040946Z/network/`).** probe-dst와 probe-other에 HTTP 서버(8080)와 ClusterIP Service를 두었다. probe-src에서 요청마다 새 TCP 연결을 여는 curl을 경로마다 60회(loss는 150회) 보내고, 주입 전·중·후를 측정했다. 값은 dst ClusterIP 경로의 median이다. loss는 실패했거나 200 ms 이상 걸린 요청의 비율이다.

| 방식 | Service 경로 delay | Service 경로 loss 10 % | Pod IP 경로 | 다른 경로 | 제거 후 |
|---|---|---|---|---|---|
| 기존(selector=출발, target=도착 Pod, to) | 1.3 → 1.1 ms (**무효**) | 0 % (**무효**) | 202 ms / 19 % | 그대로 | 원복 |
| A: + externalTargets = 도착 ClusterIP | 1.3 → 202 ms | 22.0 % | 202 ms / 16.7 % | 그대로 | 원복 |
| B: selector=도착, target=출발 (응답 방향) | 1.2 → 202 ms | 10.7 % | 202 ms / 11.3 % | 그대로 | 원복 |

- 가설이 확인됐다. ClusterIP → Pod IP DNAT는 출발 pod의 egress tc를 지난 뒤 일어난다. 그래서 Pod IP 필터는 앱 트래픽에 걸리지 않는다. 7.14의 delay·loss 무효과는 이 때문이다.
- +200 ms는 새 연결이라 지연 구간을 두 번(handshake + 요청) 지나간 값이다.
- **방법 A를 승인받았다.** 근거: 방향(호출하는 쪽 egress, 요청 방향)과 주입되는 pod(출발)가 기존과 같아 라벨과 기록 의미가 유지된다. loss 효과도 Pod IP 경로와 같은 수준이다. B는 응답만 버려서 loss가 약했다.

**수정 내용.**
- `deploy/chaos-mesh/faults/network-delay.yaml`, `packet-loss.yaml`: 기존 Pod IP target을 유지하고 `externalTargets: ["{{TARGET_SERVICE_CLUSTER_IP}}"]`를 추가했다.
- `scripts/fault_manifest.py`(새 파일):
  - `render()`가 치환을 맡는다. 도착 Service의 ClusterIP는 주입 직전에 `kubectl get svc`로 조회한다. 값이 없거나 IP 형식이 아니면, 또는 치환되지 않은 `{{…}}`가 남으면 주입을 거부한다.
  - `filter_targets()`는 렌더링된 manifest에서 실제 필터(direction, 주입 selector, target selector, externalTargets)를 읽는다.
  - `observed_targets()`는 AllInjected 시점의 Chaos Mesh containerRecords(`.` = 주입된 pod, `.Target` = 필터 대상)를 pod 객체와 맞춰 본다.
- `scripts/run-attended.py`: `fault_manifest`를 사용하도록 바꿨다. `fault-record.json`에 `filter_targets`를 기록한다.
  - 항목: `direction`, `injected_selector`, `target_selector`, `external_targets`, `destination_cluster_ip`, `injected_source_pods`(name/uid/IP), `target_destination_pods`, `destination_pod_ips`, `selection_consistent`.
- `cpu-saturation.yaml`: `workers: {{WORKERS}}`, `load: {{LOAD}}`로 바꿨다. `fault-params.yaml`의 cpu params는 `WORKERS: 4, LOAD: 100`(draft)이다.
- surge 단계 0.6/0.8/1.0C → **0.8/1.0/1.33C**(`fault-params.yaml` `load_fractions.surge_levels` l1 0.8, l2 1.0, l3 1.3333; `campaign-plan.yaml` levels; `docs/LINUX-PRODUCTION-DATASET-DESIGN.md` 표). 실제 값은 `generate-campaign.py`가 fault-params에서 읽는다. C = 6이면 4.8 / 6.0 / 8.0 tx/s다.
  - 이유: capacity 곡선(7.13)에서 0.6C(3.6 tx/s)는 p99가 baseline과 같아 확실히 무영향이었다. 1.0C(p99 326 ms)도 3배 임계(약 360~384 ms) 아래인 경계였다. 4/3 C = 8 tx/s는 p99 545 ms(약 4.3배)로 측정됐다.
- capability:
  - `probe-pods.yaml`: probe-dst와 probe-other에 HTTP 서버, readiness, Service를 추가했다.
  - `network.sh`: 기존 ping 검사는 그대로 두고 Service 경로 검사를 추가했다(`NET_TEMPLATE_METHOD` 기본 a, `NET_METHODS` 기본 같은 값).
  - `judge.py service`: 기존 기준은 그대로다. 새 기준은 delay가 before + 80 ms 이상, 다른 경로는 + 20 ms 미만, 제거 후 + 10 ms 이하다. loss는 영향 비율 10 % 이상, 다른 경로와 제거 후는 2 % 이하다.
- 테스트(모두 99개 OK):
  - `tests/test_fault_manifest.py`:
    - 생성된 edge fault 30개 모두에서 기록된 filter_targets가 렌더링된 manifest 및 치환한 ClusterIP와 같다.
    - params가 manifest에 반영된다.
    - ClusterIP가 없거나 placeholder가 남으면 거부한다.
    - observed_targets의 일치·불일치 판정이 맞다.
    - cpu WORKERS/LOAD가 반영된다.
    - fault_then_control에서 incident-record가 뒤따르는 control을 고른다(회귀).
  - `test_campaign_schedule.py` SurgeLevelTests: l1/l2/l3 = 4.8/6/8 tx/s, 나머지 phase는 2.4다.
  - `generate-incident-record.py`의 control 선택 로직은 `select_control_match()`로 분리했다(동작은 같다).
- capability 전체 재실행 PASS(`linux/out/capability-20261020T044751Z/`): cpu, pod, network(ping 8/8) 모두 통과했다. Service 경로(방법 A)는 delay 0.84 → 201.9 ms, loss 19.3 %, 다른 경로 변화 없음, 제거 후 원복. 이후 `sentrix-probe` ns를 삭제했다.
- 참고: `scripts/run-fault-experiment.py`(M2 이전 경로, linux-v1 캠페인은 사용하지 않음)는 자체 치환을 쓴다. 그 경로로 cpu 템플릿을 쓰면 `{{WORKERS}}`가 남는다.

**시험 2차 스케줄.** 기존 calib 파일을 덮어쓰지 않도록 `--campaign-id calib2-linux-v1`로 생성했다(`--seed 1 --capacity-tps 6`, profile 138개, draft). 시험 대상은 `calib2-linux-v1-{cpu-checkoutservice,delay-front-product,loss-front-product}-r02`이며 셋 다 control_then_fault다. onset은 각각 420 / 420 / 600 s, phase 합 1500 s, target_rps 2.4다.

### 7.16 5단계 시험 pair 2차 결과 (calib2-linux-v1, 2026-10-20)

queue는 `campaigns/calib2-linux-v1/schedule.json --allow-draft --stop-before 21:00`으로 tmux에서 돌렸다. 세 pair 모두 control_then_fault, target_rps 2.4다. 분석은 `runs/_campaign/calib2-linux-v1/analysis/<pair>.json`(`analyze-pair.py`)에 있다. edge 지연은 Tempo client span 기준이다. pre는 주입 전 240 s, during은 AllInjected부터 AllRecovered까지, post는 제거 60~300 s 후다.

| pair | 상태 | 소요 | 크기 | Tempo 최대 | swap 최대 |
|---|---|---|---|---|---|
| cpu-checkoutservice-r02 | **failed**(fault run 후처리 deadline, 아래) | 약 93분 | 5,093 MiB | 2,285 Mi | 800 MiB |
| delay-front-product-r02 | complete, 두 run assessment valid | 93.1분 | 5,171 MiB | 2,199 Mi | 851 MiB |
| loss-front-product-r02 | complete, 두 run assessment valid | 93.2분 | 5,169 MiB | 2,342 Mi | 854 MiB |

최소 가용 메모리는 6.4~7.2 GiB였다. 디스크 사용은 74 GiB(9 %)다.

**cpu r02 실패와 수정.**
- fault run의 run 안 incident-record 단계가 180 s deadline을 넘겼다(15:34:33~15:37:35 KST). 그래서 runtime.json에 오류가 남고 pair가 failed가 됐다.
- 원인: `/`(runs, k3s 데이터)가 회전형 HDD(sda TOSHIBA DT01ACA100)다. validate_views가 두 run의 산출물 약 7,250개(2.4 GiB)를 cold cache로 다시 해시하는 데 180 s 넘게 걸렸다. 수동 재실행(warm cache)은 5.5 s였다(`audits/pair-calib2-linux-v1-cpu-checkoutservice-r02/incident-record-manual-after-deadline.log`).
- 수정: `scripts/run-attended.py`의 incident-record deadline을 180 → 900 s로 바꿨다. pair는 failed로 두었다(runtime.json 미수정, ID 재사용 없음). queue.log에 NOTE를 남기고 delay·loss만 다시 돌렸다. 그 뒤 두 pair는 이 단계에서 문제가 없었다.
- workload, 주입·제거, pipeline은 모두 정상이었다. 두 run의 assessment도 valid다. 그래서 효과 분석에는 이 데이터를 그대로 썼다.

**cpu (worker 4, load 100).**
- checkoutservice CPU 0.004 → 0.296 core. throttled period 비율은 0 → 0.91이다. throttled 시간은 1.97 s/s로 r01(worker 1)의 0.38 s/s보다 크다.
- frontend→checkout p50/p90/p99: 4.5/9.9/72 → 28.4/91.7/164 ms. checkout에서 나가는 호출의 p99는 1~4 → 48~63 ms다.
- 사용자 영향: evaluation_v2가 **impacted**(latency_increase)로 판정했다. 다만 fault 구간 전체로는 p99 214 ms로 임계 483 ms 아래다. 판정은 짧은 스파이크(최악 30 s 창 p99 2,064 ms) 때문이다. success는 100 %다.

**delay (100 ms, jitter 10 ms, 방법 A).**
- `filter_targets` 기록:
  - direction to, 주입 pod는 frontend-5c676694c8-xfx5r(10.42.0.70).
  - 필터 대상은 ClusterIP 10.43.82.246과 productcatalog pod IP 10.42.0.67이다.
  - `selection_consistent: true`.
- **호출당 지연은 약 +100 ms다.** frontend→productcatalog p10 99.8 ms, p50 0.1 → 114.4 ms, p90 168, p99 195 ms, 오류 0이다. GetProduct와 ListProducts가 같다. gRPC는 연결을 재사용하므로 지연 구간을 한 번만 지난다. capability의 +200 ms는 새 연결이라 두 번 지난 값이다.
- **다른 edge:** recommendation→productcatalog p50 0.3 → 0.8 ms, frontend→currency 0.7 → 1.7 ms, 나머지 edge는 +0.2~1.4 ms였다. 200 ms 이상이나 오류는 없었다. control은 변화가 없었다. 이 작은 상승의 원인은 확인하지 못했다(tc 대상은 아니다).
- 제거 후 p50 0.1 ms로 원복했다.
- 사용자 영향: **impacted**(latency_increase, 주입 직후). p50 35 → 3,210 ms, p99 126 → 3,590 ms다. 페이지 하나가 productcatalog를 30번가량 직렬로 부르기 때문이다.
- 강도가 크다. 다만 이번 단계에서는 강도를 바꾸지 않았다.

**loss (2 %, correlation 25, 방법 A).** 결과는 **효과 없음**이다.
- 주입은 정상으로 기록됐다. AllInjected 09:19:12Z, AllRecovered 09:24:11Z(confirmed), injector succeeded. `filter_targets`는 delay와 같다(ClusterIP 10.43.82.246, pod IP 10.42.0.67, selection_consistent true). 살아 있는 object의 spec도 의도대로다.
- frontend→productcatalog 17,925 호출이 pre와 같았다. p50 0.1, p99 0.8 ms, mean 0.17 ms, 최대 4.8 ms, 오류 0이다. 5 ms를 넘는 호출은 0개였다. 다른 edge도 변화가 없다.
- 사용자 영향: 없음(incident status `fault_active_no_impact`). p99 124 ms, 최악 30 s 창 208 ms다.
- **2 % loss가 실제로 걸렸다면 이 결과는 나오기 어렵다.** 요청 세그먼트 약 360개가 버려졌을 것이다. 연결당 동시 요청이 거의 없으므로 회복은 TLP나 RTO에 기대야 하고, 그러면 최소 수 ms에서 200 ms가 더해진다. 즉 이번 run에서는 app 경로에 loss가 적용되지 않았을 가능성이 높다.
- 같은 템플릿 구조의 delay는 같은 pod에 적용됐고, capability probe의 loss 10 %도 적용됐다. 원인은 사후에 확인할 수 없었다. run 폴더에는 주입 중 tc 상태가 남지 않고, chaos-daemon 로그도 이미 회전됐다.
- **제안만 한다(실행하지 않음).** 5 %로 올리기 전에 진단을 먼저 한다.
  1. frontend→productcatalog에 loss 2 %를 짧게(60 s) 주입하고, 그동안 frontend netns의 `tc qdisc/filter`, ipset, `nstat` TcpRetransSegs를 덤프한다.
  2. run-attended가 AllInjected 시점에 출발 pod의 tc·ipset 상태를 fault-record에 남기게 한다.
  - 강도를 올리는 것만으로는 해결되지 않는다. 2 %가 실제로 걸렸다면 페이지 하나의 productcatalog 직렬 호출 약 30번 중 하나 이상이 손실될 확률은 1 − 0.98^30 ≈ 45 %다. 그러면 TLP/RTO 지연이 이미 span과 사용자 p99에 보였어야 한다.
  - 5 %(1 − 0.95^30 ≈ 79 %)는 진단에서 2 %가 적용된 것이 확인됐는데도 사용자 영향(p99 > baseline × 3)이 약할 때 올릴 다음 후보로만 둔다.
