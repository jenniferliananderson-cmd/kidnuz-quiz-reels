"""Where each day's material comes from: the podcast feed, the quiz PDF, and the episode page."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import feedparser
import requests
from pypdf import PdfReader

FEED_URL = "https://feeds.megaphone.fm/STM6212107967"
QUIZ_PAGE = "https://www.kidnuz.org/dailyquiz"
PODCAST_PAGE = "https://www.kidnuz.org/podcast"
EASTERN = ZoneInfo("America/New_York")
UA = {"User-Agent": "KidNuzQuizReels/1.0 (+https://github.com/jenniferliananderson-cmd/kidnuz-quiz-reels)"}


@dataclass
class Episode:
    guid: str
    title: str          # e.g. "11.19.26"
    date: datetime      # publish time, Eastern
    audio_url: str


def latest_episode() -> Episode:
    feed = feedparser.parse(requests.get(FEED_URL, headers=UA, timeout=60).content)
    if not feed.entries:
        raise RuntimeError("The podcast feed had no episodes.")
    e = feed.entries[0]
    audio = next((l.href for l in e.get("links", []) if l.get("rel") == "enclosure"), None)
    if not audio:
        raise RuntimeError(f"Episode {e.get('title')} has no audio file in the feed.")
    when = parsedate_to_datetime(e.published).astimezone(EASTERN)
    return Episode(guid=e.get("id") or audio, title=e.title.strip(), date=when, audio_url=audio)


def _quiz_label(d: datetime) -> str:
    return f"Quiz for {d.strftime('%B')} {d.day}, {d.year}"


def quiz_pdf_url(page, d: datetime) -> str:
    """Find the 'Quiz for <Month D, YYYY>' link on the Daily Quiz page (rendered with Playwright)."""
    page.goto(QUIZ_PAGE, wait_until="domcontentloaded", timeout=60000)
    label = _quiz_label(d)
    link = page.get_by_role("link", name=re.compile(re.escape(label), re.I)).first
    link.wait_for(timeout=30000)
    href = link.get_attribute("href")
    if not href:
        raise RuntimeError(f"Found '{label}' on the quiz page but it has no link.")
    return href


def first_question(pdf_url: str) -> str:
    """Return the first numbered question from the quiz PDF, up to and including its question mark."""
    data = requests.get(pdf_url, headers=UA, timeout=60, allow_redirects=True).content
    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    m = re.search(r"(?:^|\n)\s*1\s*[.)]\s*(.+?\?)", text, re.S)
    if not m:
        raise RuntimeError("Couldn't find question 1 in the quiz PDF. First 400 characters:\n" + text[:400])
    q = re.sub(r"\s+", " ", m.group(1)).strip()
    q = q.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    if len(q) > 320:
        raise RuntimeError(f"Question 1 looks too long to be one question ({len(q)} characters): {q[:120]}...")
    return q


def episode_page_url(page, title: str) -> str:
    """The episode's own page on kidnuz.org, e.g. https://www.kidnuz.org/podcast/episode/39432ef3/111926."""
    try:
        page.goto(PODCAST_PAGE, wait_until="networkidle", timeout=90000)
        # 1. a plain link to the episode, anywhere on the page or inside its embedded frames
        for frame in page.frames:
            for a in frame.locator("a[href*='/podcast/episode/']").all():
                href = a.get_attribute("href") or ""
                if href.rstrip("/").endswith(title.replace(".", "")):
                    return href.split("?")[0]
        # 2. otherwise click the episode title (it may live in an embedded frame) and read the new address
        for frame in page.frames:
            item = frame.get_by_text(title, exact=True).first
            if item.count():
                item.click()
                page.wait_for_url(re.compile(r"/podcast/episode/"), timeout=20000)
                return page.url.split("?")[0]
        raise RuntimeError(f"'{title}' isn't listed on the podcast page yet")
    except Exception as err:  # the general podcast page is a fine fallback
        print(f"Couldn't find the episode page for {title}: {err}. Using the podcast page instead.")
        return PODCAST_PAGE
