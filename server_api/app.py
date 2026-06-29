import os
import time
import tempfile
import shutil
import torch
import soundfile as sf
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from typing import Optional

# Thêm thư mục gốc dự án vào sys.path để import đúng module omnivoice
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from omnivoice.models.omnivoice import OmniVoice

app = FastAPI(
    title="OmniVoice Cloud API Server", 
    description="API Server hỗ trợ sinh giọng nói OmniVoice từ xa trên Cloud GPU (Colab/Kaggle)",
    version="1.0.0"
)

# Hằng số models
MODEL_OMNIVOICE = "k2-fsa/OmniVoice"
MODEL_ASR = "openai/whisper-large-v3-turbo"

# Nạp model toàn cục
loaded_model = None

def remove_temp_file(path: str):
    """Xóa tệp tạm thời sau khi phản hồi hoàn tất"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
            print(f"[*] Đã xóa tệp tạm: {path}")
        except Exception as e:
            print(f"[!] Lỗi khi xóa tệp tạm {path}: {e}")

@app.on_event("startup")
def load_model():
    global loaded_model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[*] Đang khởi tạo mô hình OmniVoice trên thiết bị: {device.upper()}...")
    try:
        loaded_model = OmniVoice.from_pretrained(
            MODEL_OMNIVOICE,
            device_map=device,
            dtype=torch.float16 if device == "cuda" else torch.float32,
            load_asr=True,
            asr_model_name=MODEL_ASR
        )
        print(f"[*] Nạp mô hình thành công! Thiết bị hiện tại: {device.upper()}")
    except Exception as e:
        print(f"[!] Lỗi nghiêm trọng khi nạp mô hình: {e}")

    # Khởi chạy ngrok nếu cấu hình qua biến môi trường
    ngrok_token = os.environ.get("NGROK_TOKEN")
    ngrok_domain = os.environ.get("NGROK_DOMAIN")
    port = int(os.environ.get("PORT", "8000"))

    if ngrok_token:
        try:
            from pyngrok import ngrok
        except ImportError:
            print("[*] Đang tự động cài đặt thư viện pyngrok...")
            import subprocess
            import sys
            subprocess.run([sys.executable, "-m", "pip", "install", "pyngrok"], stdout=subprocess.DEVNULL)
            from pyngrok import ngrok

        try:
            tunnels = ngrok.get_tunnels()
            if not tunnels:
                print("[*] Đang khởi tạo ngrok tunnel qua biến môi trường...")
                ngrok.set_auth_token(ngrok_token)
                if ngrok_domain:
                    tunnel = ngrok.connect(port, "http", domain=ngrok_domain)
                else:
                    tunnel = ngrok.connect(port, "http")
                print("\n" + "="*80)
                print(f"[SUCCESS] Ngrok Tunnel đã được thiết lập thành công!")
                print(f"Địa chỉ ngrok cố định (API): {tunnel.public_url}")
                print("="*80 + "\n")
        except Exception as e:
            print(f"[!] Lỗi khởi chạy ngrok trong sự kiện startup: {e}")


@app.get("/")
def read_root():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return {
        "status": "online",
        "device": device,
        "model_loaded": loaded_model is not None,
        "omnivoice_version": "0.1.5"
    }

@app.post("/api/generate")
async def api_generate(
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    language: Optional[str] = Form(None),
    speed: float = Form(1.0),
    num_step: int = Form(32),
    instruct: Optional[str] = Form(None),
    ref_text: Optional[str] = Form(None),
    ref_audio: Optional[UploadFile] = File(None)
):
    global loaded_model
    if loaded_model is None:
        raise HTTPException(status_code=503, detail="Mô hình chưa được nạp trên Server.")

    # Tạo tệp tạm lưu ref_audio gửi lên
    temp_ref_audio_path = None
    if ref_audio is not None and ref_audio.filename:
        suffix = os.path.splitext(ref_audio.filename)[1] or ".wav"
        fd, temp_ref_audio_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            with open(temp_ref_audio_path, "wb") as buffer:
                content = await ref_audio.read()
                buffer.write(content)
            print(f"[*] Đã nhận file ref_audio tạm: {temp_ref_audio_path}")
            # Lên lịch xóa file ref_audio tạm sau khi xử lý xong
            background_tasks.add_task(remove_temp_file, temp_ref_audio_path)
        except Exception as e:
            if temp_ref_audio_path and os.path.exists(temp_ref_audio_path):
                os.remove(temp_ref_audio_path)
            raise HTTPException(status_code=500, detail=f"Lỗi lưu file ref_audio gửi lên: {e}")

    # Chuẩn hóa ref_text rỗng thành None
    if ref_text is not None and not ref_text.strip():
        ref_text = None

    # Tạo tệp đầu ra tạm thời
    fd_out, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd_out)
    background_tasks.add_task(remove_temp_file, out_path)

    try:
        # Nếu có ref_audio nhưng chưa có ref_text, tự động chạy Whisper ASR
        if temp_ref_audio_path and not ref_text:
            print(f"[*] Đang nhận dạng giọng mẫu (ASR)...")
            if loaded_model._asr_pipe is None:
                loaded_model.load_asr_model(model_name=MODEL_ASR)
            ref_text = loaded_model.transcribe(temp_ref_audio_path)
            print(f"[*] Kết quả ASR: \"{ref_text}\"")

        # Chuẩn hóa ngôn ngữ và instruct
        lang_val = language if language != "Auto" and language else None
        instruct_val = instruct if instruct != "Auto" and instruct else None

        # Sinh âm thanh bằng model
        print(f"[*] Đang sinh âm thanh cho văn bản: {text[:100]}...")
        audio_data = loaded_model.generate(
            text=text,
            language=lang_val,
            ref_audio=temp_ref_audio_path,
            ref_text=ref_text,
            instruct=instruct_val,
            speed=speed,
            num_step=num_step,
            progress_callback=None
        )

        # Ghi âm thanh ra file tạm wav
        sf.write(out_path, audio_data[0], loaded_model.sampling_rate)
        print(f"[*] Đã sinh xong file âm thanh thành công.")

        return FileResponse(
            out_path, 
            media_type="audio/wav", 
            filename=f"generated_{int(time.time())}.wav"
        )

    except Exception as e:
        print(f"[!] Lỗi trong quá trình sinh âm thanh: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import argparse
    import uvicorn
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ngrok_token", type=str, default=os.environ.get("NGROK_TOKEN"))
    parser.add_argument("--ngrok_domain", type=str, default=os.environ.get("NGROK_DOMAIN"))
    args = parser.parse_args()

    # Cấu hình biến môi trường từ tham số dòng lệnh
    if args.ngrok_token:
        os.environ["NGROK_TOKEN"] = args.ngrok_token
    if args.ngrok_domain:
        os.environ["NGROK_DOMAIN"] = args.ngrok_domain
    os.environ["PORT"] = str(args.port)

    # Chạy uvicorn trực tiếp
    print(f"[*] Đang khởi chạy máy chủ FastAPI trên {args.host}:{args.port}...")
    uvicorn.run("app:app", host=args.host, port=args.port)

