"""Make and post today's KidNuz quiz Reel and still.

Runs every weekday on GitHub Actions. Safe to run more than once: it records what it has
already posted for each episode in state/posted.json and never posts the same thing twice.

Environment:
  META_TOKEN, IG_USER_ID, FB_PAGE_ID   from GitHub secrets
  DRY_RUN=1                            make the files but post nothing
  FORCE=1                              ignore the posting-time and same-day checks (for manual tests)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from kidnuz_reels import audio, render, sources
from kidnuz_reels.meta import Meta

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "posted.json"
MEDIA = ROOT / "media"
OUT = ROOT / "out"
PACIFIC = ZoneInfo("America/Los_Angeles")
POST_AFTER = (6, 25)  # 6:25 a.m. Pacific
DRY = os.environ.get("DRY_RUN") == "1"
FORCE = os.environ.get("FORCE") == "1"
HASHTAGS = "#KidNuz #NewsForKids #KidsNews #CurrentEvents #KidsPodcast"


def captions(question: str, link: str) -> tuple[str, str]:
    ig = (f"Today's KidNuz Quiz: {question}\n\n"
          f"Listen to today's episode of KidNuz, the daily news podcast for kids, to find out. Link in bio.\n\n{HASHTAGS}")
    fb = (f"Today's KidNuz Quiz: {question}\n\n"
          f"Listen to today's episode to find out: {link}\n\n{HASHTAGS}")
    return ig, fb


def git(*args: str):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def save_state(state: dict, message: str, extra: list[Path] = ()):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    git("config", "user.name", "kidnuz-quiz-bot")
    git("config", "user.email", "kidnuz-quiz-bot@users.noreply.github.com")
    git("add", str(STATE), *[str(p) for p in extra])
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
        git("commit", "-m", message)
        git("pull", "--rebase", "-q")
        git("push", "-q")


def main() -> int:
    now = datetime.now(PACIFIC)
    if not FORCE and (now.weekday() > 4 or (now.hour, now.minute) < POST_AFTER):
        print(f"{now:%a %H:%M} Pacific: outside the posting window, nothing to do.")
        return 0

    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    ep = sources.latest_episode()
    print(f"Latest episode: {ep.title} ({ep.date:%a %b %d %H:%M %Z})")
    if not FORCE and ep.date.astimezone(PACIFIC).date() != now.date():
        print("Today's episode isn't in the feed yet; will try again on the next run.")
        return 0
    done = state.setdefault(ep.guid, {"title": ep.title})
    wanted = ["ig_reel", "ig_story", "ig_image", "fb_reel", "fb_photo"]
    if not DRY and all(k in done for k in wanted):
        print("Everything for this episode is already posted.")
        return 0

    OUT.mkdir(exist_ok=True)
    MEDIA.mkdir(exist_ok=True)
    day = ep.date.weekday() if ep.date.weekday() <= 4 else 0
    stamp = ep.date.strftime("%Y-%m-%d")

    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        tmp = Path(tmp)
        browser = pw.chromium.launch()
        web = browser.new_page()
        pdf = sources.quiz_pdf_url(web, ep.date)
        question = sources.first_question(pdf)
        link = sources.episode_page_url(web, ep.title)
        web.close()
        print(f"Quiz PDF: {pdf}\nQuestion 1: {question}\nEpisode page: {link}")

        mp3 = audio.download(ep.audio_url, tmp / "episode.mp3")
        clip = audio.find_question(audio.transcribe_words(mp3, tmp), question)
        print(f"Clip {clip.start:.2f}s to {clip.end:.2f}s. Heard: {clip.spoken}")
        clip_audio = audio.cut(mp3, clip, tmp / "question.m4a")

        cfg = {"day": day, "text": question, "audio": round(clip.end - clip.start, 3),
               "wordTimes": clip.word_times, "levels": audio.levels(clip_audio)}
        reel = render.reel(browser, cfg, clip_audio, OUT / f"kidnuz-quiz-{stamp}.mp4")
        still = render.still(browser, cfg, MEDIA / f"kidnuz-quiz-{stamp}.jpg")
        browser.close()

    ig_cap, fb_cap = captions(question, link)
    (OUT / f"kidnuz-quiz-{stamp}.txt").write_text(
        f"Question: {question}\nHeard: {clip.spoken}\nEpisode: {link}\n\nInstagram caption:\n{ig_cap}\n\nFacebook caption:\n{fb_cap}\n")
    print(f"Made {reel.name} and {still.name}")
    if DRY:
        print("Dry run: not posting.")
        return 0

    # The still has to be on the web for Instagram to fetch it; the public repo serves it.
    save_state(state, f"Still for {ep.title}", [still])
    repo = os.environ.get("GITHUB_REPOSITORY", "jenniferliananderson-cmd/kidnuz-quiz-reels")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    still_url = f"https://raw.githubusercontent.com/{repo}/{branch}/media/{still.name}"

    meta = Meta(os.environ["META_TOKEN"], os.environ["IG_USER_ID"], os.environ["FB_PAGE_ID"])
    jobs = {
        "ig_reel": lambda: meta.ig_reel(reel, ig_cap),
        "ig_story": lambda: meta.ig_story(reel),
        "ig_image": lambda: meta.ig_image(still_url, ig_cap),
        "fb_reel": lambda: meta.fb_reel(reel, fb_cap),
        "fb_photo": lambda: meta.fb_photo(still, fb_cap),
    }
    failed = []
    for name, job in jobs.items():
        if name in done:
            print(f"{name}: already posted ({done[name]})")
            continue
        try:
            done[name] = job()
            print(f"{name}: posted {done[name]}")
            save_state(state, f"Posted {name} for {ep.title}")
        except Exception:
            failed.append(name)
            print(f"{name}: FAILED")
            traceback.print_exc()
    if failed:
        print("Some posts failed; the next run will retry only those: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
