# ksh-run

두 GPU 서버에서 같은 형식으로 정식 실험을 시작하고 기록하는 작은 실행기다. 외부 패키지는 사용하지 않는다.

```bash
ksh-run \
  --project lvsm \
  --gpu 0,1 \
  --goal "768-token baseline" \
  --architecture "Encoder -> 768 Tokens -> DiT -> Decoder" \
  --dataset "miniworld-eye-static/v1" \
  --workdir /root/work/miniworld-eye-static \
  -- python train.py --config configs/train.yaml
```

기본 실행은 SSH가 끊겨도 계속되며 `/root/runs/<project>/<run_id>/` 아래에 `meta.json`, `README.md`, `command.sh`, 환경 정보, 로그를 만든다. 종료 코드는 `meta.json`과 `/root/runs/INDEX.md`에 자동 반영된다.

스모크 테스트는 기록을 만들지 않고 임시 디렉터리를 반드시 삭제한다.

```bash
ksh-run --project lvsm --gpu 0 --goal "loader smoke" --smoke -- python /root/work/miniworld-eye-static/scripts/check_loader.py
```
