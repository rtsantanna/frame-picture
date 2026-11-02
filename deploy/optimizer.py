#!/usr/bin/env python3
"""
Frame Picture — otimizador local de fotos (Missao 02, secao 6).

Redimensiona IN-PLACE as copias locais em /data/photos para caber em uma area
alvo (padrao 1920x1080), preservando proporcao, orientacao EXIF, nome e
extensao. Nunca amplia, nunca corta, nunca estica. Substituicao atomica com
arquivo temporario no mesmo filesystem; em caso de falha, o original e
preservado e nao sobra lixo temporario.

Idempotente: arquivos ja dentro do limite sao pulados (nao reconverte).

Uso:
  python3 optimizer.py --scan DIR              # so analisa e relata (dry-run)
  python3 optimizer.py --apply DIR             # aplica (substitui in-place)
  opcoes: --max-w 1920 --max-h 1080 --quality 90 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict

try:
    from PIL import Image, ImageOps
except Exception as e:  # pragma: no cover
    print("ERRO: Pillow nao disponivel:", e, file=sys.stderr)
    sys.exit(2)

SUPPORTED = {".jpg", ".jpeg", ".png"}


@dataclass
class Result:
    analyzed: int = 0
    resized: int = 0
    already_ok: int = 0
    skipped_unsupported: int = 0
    errors: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    bytes_saved: int = 0
    details: list = field(default_factory=list)
    error_list: list = field(default_factory=list)


def _target_size(w: int, h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Dimensoes para caber em (max_w,max_h) preservando proporcao. So reduz."""
    scale = min(max_w / w, max_h / h, 1.0)  # <=1.0 => nunca amplia
    return (max(1, round(w * scale)), max(1, round(h * scale)))


def process_file(path: str, max_w: int, max_h: int, quality: int, apply: bool, res: Result) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        res.skipped_unsupported += 1
        return
    res.analyzed += 1
    name = os.path.basename(path)
    try:
        size_before = os.path.getsize(path)
        # 1) validar leitura/integridade
        with Image.open(path) as probe:
            probe.verify()  # detecta corrompidos sem decodificar tudo
        with Image.open(path) as im0:
            im = ImageOps.exif_transpose(im0)  # orientacao EXIF aplicada aos pixels
            ow, oh = im.size
            tw, th = _target_size(ow, oh, max_w, max_h)
            if (tw, th) == (ow, oh):
                res.already_ok += 1
                res.details.append({"file": name, "action": "ja_ok", "dims": f"{ow}x{oh}"})
                return
            # 2) redimensionar
            im_resized = im.resize((tw, th), Image.Resampling.LANCZOS)
            # 3) salvar em temporario no MESMO diretorio (mesmo filesystem -> replace atomico)
            d = os.path.dirname(path) or "."
            fd, tmp = tempfile.mkstemp(prefix=".fp_opt_", suffix=ext, dir=d)
            os.close(fd)
            try:
                if ext in (".jpg", ".jpeg"):
                    out = im_resized.convert("RGB") if im_resized.mode not in ("RGB", "L") else im_resized
                    out.save(tmp, format="JPEG", quality=quality, optimize=True, progressive=True)
                else:  # .png
                    im_resized.save(tmp, format="PNG", optimize=True)
                # 4) validar o arquivo gerado
                with Image.open(tmp) as chk:
                    chk.verify()
                with Image.open(tmp) as chk2:
                    if chk2.size != (tw, th):
                        raise ValueError(f"dims do temp {chk2.size} != esperado {(tw, th)}")
                size_after = os.path.getsize(tmp)
                if apply:
                    # 5) substituicao atomica, preservando nome
                    os.replace(tmp, path)
                    tmp = None
                else:
                    size_after = size_after  # dry-run: nao substitui
                res.resized += 1
                res.bytes_before += size_before
                res.bytes_after += size_after
                res.bytes_saved += max(0, size_before - size_after)
                res.details.append({
                    "file": name, "action": "resize",
                    "from": f"{ow}x{oh}", "to": f"{tw}x{th}",
                    "bytes_before": size_before, "bytes_after": size_after,
                    "aspect_ok": abs((ow / oh) - (tw / th)) < 0.01,
                    "no_upscale": tw <= ow and th <= oh,
                })
            finally:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)  # sem lixo temporario orfao
    except Exception as e:
        res.errors += 1
        res.error_list.append({"file": name, "error": str(e)})


def optimize_dir(root: str, max_w: int, max_h: int, quality: int, apply: bool) -> Result:
    res = Result()
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            if f.startswith(".fp_opt_"):
                continue
            process_file(os.path.join(dirpath, f), max_w, max_h, quality, apply, res)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Frame Picture — otimizador local de fotos")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--scan", metavar="DIR", help="apenas analisa (dry-run)")
    g.add_argument("--apply", metavar="DIR", help="aplica a substituicao in-place")
    ap.add_argument("--max-w", type=int, default=1920)
    ap.add_argument("--max-h", type=int, default=1080)
    ap.add_argument("--quality", type=int, default=90)
    ap.add_argument("--json", action="store_true", help="saida em JSON")
    args = ap.parse_args()

    root = args.apply or args.scan
    apply = args.apply is not None
    if not os.path.isdir(root):
        print(f"ERRO: diretorio inexistente: {root}", file=sys.stderr)
        return 2

    t0 = time.time()
    res = optimize_dir(root, args.max_w, args.max_h, args.quality, apply)
    dt = time.time() - t0

    if args.json:
        print(json.dumps(asdict(res), ensure_ascii=False))
    else:
        mode = "APLICADO" if apply else "DRY-RUN (sem alterar)"
        print(f"== Otimizador ({mode}) — {root} em {dt:.1f}s ==")
        print(f"  analisadas: {res.analyzed} | redimensionadas: {res.resized} | ja adequadas: {res.already_ok}")
        print(f"  nao suportadas: {res.skipped_unsupported} | erros: {res.errors}")
        print(f"  espaco: antes {res.bytes_before/1024:.0f} KiB -> depois {res.bytes_after/1024:.0f} KiB | economizado {res.bytes_saved/1024:.0f} KiB")
        for d in res.details:
            if d["action"] == "resize":
                flags = ("OK" if d["aspect_ok"] and d["no_upscale"] else "VERIFICAR")
                print(f"   - {d['file']}: {d['from']} -> {d['to']} ({d['bytes_before']//1024}->{d['bytes_after']//1024} KiB) [{flags}]")
        for e in res.error_list:
            print(f"   ! {e['file']}: {e['error']}")
    return 0 if res.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
