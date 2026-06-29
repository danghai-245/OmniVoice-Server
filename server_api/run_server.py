import os
import sys
import time
import subprocess
import shutil
import tempfile
import torch

# Tự động cài đặt các thư viện và dự án nếu thiếu hoặc lỗi phiên bản trên môi trường Cloud
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import fastapi
    import gradio
    import soundfile
    from transformers import HiggsAudioV2TokenizerModel
except ImportError:
    print("[*] Phát hiện thiếu hoặc lỗi phiên bản thư viện transformers tương thích trên Cloud.")
    print("[*] Đang tiến hành dọn dẹp và cài đặt sạch lại dự án cùng các dependencies (quá trình mất khoảng 1 phút)...")
    
    # Gỡ cài đặt triệt để các phiên bản cũ bị xung đột
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "transformers", "huggingface-hub"], stdout=subprocess.DEVNULL)
    
    # Cài đặt lại dự án dạng editable không dùng cache để kéo bản mới nhất
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--no-cache-dir", "-e", project_root
    ])
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "gradio", "soundfile"
    ])
    
    print("\n" + "="*80)
    print("[SUCCESS] Đã cài đặt sạch sẽ dự án và các thư viện tương thích thành công!")
    print("[INFO] Hệ thống sẽ tự động khởi động lại tiến trình Python (Kernel) sau 3 giây.")
    print("ANH VUI LÒNG BẤM CHẠY LẠI Ô MÃ LỆNH (CELL) NÀY SAU KHI TIẾN TRÌNH KHỞI ĐỘNG LẠI XONG!")
    print("="*80 + "\n")
    time.sleep(3)
    os._exit(0)

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

# Hậu xử lý âm thanh kỹ thuật số (DSP)
import numpy as np
from scipy.signal import butter, lfilter

def butter_lowpass_filter(data, cutoff, fs, order=5):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    y = lfilter(b, a, data)
    return y

def bass_boost(data, fs, gain=1.35, cutoff=220.0):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(2, normal_cutoff, btype='low')
    bass = lfilter(b, a, data)
    treble = data - bass
    return bass * gain + treble

def dynamic_range_compression(data, threshold=0.15, ratio=3.0, makeup_gain=1.15):
    abs_data = np.abs(data)
    mask = abs_data > threshold
    compressed = np.copy(data)
    compressed[mask] = np.sign(data[mask]) * (threshold + (abs_data[mask] - threshold) / ratio)
    compressed = compressed * makeup_gain
    return np.clip(compressed, -1.0, 1.0)

def postprocess_audio_dsp(audio_np, sr):
    try:
        # 1. Bass boost dải trầm
        audio_np = bass_boost(audio_np, sr, gain=1.35, cutoff=220.0)
        # 2. Lọc thông thấp cắt rè treble trên 8500Hz
        audio_np = butter_lowpass_filter(audio_np, cutoff=8500.0, fs=sr, order=3)
        # 3. Nén dải động giúp giọng đọc ấm, chắc chắn hơn
        audio_np = dynamic_range_compression(audio_np, threshold=0.15, ratio=3.0, makeup_gain=1.15)
        return audio_np
    except Exception as e:
        print(f"[!] Lỗi khi chạy hậu xử lý DSP: {e}")
        return audio_np

def generate_voice_gradio(text, language, ref_audio_path, ref_text, instruct, speed, num_step, cfg_scale=2.0, temperature=5.0):
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
        print(f"[*] Đang sinh âm thanh (CFG={cfg_scale}, Temp={temperature}) cho văn bản: {text[:100]}...")
        audio_data = loaded_model.generate(
            text=text,
            language=lang_val,
            ref_audio=ref_audio_path,
            ref_text=ref_text,
            instruct=instruct_val,
            speed=float(speed),
            num_step=int(num_step),
            guidance_scale=float(cfg_scale),
            position_temperature=float(temperature),
            progress_callback=None
        )

        # Hậu xử lý âm thanh chống robot, lọc rè, làm dày giọng đọc
        processed_audio = postprocess_audio_dsp(audio_data[0], loaded_model.sampling_rate)

        # Ghi âm thanh ra file tạm wav
        sf.write(out_path, processed_audio, loaded_model.sampling_rate)
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
        cfg_input = gr.Number(label="CFG Scale", value=2.0)
        temp_input = gr.Number(label="Temperature", value=5.0)
        
        audio_output = gr.Audio(label="Output Audio", type="filepath")
        
        btn = gr.Button("Generate")
        btn.click(
            fn=generate_voice_gradio,
            inputs=[txt_input, lang_input, ref_audio_input, ref_text_input, instruct_input, speed_input, steps_input, cfg_input, temp_input],
            outputs=audio_output,
            api_name="generate"
        )

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ngrok_token", type=str, default=os.environ.get("NGROK_TOKEN"))
    parser.add_argument("--ngrok_domain", type=str, default=os.environ.get("NGROK_DOMAIN"))
    args = parser.parse_args()
    
    # Khởi chạy ngrok nếu có token
    if args.ngrok_token:
        try:
            from pyngrok import ngrok
        except ImportError:
            print("[*] Đang tự động cài đặt thư viện pyngrok...")
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "pyngrok"], stdout=subprocess.DEVNULL)
            from pyngrok import ngrok
        
        try:
            print("[*] Đang khởi tạo ngrok tunnel...")
            ngrok.set_auth_token(args.ngrok_token)
            
            # Đóng các tunnel cũ để tránh lỗi số lượng tunnel tối đa của ngrok
            tunnels = ngrok.get_tunnels()
            for t in tunnels:
                ngrok.disconnect(t.public_url)
                
            if args.ngrok_domain:
                tunnel = ngrok.connect(args.port, "http", domain=args.ngrok_domain)
            else:
                tunnel = ngrok.connect(args.port, "http")
                
            print("\n" + "="*80)
            print(f"[SUCCESS] Ngrok Tunnel đã được thiết lập thành công!")
            print(f"Địa chỉ ngrok cố định (Gradio): {tunnel.public_url}")
            print("="*80 + "\n")
        except Exception as e:
            print(f"[!] Lỗi khởi chạy ngrok: {e}")
            
    print("[*] Đang khởi chạy máy chủ Gradio...")
    # Khởi chạy Gradio với share=True để tạo link public miễn phí (nếu không dùng ngrok)
    demo.launch(
        share=False if args.ngrok_token else True, 
        server_name="0.0.0.0", 
        server_port=args.port
    )
