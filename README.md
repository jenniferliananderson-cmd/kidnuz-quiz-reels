# KidNuz daily quiz Reels

Every weekday morning this makes and posts:

- a **9:16 Reel**: the first quiz question, read by the host, written on word by word, then "Listen to find out" and kidnuz.org/podcast
- the same video as an **Instagram Story**
- a **4:5 still** of the finished frame for the Instagram and Facebook feeds

It posts to Instagram and the KidNuz Facebook Page at about 6:30 a.m. Pacific.

## How it works

1. Reads the newest episode from the podcast feed (`feeds.megaphone.fm/STM6212107967`).
2. Finds that day's "Quiz for …" PDF on kidnuz.org/dailyquiz and takes **question 1** as the on-screen text.
3. Transcribes the first five minutes of the episode, finds "But first, today's KidNuz Quiz:", and cuts the audio from there to the end of the question.
4. Renders the approved design (`render/template.html`) frame by frame into an MP4, plus a JPEG still. The frame colour follows the weekday: cyan Monday, yellow Tuesday, red Wednesday, white Thursday, striped Friday.
5. Posts through Meta's Graph API and records what it posted in `state/posted.json`, so a re-run never posts twice.

Each run's files (video, still, captions, and what the transcript heard) are saved under the run's **Artifacts** in the Actions tab for 30 days.

## Setup

Add three repository secrets (Settings → Secrets and variables → Actions):

| Secret | What it is |
|---|---|
| `META_TOKEN` | A long-lived system-user token from Meta Business settings with `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `pages_manage_posts` |
| `IG_USER_ID` | The Instagram professional account ID linked to the KidNuz Page |
| `FB_PAGE_ID` | The KidNuz Facebook Page ID |

## Running by hand

Actions → **Daily KidNuz quiz** → **Run workflow**. "Make … without posting" is ticked by default, so a manual run only makes the files for you to check. Untick it to post.

## Changing things

- Captions and hashtags: `captions()` and `HASHTAGS` in `run.py`
- Posting time: `POST_AFTER` in `run.py` (the schedule in `.github/workflows/daily.yml` just needs to run after it)
- Design: `render/template.html`
