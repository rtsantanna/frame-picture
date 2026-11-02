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

# 3.5) cursor invisivel (kiosk): gera um tema XCursor 1x1 transparente e aponta
# o labwc/wlroots para ele, escondendo o ponteiro do mouse na HDMI.
CURSOR_THEME_DIR="/root/.icons/transparent"
if [ ! -f "$CURSOR_THEME_DIR/cursors/left_ptr" ]; then
  echo "[start] gerando tema de cursor transparente"
  python3 - "$CURSOR_THEME_DIR" <<'PY' || echo "[start] aviso: nao foi possivel gerar o cursor transparente"
import os, struct, sys
base = sys.argv[1]
cur_dir = os.path.join(base, "cursors")
os.makedirs(cur_dir, exist_ok=True)
sizes = (24, 32, 48, 64)
imgs = []
for sz in sizes:
    chunk = struct.pack("<IIIIIIIII", 36, 0xfffd0002, sz, 1, 1, 1, 0, 0, 0)
    chunk += struct.pack("<I", 0x00000000)
    imgs.append((sz, chunk))
ntoc = len(imgs)
header = struct.pack("<4sIII", b"Xcur", 16, 0x00010000, ntoc)
toc = b""; pos = 16 + ntoc * 12; offsets = []
for sz, chunk in imgs:
    offsets.append(pos); pos += len(chunk)
for (sz, chunk), off in zip(imgs, offsets):
    toc += struct.pack("<III", 0xfffd0002, sz, off)
data = header + toc + b"".join(c for _, c in imgs)
names = ["left_ptr","default","pointer","arrow","top_left_arrow","xterm","text",
         "hand","hand1","hand2","grab","grabbing","crosshair","watch","wait",
         "left_ptr_watch","progress","move","all-scroll","not-allowed","help",
         "context-menu","cell","sb_h_double_arrow","sb_v_double_arrow","fleur"]
for n in names:
    with open(os.path.join(cur_dir, n), "wb") as f:
        f.write(data)
with open(os.path.join(base, "index.theme"), "w") as f:
    f.write("[Icon Theme]\nName=transparent\nComment=Invisible cursor for kiosk\n")
PY
fi
export XCURSOR_PATH="/root/.icons:/usr/share/icons"
export XCURSOR_THEME="transparent"
export XCURSOR_SIZE="24"

# 4) sobe o compositor labwc com o picframe como sessao
echo "[start] iniciando labwc + picframe run"
exec labwc -C "$PICFRAME_DIR/labwc" --session "picframe run"
