# 새 수집 PC 세팅 (병렬 수집용)

206-40 외 PC 2대에서 정식 수집을 돌리기 위한 준비 순서다. 병렬 수집 규칙(브랜치, shard, 데이터 모으기)은 [`README.md` 8절](README.md#8-병렬-수집-pc-3대-206-40--2대)에 있다.
각 단계의 증거는 `linux/out/` 아래에 남는다. 앞 단계가 FAIL이면 다음 단계로 가지 않고 206-40에 보고한다.
아래에서 `<pc이름>`은 그 PC의 `hostname` 출력이다. 3대가 서로 달라야 한다(같으면 수집 전에 hostname을 바꾼다).

## 0. 준비물

- Ubuntu LTS, 로컬 디스크 여유 **400 GiB 이상**(PC당 23 pair × 약 5.1 GiB ≈ 120 GiB + 이미지·PVC·여유). 경로가 NFS면 안 된다(preflight가 확인한다).
- sudo 권한이 있는 사람(1~2단계의 sudo 명령만 실행).
- 수집 기간 동안 재부팅 유예. 로그아웃하지 않고 화면 잠금만 한다.

## 1. clone과 브랜치

```bash
cd ~/Documents
git clone https://github.com/esther033/sentrix-final-v1.git sentrix-final-v1   # 폴더 이름은 sentrix-final-v1
cd sentrix-final-v1
hostname                                   # = <pc이름>, 206-40에 알려 준다 (shard 이름)
git fetch --tags
git switch -c collect-$(hostname) <태그>   # 206-40이 정한 태그. 태그 전 세팅 단계에서는 origin/school-pc
```

- 이 PC에서는 코드를 고치지 않는다. commit하는 것은 `docs/pc/<pc이름>.md`와 `incidents/`뿐이다.
- 태그가 아직 없을 때(세팅만 먼저 할 때)는 `origin/school-pc`에서 브랜치를 만들고, 수집 전에 태그로 옮긴다(`git switch -C collect-$(hostname) <태그>`).

## 2. preflight (sudo 불필요)

```bash
bash linux/00-preflight.sh
```

`linux/out/preflight-<host>-*/summary.txt`의 PASS/WARN/FAIL을 `docs/pc/<pc이름>.md`에 옮긴다. 특히 sch_netem, 디스크 종류·여유, RAM, linger, 외부 접속을 확인한다.

## 3. 설치 (사람이 sudo로)

```bash
bash linux/01-install-k3s.sh               # sudo: k3s(버전 고정), sch_netem 상시 로드, sysctl, ~/.kube/config
sudo loginctl enable-linger "$USER"        # 로그아웃해도 tmux queue가 살아 있게 (권장)
bash linux/02-install-cli.sh               # ~/.local/bin 에 helm, k6 (sudo 불필요)
export PATH="$HOME/.local/bin:$PATH"
bash linux/03-python-env.sh                # .venv + 회귀 테스트 (모두 OK여야 한다)
```

- `linux/config/versions.env`의 버전을 바꾸지 않는다. 다르면 206-40과 같은 조건이 아니게 된다.
- 듀얼부트 PC면 부팅 직후 시계가 틀어져 있을 수 있다. `timedatectl show -p NTPSynchronized --value`가 `yes`일 때만 run이 시작된다.

## 4. chart 받기와 배포

```bash
bash linux/fetch-charts.sh                 # linux/charts/ 에 고정 chart tgz, digest 검증
bash linux/04-deploy-stack.sh              # HDD면 이미지 pull·PVC 준비에 오래 걸린다
bash linux/05-verify.sh                    # endpoint·series·digest PASS
```

- `linux/values/*.yaml`(메모리 limit, retention 등)은 206-40 기준값 그대로 쓴다. RAM이 15 GiB보다 작으면 고치지 말고 206-40에 먼저 보고한다.

## 5. capability

```bash
bash linux/capability/run-all.sh           # cpu, pod, network(ping + Service 경로, 방법 A)
kubectl delete ns sentrix-probe
```

`linux/out/capability-*/` 경로와 결과(모두 PASS)를 `docs/pc/<pc이름>.md`에 적는다.

## 6. 처리 용량 확인

```bash
set -a; . linux/config/endpoints.env; set +a
.venv/bin/python -B scripts/capacity-sweep.py --rates 4,6,8 --minutes 5 --max-p99-ms 500 --campaign linux-v1-$(hostname)
```

약 1시간이 걸린다(rate당 5분 run + 후처리). 판정과 206-40 비교 기준은 [README 8.3](README.md#83-새-pc-처리-용량-확인과-비교-기준)에 있다. rate 4와 6이 PASS여야 수집할 수 있다.

## 7. 기록과 보고

`docs/pc/<pc이름>.md`를 만들고 commit·push한다(`git push -u origin collect-$(hostname)`). 내용:

- 하드웨어: CPU 모델·코어, RAM, 디스크(SSD/HDD, `lsblk -d -o NAME,ROTA,MODEL,SIZE`), OS·커널
- k3s·Chaos Mesh·k6 버전(05-verify 출력), kube-proxy 모드, CNI
- preflight, capability, 처리 용량 결과와 경로
- 블록 일지 표(날짜, 시작·종료, 완료·실패 pair, 디스크, 특이사항)

수집 시작(README 8.5)은 206-40이 태그와 shard를 준 뒤에만 한다.
