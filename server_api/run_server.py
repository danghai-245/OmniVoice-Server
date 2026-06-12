import os
import sys
import time
import subprocess
import shutil
import tempfile
import torch

# Tự động cài đặt các thư viện và dự án nếu thiếu trên môi trường Cloud
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import fastapi
    import gradio
    import soundfile
    from transformers import HiggsAudioV2TokenizerModel
except ImportError:
    print("[*] Đang tiến hành cài đặt dự án và các thư viện phụ thuộc (dependencies) trên Cloud...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-e", project_root
    ])
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "gradio", "soundfile"
    ])

# Thêm thư mục gốc dự án vào sys.path để import đúng module omnivoice
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import gradio as gr
import soundfile as sf
from omnivoice.models.omnivoice import OmniVoice

# Hằng số models
MODEL_OMNIVOICE = "k2-fsa/OmniVoice"
MODEL_ASR = "openai/whisper-large-v3-turbo"

# Nạp model toàn cục
loaded_model = None

def load_model_global():
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

# Nạp model ngay khi khởi động
load_model_global()

def generate_voice_gradio(text, language, ref_audio_path, ref_text, instruct, speed, num_step):
    global loaded_model
    if loaded_model is None:
        raise gr.Error("Mô hình chưa được nạp trên Server.")

    # Chuẩn hóa ref_text rỗng thành None
    if ref_text is not None and not str(ref_text).strip():
        ref_text = None

    # Tạo tệp đầu ra tạm thời
    fd_out, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd_out)

    try:
        # Nếu có ref_audio nhưng chưa có ref_text, tự động chạy Whisper ASR
        if ref_audio_path and not ref_text:
            print(f"[*] Đang nhận dạng giọng mẫu (ASR)...")
            if loaded_model._asr_pipe is None:
                loaded_model.load_asr_model(model_name=MODEL_ASR)
            ref_text = loaded_model.transcribe(ref_audio_path)
            print(f"[*] Kết quả ASR: \"{ref_text}\"")

        # Chuẩn hóa ngôn ngữ và instruct
        lang_val = language if language != "Auto" and language else None
        instruct_val = instruct if instruct != "Auto" and instruct else None

        # Sinh âm thanh bằng model
        print(f"[*] Đang sinh âm thanh cho văn bản: {text[:100]}...")
        audio_data = loaded_model.generate(
            text=text,
            language=lang_val,
            ref_audio=ref_audio_path,
            ref_text=ref_text,
            instruct=instruct_val,
            speed=float(speed),
            num_step=int(num_step),
            progress_callback=None
        )

        # Ghi âm thanh ra file tạm wav
        sf.write(out_path, audio_data[0], loaded_model.sampling_rate)
        print(f"[*] Đã sinh xong file âm thanh thành công: {out_path}")
        return out_path

    except Exception as e:
        print(f"[!] Lỗi trong quá trình sinh âm thanh: {e}")
        if os.path.exists(out_path):
            os.remove(out_path)
        raise gr.Error(f"Lỗi: {e}")

# Dựng giao diện Gradio
with gr.Blocks(title="OmniVoice Cloud API Server") as demo:
    gr.Markdown("""
    # 🎙️ OmniVoice Cloud API Server is Running!
    
    ### Hướng dẫn kết nối:
    1. Copy đường dẫn **Public URL** hiển thị bên dưới (dạng `https://xxxx.gradio.live`).
    2. Mở ứng dụng **OmniVoiceStudio** trên máy tính của bạn.
    3. Chuyển sang tab **Cài đặt & Tải Model**.
    4. Chọn chế độ chạy là **Cloud API**.
    5. Dán đường dẫn vừa copy vào ô **Địa chỉ Cloud API Server** và bấm **Lưu cấu hình**.
    
    *Lưu ý: Vui lòng giữ tab Colab/Kaggle này hoạt động liên tục trong suốt quá trình sử dụng.*
    """)
    
    # Định nghĩa endpoint API ẩn cho Gradio Client sử dụng
    with gr.Row(visible=False):
        txt_input = gr.Textbox(label="Text")
        lang_input = gr.Textbox(label="Language")
        ref_audio_input = gr.Audio(label="Ref Audio", type="filepath")
        ref_text_input = gr.Textbox(label="Ref Text")
        instruct_input = gr.Textbox(label="Instruct")
        speed_input = gr.Number(label="Speed", value=1.0)
        steps_input = gr.Number(label="Steps", value=32)
        
        audio_output = gr.Audio(label="Output Audio", type="filepath")
        
        btn = gr.Button("Generate")
        btn.click(
            fn=generate_voice_gradio,
            inputs=[txt_input, lang_input, ref_audio_input, ref_text_input, instruct_input, speed_input, steps_input],
            outputs=audio_output,
            api_name="generate"
        )

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    
    print("[*] Đang khởi chạy máy chủ Gradio Tunnel...")
    # Khởi chạy Gradio với share=True để tạo link public miễn phí
    demo.launch(
        share=True, 
        server_name="0.0.0.0", 
        server_port=args.port
    )
