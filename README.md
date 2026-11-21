# KidNuz daily quiz Reels

Every weekday morning this makes and posts:

- a **9:16 Reel** (on Instagram it goes to the Reels tab only, not the profile grid): the first quiz question, read by the host, written on word by word, then "Listen to find out" and kidnuz.org/podcast
- the same video as an **Instagram Story**
- a **4:5 still** of the finished frame for the Instagram and Facebook feeds (this is the day's one Instagram grid post)

It posts to Instagram, the KidNuz Facebook Page and TikTok at about 6:30 a.m. Pacific, through Buffer.

## How it works

1. Reads the newest episode from the podcast feed (`feeds.megaphone.fm/STM6212107967`).
2. Finds that day's "Quiz for …" PDF on kidnuz.org/dailyquiz and takes **question 1** as the on-screen text.

   **It only posts when three dates match: today's date, the newest RSS episode's date, and a "Quiz for <today>" PDF on the quiz page.** On holidays and breaks (e.g. Monday when the newest episode and quiz are still Friday's), it posts nothing, so nothing is ever repeated.
3. Transcribes the first five minutes of the episode, finds "But first, today's KidNuz Quiz:", and cuts the audio from there to the end of the question.
4. Renders the approved design (`render/template.html`) frame by frame into an MP4, plus a JPEG still. The frame colour follows the weekday: cyan Monday, yellow Tuesday, red Wednesday, white Thursday, green Friday. The logo uses a white "KidNuz" wordmark (`assets/logo-white-wordmark.png`).
5. Publishes today's video and still in the public `media/` folder (kept 21 days), posts them through Buffer, and records what it posted in `state/posted.json`, so a re-run never posts twice.

Each run's files (video, still, captions, and what the transcript heard) are saved under the run's **Artifacts** in the Actions tab for 30 days.

## Setup

1. In Buffer, connect the KidNuz Instagram, Facebook Page and TikTok as channels.
2. In Buffer, create an API key (Settings → API, or publish.buffer.com/settings/api).
3. In this repo, add it as a secret named `BUFFER_API_KEY` (Settings → Secrets and variables → Actions → New repository secret).

Until that secret exists, the daily run makes the files and posts nothing.

(Optional, instead of Buffer for Instagram/Facebook: `META_TOKEN`, `IG_USER_ID`, `FB_PAGE_ID` from a Meta developer app. TikTok always goes through Buffer.)

## Running by hand

Actions → **Daily KidNuz quiz** → **Run workflow**. "Make … without posting" is ticked by default, so a manual run only makes the files for you to check. Untick it to post.

## Changing things

- Captions and hashtags: `captions()` and `HASHTAGS` in `run.py`
- Posting time: `POST_AFTER` in `run.py` (the schedule in `.github/workflows/daily.yml` just needs to run after it)
- Design: `render/template.html`
