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
