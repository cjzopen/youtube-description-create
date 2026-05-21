import os
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv()

_API_BASE = "https://www.googleapis.com/youtube/v3"


def _get_channel_id(handle: str, api_key: str) -> str:
    handle = handle.lstrip("@")
    resp = requests.get(
        f"{_API_BASE}/channels",
        params={"part": "id", "forHandle": handle, "key": api_key},
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise ValueError(f"找不到頻道：@{handle}")
    return items[0]["id"]


def _get_playlist_video_ids(playlist_id: str, api_key: str, since: datetime) -> set[str]:
    """從播放清單取得所有影片 ID，只保留 since 之後發布的。"""
    ids = set()
    page_token = None

    while True:
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(f"{_API_BASE}/playlistItems", params=params)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            published_str = item["snippet"]["publishedAt"]
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            if published >= since:
                video_id = item["snippet"]["resourceId"]["videoId"]
                ids.add(video_id)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return ids


def get_video_metadata(video_ids: list[str], api_key: str) -> dict[str, dict]:
    """批次取得影片原始 title 與上傳日期，回傳 {video_id: {title, published_at}}。"""
    result = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = requests.get(
            f"{_API_BASE}/videos",
            params={"part": "snippet", "id": ",".join(batch), "key": api_key},
        )
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            vid = item["id"]
            snippet = item["snippet"]
            result[vid] = {
                "original_title": snippet["title"],
                "published_at": snippet["publishedAt"][:10],  # YYYY-MM-DD
            }
    return result


def fetch_channel_videos(
    channel: str, api_key: str, since_date: str
) -> tuple[list[str], list[str]]:
    """
    回傳 (regular_ids, shorts_ids)，只含 since_date（YYYY-MM-DD）之後發布的影片。
    Shorts 判斷：出現在頻道自動產生的 Shorts 播放清單（UUSH...）中者。
    """
    since = datetime.fromisoformat(since_date).replace(tzinfo=timezone.utc)
    channel_id = _get_channel_id(channel, api_key)
    suffix = channel_id[2:]  # 去掉 "UC"

    uploads_playlist = "UU" + suffix
    shorts_playlist = "UUSH" + suffix

    print(f"Channel ID       : {channel_id}")
    print(f"Uploads playlist : {uploads_playlist}")
    all_ids = _get_playlist_video_ids(uploads_playlist, api_key, since)
    print(f"  {since_date} 之後共 {len(all_ids)} 支影片")

    print(f"Shorts playlist  : {shorts_playlist}")
    shorts_ids = _get_playlist_video_ids(shorts_playlist, api_key, since)
    print(f"  {since_date} 之後共 {len(shorts_ids)} 支 Shorts")

    regular = [v for v in all_ids if v not in shorts_ids]
    shorts = [v for v in all_ids if v in shorts_ids]
    return regular, shorts
