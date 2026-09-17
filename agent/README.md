# ksh GPU agent

각 workspace에서 30초마다 GPU·디스크·`/root/runs/INDEX.md` 상태를 보낸다. VESSL SDK에서 현재 실행 세션의 시작 시각과 최대 실행 시간을 5분 캐시로 읽어 만료 시각도 전송한다. 비밀값은 소스와 분리해 `/root/.config/ksh-gpu-agent/env`에 권한 `600`으로 저장한다.

서버 설치 위치:

- 코드: `/root/work/ksh-gpu-agent/`
- 설정: `/root/.config/ksh-gpu-agent/env`
- PID·로그: `/root/runs/_system/ksh-gpu-agent/`

관리 명령:

```bash
/root/work/ksh-gpu-agent/ksh-gpu-agent collect  # 전송 없이 수집 결과 확인
/root/work/ksh-gpu-agent/ksh-gpu-agent once     # 한 번 전송
/root/work/ksh-gpu-agent/ksh-gpu-agent start
/root/work/ksh-gpu-agent/ksh-gpu-agent status
/root/work/ksh-gpu-agent/ksh-gpu-agent stop
```

workspace가 다시 시작되면 `/root`의 코드와 설정은 유지되지만 프로세스는 종료된다. 접속 후 `start`를 한 번 실행한다. `start`는 중복 실행을 막는다.
