# 세팅 완료 조건 및 팀원 보고 양식

상태는 `통과 / 보완 필요 / 환경 접근 대기`로 구분하고 증거 경로를 적는다. 단순 YAML parse나 dry-run을 실제 장애 주입 성공으로 보고하지 않는다.

| 검증 항목 | 완료 기준 |
|---|---|
| 환경 지문 | OS/kernel/K8s/runtime/CNI/버전/digest/CPU/RAM/disk/context 기록 |
| 재설치 절차 | Linux overlay, Python 의존성, CLI 버전, 설치 순서 제공 |
| 영속 저장 | backend PVC/retention과 archive 위치, 예상 bytes/run 및 여유 용량 확인 |
| Endpoint | frontend/Prometheus/Tempo/Loki/OTel 연결이 재부팅·세션 종료 정책과 일치 |
| CPU capability | 대상 cgroup, quota, stress 효과와 throttling, 제거 증거 |
| Network capability | 전용 probe에서 delay 및 loss 적용/필터/실측/원복 증거 |
| Pod capability | 주입된 UID/상태 변화와 제거·서비스 정상화 증거 |
| Export | 필요한 raw source, source 주기/coverage, hash와 최신 view 포인터 확인 |
| Pair order | 두 순서 모두 작동하며 fault-first도 최종 control 매칭 평가 통과 |
| Schedule | 69 fault/69 control, 고유 ID, pair 일치, 홀수 개수 균형, seed 재현성 |
| Onset | 7~12분 배정, phase 합 1500초, 실제 주입 시각과 k6 schedule 기록 |
| Label | case/window 영향 분리, no-impact/transition/recovery 정책, 임계값 동결 |
| 누수 검사 | Chaos/qdisc 주입 증거/identity/time이 primary 모델 입력에 들어가지 않음 |
| Model view | sample count/mask, node/edge 결합, fold별 전처리와 provenance 확인 |
| 시험 수집 | CPU 및 delay 각 1 pair의 run 경로와 품질·원복 결과 |
| 테스트 | 기존 unit test 및 pair-order/schedule/누수 방지 관련 의미 있는 테스트 통과 |

## 결과 보고에 그대로 사용할 양식

```text
세팅 날짜:
작업한 소스 revision 또는 전달 ZIP SHA256:
Linux 접속/배포 환경 식별자(비밀번호·토큰 제외):
VM 자원 / 사용·여유 디스크:
Kubernetes context / namespaces:
배포 버전 및 image digest 파일:

구현한 기능:
수정 파일:
테스트 명령과 결과:

Capability 증거 디렉터리:
Capacity C와 판정식/측정 근거:
동결한 fault parameter 파일:
생성한 profile/schedule 경로 및 개수:

CPU 시험 pair ID / artifact 경로 / 결과:
Network 시험 pair ID / artifact 경로 / 결과:
중단 및 원복 검증 결과:

남은 문제와 영향:
예상 저장량 및 전체 시간 산정 근거:
한 pair 실행 명령:
전체 campaign 실행 명령:
전체 campaign 시작 가능 여부와 근거:
```

기존 `python -B -m unittest discover -s tests -v`는 초기 회귀 테스트 명령이다. 본 패키지 제작만으로 Linux live 검증이 완료된 것은 아니다.
