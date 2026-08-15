import modal

# Container thuần 100% OmniVoice Zero-Shot Voice Cloning
image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("espeak-ng", "ffmpeg", "git")
    .pip_install(
        "torch", "torchaudio", "transformers", "accelerate", "soundfile",
        "fastapi", "requests", "librosa", "scipy", "einops", "timm",
        "huggingface_hub", "pydub"
    )
    .pip_install("git+https://github.com/k2-fsa/OmniVoice.git")
)

app = modal.App("omnivoice-tts-serverless", image=image)

@app.cls(gpu="T4", timeout=600, scaledown_window=600)
class OmniVoiceModel:
    @modal.enter()
    def load_model(self):
        import torch
        from omnivoice.models.omnivoice import OmniVoice
        print("[*] Nạp mô hình OmniVoice Zero-Shot Voice Cloning vào GPU T4...")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        try:
            # load_asr=False để nạp cực nhanh, nhẹ VRAM và không bị lỗi Whisper ASR
            self.model = OmniVoice.from_pretrained(
                "k2-fsa/OmniVoice",
                device_map=self.device,
                dtype=dtype,
                load_asr=False
            )
            print("[*] Nạp mô hình OmniVoice 100% thành công!")
        except Exception as e:
            print(f"[!] Lỗi nạp mô hình OmniVoice: {e}")
            self.model = None

    @modal.fastapi_endpoint(method="POST")
    def generate(self, data: dict = None):
        import tempfile, soundfile as sf, base64, requests, os, torch
        from fastapi.responses import FileResponse, JSONResponse

        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400"
        }

        if not data or not isinstance(data, dict):
            data = {}

        try:
            text = data.get("text", "")
            speed = float(data.get("speed", 1.0))
            ref_text = data.get("ref_text", "")
            
            if not text or not str(text).strip():
                text = "Xin chào"

            # Lấy tệp giọng đọc mẫu (Base64 hoặc URL)
            ref_audio_b64 = data.get("ref_audio_base64") or data.get("ref_audio") or data.get("prompt_speech") or ""
            ref_audio_url = data.get("ref_audio_url") or data.get("audio_prompt") or ""
            
            temp_ref_path = None
            
            # 1. Giải mã Base64 tệp âm thanh mẫu
            if ref_audio_b64 and isinstance(ref_audio_b64, str) and ("base64," in ref_audio_b64 or len(ref_audio_b64) > 200):
                try:
                    b64_clean = ref_audio_b64.split("base64,")[-1]
                    audio_bytes = base64.b64decode(b64_clean)
                    
                    suffix = ".wav"
                    if audio_bytes.startswith(b"ID3") or audio_bytes[:2] in [b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"]:
                        suffix = ".mp3"
                    elif audio_bytes.startswith(b"OggS"):
                        suffix = ".ogg"
                    elif audio_bytes.startswith(b"RIFF"):
                        suffix = ".wav"

                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f_ref:
                        f_ref.write(audio_bytes)
                        temp_ref_path = f_ref.name
                    print(f"[*] Đã giải mã tệp mẫu Base64 ({suffix}): {temp_ref_path}")
                except Exception as e:
                    print(f"[!] Lỗi giải mã Base64: {e}")

            # 2. Tải tệp âm thanh từ URL nếu chưa có Base64 hợp lệ
            if not temp_ref_path and ref_audio_url and isinstance(ref_audio_url, str) and ref_audio_url.startswith("http"):
                try:
                    req_headers = {"User-Agent": "Mozilla/5.0"}
                    resp = requests.get(ref_audio_url, headers=req_headers, timeout=10)
                    if resp.status_code == 200:
                        audio_bytes = resp.content
                        suffix = ".wav"
                        if audio_bytes.startswith(b"ID3") or audio_bytes[:2] in [b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"]:
                            suffix = ".mp3"
                        elif audio_bytes.startswith(b"RIFF"):
                            suffix = ".wav"
                            
                        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f_ref:
                            f_ref.write(audio_bytes)
                            temp_ref_path = f_ref.name
                        print(f"[*] Đã tải tệp mẫu từ URL ({suffix}): {temp_ref_path}")
                except Exception as e:
                    print(f"[!] Lỗi tải tệp từ URL: {e}")

            if self.model is None:
                return JSONResponse(status_code=500, content={"error": "OmniVoice model chưa được khởi tạo thành công"}, headers=headers)

            try:
                gen_kwargs = {
                    "text": text,
                    "speed": speed
                }
                if temp_ref_path and os.path.exists(temp_ref_path):
                    gen_kwargs["ref_audio"] = temp_ref_path
                    if ref_text and str(ref_text).strip():
                        gen_kwargs["ref_text"] = str(ref_text).strip()

                print(f"[*] [OmniVoice] Đang sinh âm thanh nhái giọng...")
                audio_res = self.model.generate(**gen_kwargs)
                
                if isinstance(audio_res, (tuple, list)):
                    audio_data = audio_res[0]
                else:
                    audio_data = audio_res

            except Exception as e_gen:
                print(f"[!] Lỗi khi sinh âm thanh bằng OmniVoice: {e_gen}")
                return JSONResponse(status_code=500, content={"error": f"Lỗi sinh âm thanh OmniVoice: {str(e_gen)}"}, headers=headers)
            finally:
                if temp_ref_path and os.path.exists(temp_ref_path):
                    try:
                        os.remove(temp_ref_path)
                    except Exception:
                        pass

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                out_path = f.name

            sr = getattr(self.model, "sampling_rate", 24000)
            if hasattr(audio_data, "cpu"):
                audio_data = audio_data.cpu().numpy()
            sf.write(out_path, audio_data, sr)

            return FileResponse(out_path, media_type="audio/wav", headers=headers)

        except Exception as err:
            print(f"[!] Lỗi nghiêm trọng: {err}")
            return JSONResponse(status_code=500, content={"error": str(err)}, headers=headers)
