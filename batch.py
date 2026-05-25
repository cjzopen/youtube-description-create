import asyncio
import http.server
import json
import os
import socket
import socketserver
import webbrowser
from pathlib import Path
from dotenv import load_dotenv
from main import analyze_youtube, generate_metadata
from youtube import fetch_channel_videos, get_video_metadata

load_dotenv()

RESULTS_FILE = "results.json"
HTML_FILE = "results.html"


def _open_html():
  with socket.socket() as s:
    s.bind(("", 0))
    port = s.getsockname()[1]
  handler = http.server.SimpleHTTPRequestHandler
  handler.log_message = lambda *_: None
  with socketserver.TCPServer(("", port), handler) as httpd:
    webbrowser.open(f"http://localhost:{port}/{HTML_FILE}")
    print(f"已開啟 http://localhost:{port}/{HTML_FILE}　（Ctrl+C 結束）")
    httpd.serve_forever()


def _load_results() -> list:
  if Path(RESULTS_FILE).exists():
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
      return json.load(f)
  return []


def _save_results(results: list):
  with open(RESULTS_FILE, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)


async def _process_video(video_id: str, video_type: str, meta: dict, results: list, index: int, total: int):
  url = f"https://www.youtube.com/watch?v={video_id}"
  processed = {r["url"] for r in results}
  if url in processed:
    print(f"[{index}/{total}] 略過（已處理）：{video_id}")
    return

  print(f"\n[{index}/{total}] [{video_type}] {url}")
  try:
    content = await analyze_youtube(url)
    metadata = generate_metadata(content, is_shorts=(video_type == "shorts"))
    results.append({"type": video_type, "url": url, **meta, **metadata})
    print(f"  title: {metadata['title']}")
  except Exception as e:
    results.append({"type": video_type, "url": url, **meta, "status": "failed", "error": str(e)})
    print(f"  失敗：{e}")
  finally:
    _save_results(results)


async def main():
  channel = os.environ["channel"]
  api_key = os.environ["YOUTUBE_API_KEY"]
  since_date = os.environ.get("SINCE", "2025-01-01")

  print(f"頻道：{channel}　抓取 {since_date} 之後的影片\n")
  regular_ids, shorts_ids = fetch_channel_videos(channel, api_key, since_date)
  total = len(regular_ids) + len(shorts_ids)
  print(f"\n一般影片 {len(regular_ids)} 支 / Shorts {len(shorts_ids)} 支　合計 {total} 支")

  print("抓取影片 metadata...")
  video_meta = get_video_metadata(regular_ids + shorts_ids, api_key)
  print(f"取得 {len(video_meta)} 筆 metadata\n")

  results = _load_results()
  index = 1

  for vid in regular_ids:
    await _process_video(vid, "regular", video_meta.get(vid, {}), results, index, total)
    index += 1

  for vid in shorts_ids:
    await _process_video(vid, "shorts", video_meta.get(vid, {}), results, index, total)
    index += 1

  print(f"\n完成！共處理 {len(results)} 筆，輸出：{RESULTS_FILE}")
  _open_html()


if __name__ == "__main__":
  asyncio.run(main())
