"""Turn the design template into a 9:16 MP4 Reel and a 4:5 JPEG still."""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

from PIL import Image

TEMPLATE = (Path(__file__).resolve().parent.parent / "render" / "template.html").as_uri()
FPS = 30


def _open(browser, width: int, height: int):
    page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
    page.goto(TEMPLATE, wait_until="load", timeout=60000)
    # load every face the design uses before checking, so frame 1 is already in the right type
    page.evaluate("""Promise.all(['400 40px Fraunces', '500 40px Fraunces', '500 40px Poppins', '600 40px Poppins']
        .map(f => document.fonts.load(f, 'KidNuz Quiz'))).then(() => document.fonts.ready)""")
    ok = page.evaluate("document.fonts.check('400 40px Fraunces') && document.fonts.check('600 40px Poppins')")
    if not ok:
        raise RuntimeError("The Fraunces/Poppins fonts didn't load, so the video would use the wrong type.")
    return page


def reel(browser, cfg: dict, clip_audio: Path, dest: Path) -> Path:
    page = _open(browser, 1080, 1920)
    info = page.evaluate(f"setup({json.dumps({**cfg, 'format': 'reel'})})")
    duration, a0 = info["duration"], info["audioStart"]
    frames = int(round(duration * FPS))
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
         "-i", str(clip_audio),
         "-filter_complex", f"[1:a]adelay={int(a0 * 1000)}:all=1,apad[a]",
         "-map", "0:v", "-map", "[a]", "-t", f"{frames / FPS:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
         "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(dest)],
        stdin=subprocess.PIPE)
    reel_el = page.locator("#reel")
    for k in range(frames):
        page.evaluate(f"renderAt({k / FPS})")
        enc.stdin.write(reel_el.screenshot(type="png", animations="disabled"))
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg couldn't make the video.")
    page.close()
    return dest


def still(browser, cfg: dict, dest: Path) -> Path:
    page = _open(browser, 1080, 1350)
    page.evaluate(f"setup({json.dumps({**cfg, 'format': 'feed'})})")
    page.evaluate("renderAt(1e6)")
    png = page.locator("#reel").screenshot(type="png", animations="disabled")
    Image.open(io.BytesIO(png)).convert("RGB").save(dest, "JPEG", quality=92, optimize=True)
    page.close()
    return dest
