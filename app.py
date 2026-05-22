import base64
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv
from google import genai
from google.genai import types
from main import analyze_file, generate_metadata

load_dotenv()

app = Flask(__name__, static_folder=".", static_url_path="")
_TMP = Path(tempfile.gettempdir())
_SIZE_THRESHOLD = 500 * 1024 * 1024  # 500 MB
_jobs: dict[str, dict] = {}


def _extract_chapters(gemini_file_name: str, model: str, api_key: str) -> str:
    client = genai.Client(api_key=api_key)
    video_file = client.files.get(name=gemini_file_name)
    response = client.models.generate_content(
        model=model,
        contents=[
            video_file,
            (
                "請列出這支影片的主要章節與對應時間點。\n"
                "規則：\n"
                "- 章節標題需明確描述該段內容，2–16 個字（英文單字算 1 個字）\n"
                "- 若該章節與解決問題相關（痛點、挑戰、解法、Why），標題改用問句（以「？」結尾）\n"
                "- 時間格式：影片未滿 1 小時用 MM:SS，滿 1 小時（含）用 HH:MM:SS\n"
                "- 只輸出時間戳清單，不要其他文字\n"
                "格式範例：\n"
                "00:00 章節標題\n"
                "01:23 章節標題\n"
                "1:05:30 章節標題"
            ),
        ],
    )
    return response.text.strip()


def _run_analyze(job_id: str, file_path: str):
    def progress(step):
        _jobs[job_id]["step"] = step

    api_key = os.environ["GEMINI_API_KEY"]
    model = os.environ["GEMINI_MODEL"]
    gemini_file_name = None

    try:
        content, gemini_file_name = analyze_file(file_path, progress_cb=progress)

        progress("gemini_chapters")
        chapters = _extract_chapters(gemini_file_name, model, api_key)

        progress("gemini_metadata")
        metadata = generate_metadata(content)

        if chapters:
            metadata["description"] += f"\n\n{chapters}"

        _jobs[job_id].update(
            {
                "status": "done",
                "step": "done",
                "title": metadata["title"],
                "description": metadata["description"],
            }
        )
    except Exception as e:
        _jobs[job_id].update({"status": "error", "step": "error", "error": str(e)})
    finally:
        if gemini_file_name:
            try:
                genai.Client(api_key=api_key).files.delete(name=gemini_file_name)
            except Exception:
                pass


@app.route("/")
def index():
    return send_file("upload.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("video")
    if not file:
        return jsonify({"error": "未收到檔案"}), 400

    job_id = str(uuid.uuid4())
    file_path = _TMP / f"{job_id}.mp4"

    content_length = request.content_length or 0
    if 0 < content_length <= _SIZE_THRESHOLD:
        # ≤ 500 MB：整份讀入記憶體後一次寫入
        file_path.write_bytes(file.read())
    else:
        # > 500 MB 或大小未知：分塊串流寫入磁碟，避免記憶體溢出
        file.save(str(file_path))

    _jobs[job_id] = {"status": "running", "step": "uploading", "file_path": str(file_path)}
    threading.Thread(target=_run_analyze, args=(job_id, str(file_path)), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "找不到工作"}), 404
    result = {"status": job["status"], "step": job["step"]}
    if job["status"] == "done":
        result["title"] = job["title"]
        result["description"] = job["description"]
    elif job["status"] == "error":
        result["error"] = job["error"]
    return jsonify(result)


@app.route("/api/subtitle", methods=["POST"])
def subtitle():
    data = request.get_json(silent=True) or {}
    job = _jobs.get(data.get("job_id"))
    if not job:
        return jsonify({"error": "找不到對應的分析工作"}), 404

    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

        video_file = client.files.upload(
            file=job["file_path"],
            config=types.UploadFileConfig(mime_type="video/mp4"),
        )
        while video_file.state.name == "PROCESSING":
            time.sleep(3)
            video_file = client.files.get(name=video_file.name)

        if video_file.state.name == "FAILED":
            return jsonify({"error": "Gemini 檔案處理失敗"}), 500

        response = client.models.generate_content(
            model=os.environ["GEMINI_MODEL"],
            contents=[
                video_file,
                "請為這段影片生成完整字幕，輸出標準 SRT 格式，只輸出 SRT 內容，不要其他文字。",
            ],
        )
        client.files.delete(name=video_file.name)

        srt_path = _TMP / f"{data['job_id']}.srt"
        srt_path.write_text(response.text.strip(), encoding="utf-8")

        return send_file(
            str(srt_path),
            mimetype="text/plain",
            as_attachment=True,
            download_name="subtitle.srt",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/thumbnail", methods=["POST"])
def thumbnail():
    data = request.get_json(silent=True) or {}
    job = _jobs.get(data.get("job_id"))
    if not job:
        return jsonify({"error": "找不到對應的分析工作"}), 404

    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        prompt = (
            f"Professional B2B enterprise YouTube thumbnail, 1280x720 pixels. "
            f"Video title: {job['title']}. "
            f"Clean modern corporate design, blue and white color scheme, "
            f"bold typography, tech/software company aesthetic, "
            f"abstract geometric background, no human faces."
        )
        response = client.models.generate_images(
            model="imagen-3.0-generate-001",
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="16:9"),
        )
        img_b64 = base64.b64encode(response.generated_images[0].image.image_bytes).decode()
        return jsonify({"image": f"data:image/png;base64,{img_b64}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import webbrowser
    webbrowser.open("http://localhost:5000")
    app.run(port=5000, debug=False)
