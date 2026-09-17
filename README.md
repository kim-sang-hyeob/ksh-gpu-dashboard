# KSH GPU Dashboard

Cloudflare Workers + D1 무료 플랜으로 여러 VESSL workspace의 GPU와 실험 상태를 모아 본다.

- Worker: `ksh-gpu-dashboard`
- URL: `https://ksh-gpu-dashboard.sanghyeop0416.workers.dev`
- D1: `ksh-gpu-dashboard-db`
- D1 binding: `DB`
- UI 접근: Cloudflare Access 계정 멤버 정책
- 상태 수신: Access service token + Worker `INGEST_KEY`

## 로컬 명령

번들 Node와 pnpm을 PATH에 넣고 실행한다.

```bash
pnpm install
pnpm run db:init
pnpm run deploy
```

## 데이터 보존 기준

D1에는 workspace·GPU·실험의 요약 상태만 저장한다. 영상, 체크포인트, 전체 로그,
SSH 비밀번호나 개인 키는 저장하지 않는다. 대용량 결과는 각 workspace에 두고 경로만 기록한다.

heartbeat 주기는 30초를 기본으로 하고 90초 이상 수신되지 않으면 UI에서 오프라인으로 표시한다.
`INGEST_KEY`와 Cloudflare Access service token은 저장소에 커밋하지 않는다.

## Workspace 에이전트

두 VESSL workspace에는 `/root/work/ksh-gpu-agent/`가 설치되어 있다. 에이전트는 GPU,
디스크, `/root/runs/INDEX.md`와 함께 VESSL SDK에서 현재 세션의 시작 시각과 168시간 제한을
읽어 종료 예정 시각을 보낸다. VESSL 메타데이터는 5분 동안 캐시하고 나머지 상태는 30초마다
갱신한다.

```bash
/root/work/ksh-gpu-agent/ksh-gpu-agent status
/root/work/ksh-gpu-agent/ksh-gpu-agent start
/root/work/ksh-gpu-agent/ksh-gpu-agent once
```

workspace를 다시 시작하면 `/root`의 코드와 설정은 남지만 프로세스는 종료된다. 새 세션에서
`start`를 한 번 실행하면 새 VESSL 시작 시각을 자동으로 읽어 대시보드의 남은 시간도 바뀐다.

현재 Access 서비스 토큰의 만료일은 2027-09-17이다. 만료 전 교체한 뒤 각 서버의
`/root/.config/ksh-gpu-agent/env`만 갱신하며, 값 자체는 문서나 저장소에 남기지 않는다.

## VESSL 자동 재시작

운영 저장소: `https://github.com/kim-sang-hyeob/ksh-gpu-dashboard`

`.github/workflows/vessl-autostart.yml`은 매시간 17분에 등록된 workspace를 확인하고 상태가
정확히 `stopped`일 때만 init script를 설정하고 공식 `vessl workspace start ID`를 요청한다.
`stopping`, `pending`, `running`과 조회 오류는 중지로 추정하지 않는다. 실행 결과에는 workspace
이름·ID·API 응답을 출력하지 않고 개수만 남긴다.

무료 운영을 위해 공개 GitHub 저장소의 표준 러너만 사용하며, 비공개 저장소에서는 job 자체를
실행하지 않는다. 공개 저장소의 예약 실행이 비활성화되지 않도록 월 1회 keepalive 파일만
갱신한다. 수동으로 중지한 workspace도 다시 시작되므로 정지 상태를 유지하려면 먼저
`AUTO_START_ENABLED=false`로 바꾼다.

Repository secret:

- `VESSL_ACCESS_TOKEN`

Repository variables:

- `AUTO_START_ENABLED=true`
- `VESSL_DEFAULT_ORGANIZATION=kaist-temp`
- `VESSL_WORKSPACE_IDS=85899412396,85899412397`

처음에는 Actions의 `workflow_dispatch`에서 `dry_run=true`로 인증과 조회만 검증한다. 성공 후
변수를 활성화한다. VESSL이 workspace를 다시 띄우면 저장된 init script가
`/root/work/server-setup/on-workspace-start.sh`를 실행해 비영속 작업 폴더와 대시보드 에이전트를
복구한다.

2026-09-18 기준 dry-run과 실제 모드 확인이 모두 성공했으며 `AUTO_START_ENABLED=true`다.
실제 모드 확인 당시 두 workspace는 `running`, 시작 요청과 실패는 각각 0건이었다.
