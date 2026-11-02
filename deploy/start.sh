#!/usr/bin/env bash
# Frame Picture — arranque do container: prepara runtime, inicializa, configura
# o diretorio de fotos e sobe o labwc (Wayland-kiosk) com o picframe run.
set -euo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/0}"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

PICFRAME_DIR="${PICFRAME_DIR:-/root/.picframe}"
PIC_DIR="${PIC_DIR:-/data/photos}"
mkdir -p "$PICFRAME_DIR"

# 1) init idempotente (cria dirs, assets, config.db3, media.db3) se ainda nao existir
if [ ! -f "$PICFRAME_DIR/data/config.db3" ]; then
  echo "[start] picframe init em $PICFRAME_DIR"
  picframe init --force --dir "$PICFRAME_DIR" || picframe init --force "$PICFRAME_DIR" || true
fi

# 2) aponta a biblioteca para /data/photos (chave model.pic_dir)
python3 - "$PICFRAME_DIR" "$PIC_DIR" <<'PY' || echo "[start] aviso: nao foi possivel setar pic_dir programaticamente"
import sys, os
base, picdir = sys.argv[1], sys.argv[2]
try:
    from picframe.core.repositories.sqlite_config import SQLiteConfigRepository
    from picframe.core.services.resource_paths import ResourcePaths
    rp = ResourcePaths.from_base_dir(base)
    repo = SQLiteConfigRepository(os.path.join(rp.resolve_data_dir() if hasattr(rp,'resolve_data_dir') else os.path.join(base,'data'), 'config.db3'))
    repo.set_app_config('model.pic_dir', picdir)
    print('[start] model.pic_dir =', picdir)
except Exception as e:
    print('[start] fallback pic_dir:', e)
    raise SystemExit(1)
PY

# 3) config do labwc (regras de janela do picframe)
mkdir -p "$PICFRAME_DIR/labwc"
cp -f /labwc-rc.xml "$PICFRAME_DIR/labwc/rc.xml"

# 4) sobe o compositor labwc com o picframe como sessao
echo "[start] iniciando labwc + picframe run"
exec labwc -C "$PICFRAME_DIR/labwc" --session "picframe run"
