import asyncio
import base64
import os
import tempfile
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
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

_TMP = Path(tempfile.gettempdir())
_jobs: dict[str, dict] = {}


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
    file.save(str(file_path))

    try:
        content = asyncio.run(analyze_file(str(file_path)))
        metadata = generate_metadata(content)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    _jobs[job_id] = {
        "file_path": str(file_path),
        "title": metadata["title"],
        "description": metadata["description"],
    }
    return jsonify({"job_id": job_id, **metadata})


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
