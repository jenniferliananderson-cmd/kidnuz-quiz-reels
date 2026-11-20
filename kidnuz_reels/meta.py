"""Posting to Instagram and the Facebook Page through Meta's Graph API."""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

VERSION = os.environ.get("GRAPH_VERSION", "v23.0")
GRAPH = f"https://graph.facebook.com/{VERSION}"


class Meta:
    def __init__(self, token: str, ig_user_id: str, page_id: str):
        self.token, self.ig, self.page = token, ig_user_id, page_id
        self._page_token = None

    # ---------- helpers ----------
    @staticmethod
    def _ok(r: requests.Response) -> dict:
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:500]}
        if r.status_code >= 400 or "error" in data:
            raise RuntimeError(f"Meta API error {r.status_code}: {data}")
        return data

    def page_token(self) -> str:
        if not self._page_token:
            d = self._ok(requests.get(f"{GRAPH}/{self.page}", params={"fields": "access_token", "access_token": self.token}, timeout=60))
            self._page_token = d["access_token"]
        return self._page_token

    def _wait_ig(self, container: str, minutes: int = 10):
        for _ in range(minutes * 6):
            d = self._ok(requests.get(f"{GRAPH}/{container}", params={"fields": "status_code,status", "access_token": self.token}, timeout=60))
            if d.get("status_code") == "FINISHED":
                return
            if d.get("status_code") in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram couldn't process the upload: {d}")
            time.sleep(10)
        raise RuntimeError("Instagram took too long to process the upload.")

    def _ig_publish(self, container: str) -> str:
        return self._ok(requests.post(f"{GRAPH}/{self.ig}/media_publish", data={"creation_id": container, "access_token": self.token}, timeout=60))["id"]

    def _ig_video(self, path: Path, media_type: str, caption: str | None) -> str:
        data = {"media_type": media_type, "upload_type": "resumable", "access_token": self.token}
        if caption:
            data["caption"] = caption
        if media_type == "REELS":
            data["share_to_feed"] = "false"  # Reels tab only; the still is the grid post
        c = self._ok(requests.post(f"{GRAPH}/{self.ig}/media", data=data, timeout=60))
        size = path.stat().st_size
        with open(path, "rb") as f:
            self._ok(requests.post(c["uri"], data=f, timeout=600,
                                   headers={"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)}))
        self._wait_ig(c["id"])
        return self._ig_publish(c["id"])

    # ---------- Instagram ----------
    def ig_reel(self, path: Path, caption: str) -> str:
        return self._ig_video(path, "REELS", caption)

    def ig_story(self, path: Path) -> str:
        return self._ig_video(path, "STORIES", None)

    def ig_image(self, image_url: str, caption: str) -> str:
        c = self._ok(requests.post(f"{GRAPH}/{self.ig}/media", data={"image_url": image_url, "caption": caption, "access_token": self.token}, timeout=60))
        self._wait_ig(c["id"], minutes=3)
        return self._ig_publish(c["id"])

    # ---------- Facebook Page ----------
    def fb_reel(self, path: Path, description: str) -> str:
        pt = self.page_token()
        s = self._ok(requests.post(f"{GRAPH}/{self.page}/video_reels", data={"upload_phase": "start", "access_token": pt}, timeout=60))
        size = path.stat().st_size
        with open(path, "rb") as f:
            self._ok(requests.post(s["upload_url"], data=f, timeout=600,
                                   headers={"Authorization": f"OAuth {pt}", "offset": "0", "file_size": str(size)}))
        self._ok(requests.post(f"{GRAPH}/{self.page}/video_reels", timeout=60, data={
            "upload_phase": "finish", "video_id": s["video_id"], "video_state": "PUBLISHED",
            "description": description, "access_token": pt}))
        return s["video_id"]

    def fb_photo(self, path: Path, caption: str) -> str:
        with open(path, "rb") as f:
            d = self._ok(requests.post(f"{GRAPH}/{self.page}/photos", timeout=120,
                                       data={"caption": caption, "published": "true", "access_token": self.page_token()},
                                       files={"source": (path.name, f, "image/jpeg")}))
        return d.get("post_id") or d["id"]
