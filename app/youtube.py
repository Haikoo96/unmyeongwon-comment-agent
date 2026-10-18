"""YouTube Data API v3 + 자막."""
import os
import re

import httpx

from . import db
from .config import CHANNELS, CONFIG

API = "https://www.googleapis.com/youtube/v3"


class YouTubeError(RuntimeError):
    def __init__(self, status: int, reason: str):
        super().__init__(f"YouTube API 오류 {status}: {reason}")
        self.status, self.reason = status, reason


def _get(path: str, **params) -> dict:
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError(".env에 YOUTUBE_API_KEY가 없어요.")
    # 키는 헤더로 보내요. 오류 문구에 URL이 찍혀도 키가 화면에 나오지 않게요.
    r = httpx.get(f"{API}/{path}", params=params, headers={"X-Goog-Api-Key": key}, timeout=20)
    if r.status_code >= 400:
        try:
            reason = r.json()["error"]["errors"][0]["reason"]
        except Exception:
            reason = "unknown"
        raise YouTubeError(r.status_code, reason)
    return r.json()


def save_video(v: dict):
    with db.tx() as c:
        c.execute(
            """INSERT INTO videos (id, channel_id, channel_title, title, description, thumbnail, published_at)
               VALUES (:id, :channel_id, :channel_title, :title, :description, :thumbnail, :published_at)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title, thumbnail=excluded.thumbnail""", v)


def fetch_latest_videos() -> list[dict]:
    """허용 채널 각각의 업로드 목록에서 최신 영상을 가져와 DB에 저장해요."""
    per = CONFIG.get("videos_per_channel", 4)
    out = []
    for channel_id, name in CHANNELS.items():
        uploads = "UU" + channel_id[2:]  # 채널 업로드 재생목록 규칙
        data = _get("playlistItems", part="snippet", playlistId=uploads, maxResults=per)
        for it in data.get("items", []):
            s = it["snippet"]
            vid = s["resourceId"]["videoId"]
            thumbs = s.get("thumbnails", {})
            thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
            out.append({
                "id": vid, "channel_id": channel_id, "channel_title": name,
                "title": s["title"], "description": s.get("description", ""),
                "thumbnail": thumb, "published_at": s["publishedAt"],
            })
    for v in out:
        save_video(v)
    return sorted(out, key=lambda v: v["published_at"], reverse=True)


def fetch_video(video_id: str) -> dict:
    """링크 직접 입력용. 저장은 채널 확인을 통과한 뒤에 호출하는 쪽에서 해요."""
    data = _get("videos", part="snippet", id=video_id)
    if not data.get("items"):
        raise ValueError("영상을 찾을 수 없어요.")
    s = data["items"][0]["snippet"]
    return {
        "id": video_id, "channel_id": s["channelId"], "channel_title": s["channelTitle"],
        "title": s["title"], "description": s.get("description", ""),
        "thumbnail": s["thumbnails"].get("medium", {}).get("url"), "published_at": s["publishedAt"],
    }


def fetch_comments(video_id: str, n: int = 50) -> list[dict]:
    """인기순 댓글. 가짜 댓글 판별에 쓸 메타데이터도 같이 가져와요."""
    try:
        data = _get("commentThreads", part="snippet", videoId=video_id, order="relevance",
                    maxResults=n, textFormat="plainText")
    except YouTubeError as e:
        if e.reason == "commentsDisabled":
            return []  # 댓글이 꺼진 영상도 영상 내용만으로 분석해요
        raise
    out = []
    for it in data.get("items", []):
        top = it["snippet"]["topLevelComment"]["snippet"]
        out.append({
            "author": top.get("authorDisplayName"),
            "text": top["textDisplay"],
            "likes": top.get("likeCount", 0),
            "replies": it["snippet"].get("totalReplyCount", 0),
            "published_at": top.get("publishedAt"),
        })
    return out


def fetch_transcript(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        t = YouTubeTranscriptApi().fetch(video_id, languages=["ko", "en"])
        return " ".join(s.text for s in t)
    except Exception:
        return None  # 자막이 없으면 제목·설명으로 대신해요


def parse_video_id(url_or_id: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url_or_id)
    if m:
        return m.group(1)
    return url_or_id if re.fullmatch(r"[\w-]{11}", url_or_id) else None
