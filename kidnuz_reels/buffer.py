"""Posting through Buffer's GraphQL API (https://developers.buffer.com).

One Buffer API key covers the KidNuz Instagram, Facebook Page and TikTok, which are connected
inside Buffer. Buffer fetches the video and image from public URLs (the public GitHub repo).
"""
from __future__ import annotations

import time

import requests

API = "https://api.buffer.com"

CREATE = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id status } }
    ... on MutationError { message }
  }
}"""

STATUS = """
query PostStatus($input: PostInput!) {
  post(input: $input) { id status externalLink error { message supportUrl } }
}"""


class Buffer:
    def __init__(self, api_key: str):
        self.key = api_key
        self._channels = None

    def _gql(self, query: str, variables: dict | None = None) -> dict:
        for attempt in range(4):
            r = requests.post(API, json={"query": query, "variables": variables or {}}, timeout=60,
                              headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "30")))
                continue
            data = r.json()
            if r.status_code >= 400 or data.get("errors"):
                raise RuntimeError(f"Buffer API error {r.status_code}: {data.get('errors') or data}")
            return data["data"]
        raise RuntimeError("Buffer kept rate-limiting the request.")

    def channels(self) -> dict[str, str]:
        """{'instagram': channel_id, 'facebook': ..., 'tiktok': ...} for the KidNuz organization."""
        if self._channels is None:
            orgs = self._gql("query { account { organizations { id name } } }")["account"]["organizations"]
            found = {}
            for org in orgs:
                chans = self._gql("query($input: ChannelsInput!) { channels(input: $input) { id name service } }",
                                  {"input": {"organizationId": org["id"]}})["channels"]
                for c in chans:
                    found.setdefault(c["service"].lower(), c["id"])
            self._channels = found
            print("Buffer channels: " + ", ".join(sorted(found)))
        return self._channels

    def _post(self, service: str, text: str, asset: dict, metadata: dict) -> str:
        chans = self.channels()
        if service not in chans:
            raise RuntimeError(f"No {service} account is connected in Buffer.")
        res = self._gql(CREATE, {"input": {
            "channelId": chans[service], "text": text, "schedulingType": "automatic", "mode": "shareNow",
            "assets": [asset], "metadata": {service: metadata} if metadata else None}})["createPost"]
        if "post" not in res:
            raise RuntimeError(f"Buffer refused the {service} post: {res.get('message')}")
        return self._wait(res["post"]["id"])

    def _wait(self, post_id: str, minutes: int = 10) -> str:
        for _ in range(minutes * 4):
            p = self._gql(STATUS, {"input": {"id": post_id}})["post"]
            if p["status"] == "sent":
                return p.get("externalLink") or post_id
            if p["status"] == "error":
                raise RuntimeError(f"Buffer couldn't publish post {post_id}: {p.get('error')}")
            time.sleep(15)
        raise RuntimeError(f"Buffer post {post_id} was still '{p['status']}' after {minutes} minutes.")

    # ---------- what KidNuz posts each day ----------
    def ig_reel(self, video_url: str, caption: str) -> str:
        return self._post("instagram", caption, {"video": {"url": video_url}}, {"type": "reel", "shouldShareToFeed": True})

    def ig_story(self, video_url: str) -> str:
        return self._post("instagram", "", {"video": {"url": video_url}}, {"type": "story", "shouldShareToFeed": False})

    def ig_image(self, image_url: str, caption: str) -> str:
        return self._post("instagram", caption, {"image": {"url": image_url}}, {"type": "post", "shouldShareToFeed": True})

    def fb_reel(self, video_url: str, caption: str) -> str:
        return self._post("facebook", caption, {"video": {"url": video_url}}, {"type": "reel"})

    def fb_photo(self, image_url: str, caption: str) -> str:
        return self._post("facebook", caption, {"image": {"url": image_url}}, {"type": "post"})

    def tiktok(self, video_url: str, caption: str) -> str:
        return self._post("tiktok", caption, {"video": {"url": video_url}}, {})
