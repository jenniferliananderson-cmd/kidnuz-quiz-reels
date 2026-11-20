"""Find the first quiz question in the episode audio and cut it out.

The episode always says "But first, today's KidNuz Quiz:" and then reads the question.
We transcribe the first few minutes with word timings, find that line, and cut from the
first word after "Quiz" to the end of the question.
"""
from __future__ import annotations

import difflib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests

SCAN_SECONDS = 300          # the quiz comes near the top of the episode
MAX_QUESTION_SECONDS = 40


@dataclass
class Clip:
    start: float
    end: float
    word_times: list[float]   # one per on-screen word, seconds from clip start
    spoken: str               # what the transcript heard, for the log


def download(url: str, dest: Path) -> Path:
    with requests.get(url, stream=True, timeout=120, headers={"User-Agent": "KidNuzQuizReels/1.0"}) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return dest


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))


def transcribe_words(mp3: Path, workdir: Path):
    from faster_whisper import WhisperModel
    head = workdir / "head.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-t", str(SCAN_SECONDS),
                    "-ac", "1", "-ar", "16000", str(head)], check=True)
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(head), word_timestamps=True, vad_filter=False,
                                   initial_prompt="KidNuz. But first, today's KidNuz Quiz:")
    return [w for s in segments for w in (s.words or [])]


def find_question(words, question: str) -> Clip:
    norm = [_norm(w.word) for w in words]
    # 1. the cue: "quiz" with "first" (or "today's") just before it
    cue = None
    for i, w in enumerate(norm):
        if w.startswith("quiz") and any(x in ("first", "today's", "todays") for x in norm[max(0, i - 5):i]):
            cue = i
            break
    if cue is None:
        cue = next((i for i, w in enumerate(norm) if w.startswith("quiz")), None)
    if cue is None or cue + 1 >= len(words):
        heard = " ".join(w.word.strip() for w in words[:80])
        raise RuntimeError("Couldn't hear 'today's KidNuz Quiz' in the first five minutes. Heard: " + heard)
    first = cue + 1
    start = max(0.0, words[first].start - 0.12)

    # 2. the end: where the transcript reaches the question's last word
    qwords = [_norm(w) for w in question.split()]
    qwords = [w for w in qwords if w]
    last, prev = qwords[-1], (qwords[-2] if len(qwords) > 1 else "")
    end_i = None
    for j in range(first, len(words)):
        if words[j].end - start > MAX_QUESTION_SECONDS:
            break
        near = j - first + 1 >= 0.5 * len(qwords)
        if near and difflib.SequenceMatcher(None, norm[j], last).ratio() > 0.75 and (
                not prev or difflib.SequenceMatcher(None, norm[j - 1], prev).ratio() > 0.6 or words[j].word.strip().endswith("?")):
            end_i = j
            break
    if end_i is None:  # fall back to the first question mark the transcript wrote
        end_i = next((j for j in range(first, len(words))
                      if words[j].word.strip().endswith("?") and words[j].end - start <= MAX_QUESTION_SECONDS), None)
    if end_i is None:
        raise RuntimeError("Found the quiz cue but couldn't tell where the question ends.")
    end = words[end_i].end + 0.3
    if end_i + 1 < len(words):
        end = min(end, words[end_i + 1].start - 0.02)

    # 3. timing for each on-screen word, spread over the spoken words
    spoken = words[first:end_i + 1]
    n, m = len(question.split()), len(spoken)
    times = [max(0.0, spoken[round(k * (m - 1) / max(1, n - 1))].start - start) for k in range(n)]
    return Clip(start=start, end=end, word_times=times, spoken=" ".join(w.word.strip() for w in spoken))


def cut(mp3: Path, clip: Clip, dest: Path) -> Path:
    dur = clip.end - clip.start
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{clip.start:.3f}", "-t", f"{dur:.3f}", "-i", str(mp3),
                    "-af", f"afade=t=in:d=0.04,afade=t=out:st={max(0, dur - 0.25):.3f}:d=0.25",
                    "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "160k", str(dest)], check=True)
    return dest


def levels(clip_audio: Path, fps: int = 30) -> list[float]:
    """Loudness per video frame, 0..1, so the sound wave follows the voice."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(clip_audio), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], check=True, capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    hop = 16000 // fps
    rms = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2)) for i in range(0, len(x), hop)] or [0.0])
    top = np.percentile(rms, 95) or 1.0
    return [round(float(v), 3) for v in np.sqrt(np.clip(rms / top, 0, 1))]
