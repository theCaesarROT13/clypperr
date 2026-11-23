#!/usr/bin/env python3
"""
clipper.py - genera clip verticali (9:16) con sottotitoli parola-per-parola
a partire da un video lungo e da un file txt con i timestamp.

I sottotitoli sono disegnati con Pillow e sovrapposti con il filtro "overlay"
di ffmpeg: NON serve che ffmpeg sia compilato con libass.

Formato di clips.txt (una clip per riga, # = commento):

    12:30-13:20 | Titolo della clip
    1:05:10-1:05:55 | Altra clip
    00:45-01:30

Uso:
    python clipper.py video.mp4 clips.txt
    python clipper.py video.mp4 clips.txt --mode crop --model medium -o clips_out

Requisiti: ffmpeg, faster-whisper, pillow, numpy
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

W, H = 1080, 1920
BAND_Y, BAND_H = 1300, 420  # fascia verticale occupata dai sottotitoli
TEXT_Y = 100  # centro verticale del testo dentro la fascia (=> y assoluta 1400)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


# ---------------------------------------------------------------- parsing ---
def to_seconds(ts: str) -> float:
    """'1:05:10' / '12:30' / '45' / '12:30.5' -> secondi."""
    parts = ts.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"timestamp non valido: {ts!r}")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return secs


def parse_clips(path: Path):
    clips = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        time_part, _, title = line.partition("|")
        m = re.match(r"^\s*([\d:.]+)\s*[-–—]\s*([\d:.]+)\s*$", time_part)
        if not m:
            print(f"[!] riga {n} ignorata (formato non valido): {raw}")
            continue
        start, end = to_seconds(m.group(1)), to_seconds(m.group(2))
        if end <= start:
            print(f"[!] riga {n} ignorata (fine <= inizio): {raw}")
            continue
        if end - start > 60:
            print(f"[!] riga {n}: la clip dura {end - start:.0f}s (>60s), la tengo comunque")
        clips.append({"start": start, "end": end, "title": title.strip() or f"clip {len(clips) + 1}"})
    return clips


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE)
    return re.sub(r"[\s_-]+", "-", text).strip("-")[:50] or "clip"


# ----------------------------------------------------------- trascrizione ---
_model = None


def load_wav(path: Path):
    """Legge un wav 16 kHz mono (creato da ffmpeg) e lo ritorna come array float32."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(media: Path, model_name: str, language: str):
    """Ritorna lista di parole [{'w','s','e'}] con tempi relativi alla clip."""
    global _model
    from faster_whisper import WhisperModel  # import tardivo

    if _model is None:
        print(f"    carico il modello Whisper '{model_name}' (la prima volta scarica i file)...")
        _model = WhisperModel(model_name, device="cpu", compute_type="int8")
    audio = load_wav(media)  # evita av.open() di faster-whisper (incompatibile con av recenti)
    segments, _ = _model.transcribe(
        audio, language=language, word_timestamps=True, vad_filter=True
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"w": text, "s": w.start, "e": w.end})
    return words


# ------------------------------------------------------------ sottotitoli ---
def load_font(size: int, custom: str | None = None):
    from PIL import ImageFont

    for p in ([custom] if custom else []) + FONT_CANDIDATES:
        if p and Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _layout(texts, custom_font, max_w):
    """Sceglie corpo e righe: prima prova su una riga (corpo >= 68), poi su due righe."""
    def wrap(font, space):
        widths = [font.getlength(t) for t in texts]
        lines, cur, cur_w = [], [], 0.0
        for i, w in enumerate(widths):
            add = w if not cur else space + w
            if cur and cur_w + add > max_w:
                lines.append(cur)
                cur, cur_w = [i], w
            else:
                cur.append(i)
                cur_w += add
        lines.append(cur)
        return lines, widths

    for size in range(92, 67, -4):  # una riga
        font = load_font(size, custom_font)
        space = font.getlength(" ")
        lines, widths = wrap(font, space)
        if len(lines) == 1:
            return font, size, space, lines, widths
    for size in range(92, 23, -4):  # fino a due righe
        font = load_font(size, custom_font)
        space = font.getlength(" ")
        lines, widths = wrap(font, space)
        if len(lines) <= 2 and max(widths) <= max_w:
            return font, size, space, lines, widths
    return font, size, space, lines, widths


def render_caption(texts, active: int, path: Path, custom_font=None, max_w=940):
    """Disegna 2-3 parole (la parola 'active' in giallo) in un PNG trasparente."""
    from PIL import Image, ImageDraw

    font, size, space, lines, widths = _layout(texts, custom_font, max_w)
    img = Image.new("RGBA", (W, BAND_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    stroke = max(4, size // 12)
    line_h = size * 1.2
    y = TEXT_Y - (len(lines) - 1) * line_h / 2
    for line in lines:
        total = sum(widths[i] for i in line) + space * (len(line) - 1)
        x = (W - total) / 2
        for i in line:
            color = (255, 230, 0, 255) if i == active else (255, 255, 255, 255)
            d.text((x, y), texts[i], font=font, fill=color, anchor="lm",
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += widths[i] + space
        y += line_h
    img.save(path)


def build_captions(words, tmp: Path, total_dur: float, group_size=3, custom_font=None):
    """
    Crea i PNG dei sottotitoli e un file 'captions.txt' (concat demuxer di ffmpeg)
    che li mostra ai tempi giusti. Ritorna il path del file.
    """
    from PIL import Image

    # raggruppa le parole
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= group_size or re.search(r"[.!?…]$", w["w"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    blank = tmp / "blank.png"
    Image.new("RGBA", (W, BAND_H), (0, 0, 0, 0)).save(blank)

    entries = []  # (png, durata)
    t = 0.0

    def blank_until(target):
        nonlocal t
        if target - t > 0.01:
            entries.append((blank, target - t))
            t = target

    n = 0
    for g in groups:
        texts = [re.sub(r"\s+", " ", w["w"]).upper() for w in g]
        for i, w in enumerate(g):
            start = max(w["s"], t)
            if start >= total_dur:
                continue
            end = g[i + 1]["s"] if i + 1 < len(g) else w["e"]
            end = min(max(end, start + 0.12), total_dur)
            if end <= start:
                continue
            blank_until(start)
            f = tmp / f"c{n:04d}.png"
            n += 1
            render_caption(texts, i, f, custom_font)
            entries.append((f, end - t))
            t = end
    blank_until(total_dur)
    entries.append((blank, 1.0))  # il concat ignora la durata dell'ultimo elemento

    lines = ["ffconcat version 1.0"]
    for f, dur in entries:
        safe = str(f.resolve()).replace("'", "'\\''")
        lines.append(f"file '{safe}'")
        lines.append(f"duration {dur:.3f}")
    out = tmp / "captions.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ------------------------------------------------------------------ ffmpeg ---
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise RuntimeError("ffmpeg ha dato errore")


def video_filter(mode: str, with_caps: bool) -> str:
    if mode == "crop":
        # ritaglio centrale a tutto schermo
        base = f"[0:v]scale=-2:{H},crop={W}:{H}[base]"
    else:
        # "blur": video intero al centro con sfondo sfocato (ideale per podcast a 2)
        base = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:5[bgb];"
            f"[fg]scale={W}:-2[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[base]"
        )
    if with_caps:
        return base + f";[base][1:v]overlay=0:{BAND_Y}:format=auto[v]"
    return base + ";[base]null[v]"


def make_clip(video: Path, clip: dict, out: Path, args):
    start, end = clip["start"], clip["end"]
    dur = end - start
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        caps = None
        if not args.no_subs:
            wav = tmp / "audio.wav"
            run(["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", str(video),
                 "-vn", "-ac", "1", "-ar", "16000", str(wav)])
            words = transcribe(wav, args.model, args.lang)
            if words:
                caps = build_captions(words, tmp, dur, group_size=args.words,
                                      custom_font=args.font)
            else:
                print("    nessun parlato rilevato, niente sottotitoli")

        cmd = ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", str(video.resolve())]
        if caps:
            cmd += ["-f", "concat", "-safe", "0", "-i", str(caps)]
        cmd += [
            "-filter_complex", video_filter(args.mode, bool(caps)),
            "-map", "[v]", "-map", "0:a?",
            "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out.resolve()),
        ]
        run(cmd)


# -------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser(description="Genera clip verticali sottotitolate")
    ap.add_argument("video", type=Path)
    ap.add_argument("clips", type=Path, help="file txt con i timestamp")
    ap.add_argument("-o", "--out", type=Path, default=Path("clips_out"))
    ap.add_argument("--mode", choices=["blur", "crop"], default="blur",
                    help="blur = video intero con sfondo sfocato; crop = ritaglio centrale")
    ap.add_argument("--model", default="small",
                    help="modello Whisper: base, small, medium, large-v3 (piu' grande = piu' preciso e lento)")
    ap.add_argument("--lang", default="it")
    ap.add_argument("--words", type=int, default=3, help="parole per riga di sottotitolo")
    ap.add_argument("--font", default=None, help="percorso di un file .ttf per i sottotitoli")
    ap.add_argument("--no-subs", action="store_true", help="solo taglio, senza sottotitoli")
    args = ap.parse_args()

    if not args.video.exists():
        sys.exit(f"Video non trovato: {args.video}")
    clips = parse_clips(args.clips)
    if not clips:
        sys.exit("Nessuna clip valida nel file txt.")
    if not args.no_subs:
        try:
            import PIL  # noqa: F401
        except ImportError:
            sys.exit("Manca Pillow. Installalo con:  pip install pillow")

    args.out.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(clips, 1):
        out = args.out / f"{i:02d}_{slugify(c['title'])}.mp4"
        print(f"[{i}/{len(clips)}] {c['title']}  ({c['end'] - c['start']:.0f}s)")
        make_clip(args.video, c, out, args)
        print(f"    -> {out}")
    print("\nFatto! Clip in:", args.out.resolve())


if __name__ == "__main__":
    main()
