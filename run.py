"""Make and post today's KidNuz quiz Reel and still.

Runs every weekday on GitHub Actions. Safe to run more than once: it records what it has
already posted for each episode in state/posted.json and never posts the same thing twice.

Environment:
  BUFFER_API_KEY                       from GitHub secrets (Instagram, Facebook and TikTok via Buffer)
  META_TOKEN, IG_USER_ID, FB_PAGE_ID   optional: post to Instagram/Facebook directly through Meta instead
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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from kidnuz_reels import audio, render, sources
from kidnuz_reels.buffer import Buffer
from kidnuz_reels.meta import Meta

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "posted.json"
MEDIA = ROOT / "media"
OUT = ROOT / "out"
PACIFIC = ZoneInfo("America/Los_Angeles")
POST_AFTER = (6, 25)  # 6:25 a.m. Pacific
DRY = os.environ.get("DRY_RUN") == "1"
if not DRY and not (os.environ.get("BUFFER_API_KEY") or os.environ.get("META_TOKEN")):
    print("No BUFFER_API_KEY secret yet, so this run makes the files without posting.")
    DRY = True
KEEP_DAYS = 21  # days of videos/stills kept in the public media folder
FORCE = os.environ.get("FORCE") == "1"
HASHTAGS = "#KidNuz #NewsForKids #KidsNews #CurrentEvents #KidsPodcast"


def wait_public(url: str, minutes: int = 5):
    """Wait until a file just pushed to the public repo can be fetched."""
    import time
    import requests
    for _ in range(minutes * 6):
        if requests.head(url, timeout=30).status_code == 200:
            return
        time.sleep(10)
    raise RuntimeError(f"{url} still isn't reachable after {minutes} minutes.")


def captions(question: str, link: str) -> tuple[str, str, str]:
    ig = (f"Today's KidNuz Quiz: {question}\n\n"
          f"Listen to today's episode of KidNuz, the daily news podcast for kids, to find out. Link in bio.\n\n{HASHTAGS}")
    fb = (f"Today's KidNuz Quiz: {question}\n\n"
          f"Listen to today's episode to find out: {link}\n\n{HASHTAGS}")
    tt = (f"Today's KidNuz Quiz: {question}\n\n"
          f"Listen to today's episode of KidNuz, the daily news podcast for kids, to find out. Link in bio.\n\n{HASHTAGS}")
    return ig, fb, tt


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
    # Three dates must match before anything posts: today's date, the newest RSS episode's date,
    # and a "Quiz for <today>" PDF on kidnuz.org/dailyquiz (checked below). On holidays and breaks
    # the newest episode and quiz are from an earlier day, so nothing is posted and nothing repeats.
    if not FORCE and ep.date.astimezone(PACIFIC).date() != now.date():
        print(f"No new episode for {now:%a %b %d}: the newest in the RSS feed is '{ep.title}' "
              f"from {ep.date:%a %b %d}. Skipping today (holiday or not uploaded yet); nothing posted.")
        return 0
    done = state.setdefault(ep.guid, {"title": ep.title})
    wanted = ["ig_reel", "ig_story", "ig_image", "fb_reel", "fb_photo", "tiktok"]
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
        if pdf is None:
            print(f"No '{sources._quiz_label(ep.date)}' quiz on kidnuz.org/dailyquiz yet. "
                  "Skipping today (holiday or not uploaded yet); nothing posted.")
            return 0
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
        reel = render.reel(browser, cfg, clip_audio, MEDIA / f"kidnuz-quiz-{stamp}.mp4")
        still = render.still(browser, cfg, MEDIA / f"kidnuz-quiz-{stamp}.jpg")
        browser.close()

    ig_cap, fb_cap, tt_cap = captions(question, link)
    (OUT / f"kidnuz-quiz-{stamp}.txt").write_text(
        f"Question: {question}\nHeard: {clip.spoken}\nEpisode: {link}\n\nInstagram caption:\n{ig_cap}\n\nFacebook caption:\n{fb_cap}\n\nTikTok caption:\n{tt_cap}\n")
    print(f"Made {reel.name} and {still.name}")
    if DRY:
        print("Dry run: not posting.")
        return 0

    # Buffer and Instagram fetch media from the web, so publish today's files in the public repo first.
    cutoff = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    old = [p for p in MEDIA.glob("kidnuz-quiz-*") if p.name[len("kidnuz-quiz-"):][:10] < cutoff]
    for p in old:
        p.unlink()
    save_state(state, f"Media for {ep.title}", [reel, still, *old])
    repo = os.environ.get("GITHUB_REPOSITORY", "jenniferliananderson-cmd/kidnuz-quiz-reels")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    base = f"https://raw.githubusercontent.com/{repo}/{branch}/media"
    reel_url, still_url = f"{base}/{reel.name}", f"{base}/{still.name}"
    wait_public(reel_url)
    wait_public(still_url)

    if os.environ.get("BUFFER_API_KEY"):
        buf = Buffer(os.environ["BUFFER_API_KEY"])
        jobs = {
            "ig_reel": lambda: buf.ig_reel(reel_url, ig_cap),
            "ig_story": lambda: buf.ig_story(reel_url),
            "ig_image": lambda: buf.ig_image(still_url, ig_cap),
            "fb_reel": lambda: buf.fb_reel(reel_url, fb_cap),
            "fb_photo": lambda: buf.fb_photo(still_url, fb_cap),
            "tiktok": lambda: buf.tiktok(reel_url, tt_cap),
        }
        # Accounts not connected in Buffer yet (e.g. TikTok while it's being sorted out) are skipped quietly.
        connected = buf.channels()
        for name, service in {"ig_reel": "instagram", "ig_story": "instagram", "ig_image": "instagram",
                              "fb_reel": "facebook", "fb_photo": "facebook", "tiktok": "tiktok"}.items():
            if service not in connected and name not in done:
                print(f"{name}: skipped, no {service} account connected in Buffer yet")
                jobs.pop(name)
    else:
        meta = Meta(os.environ["META_TOKEN"], os.environ["IG_USER_ID"], os.environ["FB_PAGE_ID"])
        jobs = {
            "ig_reel": lambda: meta.ig_reel(reel, ig_cap),
            "ig_story": lambda: meta.ig_story(reel),
            "ig_image": lambda: meta.ig_image(still_url, ig_cap),
            "fb_reel": lambda: meta.fb_reel(reel, fb_cap),
            "fb_photo": lambda: meta.fb_photo(still, fb_cap),
        }
        done.setdefault("tiktok", "skipped: TikTok needs Buffer")
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
