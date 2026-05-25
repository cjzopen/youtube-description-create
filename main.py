import asyncio
import json
import os
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from notebooklm import NotebookLMClient

load_dotenv()


def analyze_file(file_path: str, progress_cb=None) -> tuple[str, str]:
    """上傳本地影片檔，透過 Gemini Files API 分析，回傳 (內容摘要, gemini_file_name)。"""
    def p(step):
        if progress_cb:
            progress_cb(step)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    p("gemini_upload")
    video_file = client.files.upload(
        file=file_path,
        config=types.UploadFileConfig(mime_type="video/mp4"),
    )

    p("gemini_processing")
    while video_file.state.name == "PROCESSING":
        time.sleep(3)
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise RuntimeError("Gemini 影片處理失敗")

    p("gemini_analyze")
    response = client.models.generate_content(
        model=os.environ["GEMINI_MODEL"],
        contents=[
            video_file,
            "請詳細摘要這支影片的主要內容、重點論述與核心結論。",
        ],
    )
    return response.text.strip(), video_file.name


async def analyze_youtube(youtube_url: str) -> str:
    """輸入 YouTube 網址，透過 NotebookLM 分析並回傳內容摘要。"""
    async with await NotebookLMClient.from_storage() as client:
        print("[1/5] 建立 Notebook...")
        nb = await client.notebooks.create("youtube-analysis")

        print(f"[2/5] 匯入 YouTube 來源：{youtube_url}")
        await client.sources.add_url(nb.id, youtube_url, wait=True)
        print("      來源索引完成")

        print("[3/5] 請 NotebookLM 分析內容...")
        result = await client.chat.ask(
            nb.id,
            "請詳細摘要這支影片的主要內容、重點論述與核心結論。",
        )
        content = re.sub(r"\[\d+(?:[,\-]\s*\d+)*\]", "", result.answer).strip()
        print(f"      取得分析內容（{len(content)} 字）")

        await client.notebooks.delete(nb.id)
        return content


def generate_metadata(content: str, is_shorts: bool = False) -> dict:
    """將 NotebookLM 分析內容透過 Gemini API 整理成 title 與 description。"""
    print("[4/5] 呼叫 Gemini API 整理 metadata...")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    shorts_instruction = "（這是一支 Shorts 短影片，結尾一定要加上 #shorts）" if is_shorts else "（若是shorts一定要加上 #shorts）"

    prompt = f"""你是B2B企業YouTube頻道的內容編輯，負責為產品介紹、解決方案、客戶案例、研討會或教學類型的影片撰寫metadata。

請根據以下影片摘要，產生title與description。

【Title規則】
- 具體點出影片的主題、產品或解決的問題
- 讓目標觀眾（企業決策者或技術評估者）一眼看懂影片在講什麼
- 50 字以內

【Description規則】
- 開門見山，直接說明影片情境、講什麼、用什麼方法解決什麼問題
- 具體描述影片中的背景、做法、方法論，並寫下結論與實質資訊，不看影片也能掌握實質內容
- 結尾加上合適的hashtag，不限數量，但要與內容相關{shorts_instruction}
- 禁止使用以下類型的空洞語句：
  「本影片」「精彩內容」「乾貨滿滿」「一起來了解」「不容錯過」「讓我們看看」「歡迎收看」或僅描述議程流程而不提供實質資訊

請以JSON格式回傳，只輸出JSON，不要有任何其他文字：
{{
  "title": "...",
  "description": "..."
}}

影片摘要：
{content}"""

    response = client.models.generate_content(
        model=os.environ["GEMINI_MODEL"],
        contents=prompt,
    )
    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    result = json.loads(raw)

    if is_shorts and "description" in result:
        desc = result["description"]
        if "#shorts" not in desc.lower():
            result["description"] = desc.rstrip() + " #shorts"

    return result


async def main():
    url = input("請輸入 YouTube 網址：").strip()
    if not url:
        print("未輸入網址，結束。")
        return

    content = await analyze_youtube(url)
    metadata = generate_metadata(content, is_shorts=("/shorts/" in url))

    output = {"url": url, **metadata}

    print("[5/5] 寫入 output.json...")
    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n===== 結果 =====")
    print(f"Title      : {output['title']}")
    print(f"Description:\n{output['description']}")
    print(f"\n輸出檔案   : output.json")


if __name__ == "__main__":
    asyncio.run(main())
