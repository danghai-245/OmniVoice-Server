#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time
import threading
import logging
import subprocess
import json
import re
import requests

# =====================================================================
# 1. Cấu hình biến môi trường Cache lưu hoàn toàn ở ổ E (thư mục dự án)
# =====================================================================
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if getattr(sys, 'frozen', False):
    # Chạy từ file exe đóng gói
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    # Nếu exe nằm trong dist/OmniVoiceStudio, quay lại thư mục gốc dự án
    parent_dir = os.path.dirname(exe_dir)
    grandparent_dir = os.path.dirname(parent_dir)
    if os.path.basename(parent_dir).lower() == "dist":
        current_dir = grandparent_dir
    else:
        current_dir = exe_dir
else:
    # Chạy từ mã nguồn python bình thường
    current_dir = os.path.dirname(os.path.abspath(__file__))

cache_dir = os.path.join(current_dir, "cache")

os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["HF_HOME"] = os.path.join(cache_dir, "huggingface")
os.environ["TORCH_HOME"] = os.path.join(cache_dir, "torch")
os.environ["UV_CACHE_DIR"] = os.path.join(cache_dir, "uv")
os.environ["TEMP"] = os.path.join(cache_dir, "temp")
os.environ["TMP"] = os.path.join(cache_dir, "temp")
os.environ["CUDA_CACHE_PATH"] = os.path.join(cache_dir, "cuda")


# Tạo các thư mục cache nếu chưa có
os.makedirs(os.path.join(cache_dir, "huggingface"), exist_ok=True)
os.makedirs(os.path.join(cache_dir, "torch"), exist_ok=True)
os.makedirs(os.path.join(cache_dir, "uv"), exist_ok=True)
os.makedirs(os.path.join(cache_dir, "temp"), exist_ok=True)
os.makedirs(os.path.join(cache_dir, "cuda"), exist_ok=True)

# Thư mục chứa file âm thanh đầu ra
output_dir = os.path.join(current_dir, "outputs")
os.makedirs(output_dir, exist_ok=True)

# Thư mục lưu trữ giọng đọc đã clone
saved_voices_dir = os.path.join(current_dir, "saved_voices")
os.makedirs(saved_voices_dir, exist_ok=True)

def get_asset_path(filename):
    """Tìm đường dẫn tài nguyên (Logo, Icon...) hỗ trợ đóng gói PyInstaller trên mọi máy tính"""
    possible_paths = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            possible_paths.append(os.path.join(sys._MEIPASS, filename))
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        possible_paths.append(os.path.join(exe_dir, "_internal", filename))
        possible_paths.append(os.path.join(exe_dir, filename))
    
    possible_paths.append(os.path.join(current_dir, filename))
    possible_paths.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename))
    
    for p in possible_paths:
        if os.path.exists(p):
            return p
    return filename


# =====================================================================
# 2. Khởi tạo Logging
# =====================================================================
logger = logging.getLogger("OmniVoiceGUI")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

# Ghi log ra file
log_file = os.path.join(cache_dir, "app.log")
file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

class SafeStream:
    def write(self, string):
        pass
    def flush(self):
        pass

out_stream = sys.stdout if sys.stdout is not None else SafeStream()
console_handler = logging.StreamHandler(out_stream)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Tắt log rác mức INFO/DEBUG từ các thư viện bên thứ 3
for lib_name in ["huggingface_hub", "urllib3", "filelock", "transformers", "asyncio", "httpx", "kaggle"]:
    logging.getLogger(lib_name).setLevel(logging.WARNING)

# =====================================================================
# 2.1 Lớp chuyển hướng stdout/stderr sang Log Widget (Lọc log thô)
# =====================================================================
class RedirectText:
    def __init__(self, text_widget, log_file_path=None):
        self.text_widget = text_widget
        self.log_file_path = log_file_path

    def write(self, string):
        if not string or self.text_widget is None:
            return
            
        # Luôn ghi đầy đủ vào file log hệ thống
        if self.log_file_path:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(string)
            except Exception:
                pass

        strip_str = string.strip()
        if not strip_str:
            return

        # Lọc các dòng log thô/code/warnings không cần thiết trên UI
        if ("%" in strip_str and "|" in strip_str) or ("B/s" in strip_str and "/" in strip_str) or ("it/s" in strip_str):
            return
        if "DEBUG" in strip_str and ("https://" in strip_str or "http://" in strip_str or "connection" in strip_str.lower()):
            return
        if any(w in strip_str for w in ["UserWarning", "DeprecationWarning", "FutureWarning", "SyntaxWarning"]):
            return
        if strip_str.startswith("File \"") or strip_str.startswith("line ") or "site-packages" in strip_str:
            return

        def append():
            try:
                if self.text_widget and self.text_widget.winfo_exists():
                    self.text_widget.configure(state='normal')
                    self.text_widget.insert('end', string if string.endswith('\n') else string + '\n')
                    self.text_widget.configure(state='disabled')
                    self.text_widget.see('end')
            except Exception:
                pass
        
        try:
            if hasattr(self.text_widget, 'after'):
                self.text_widget.after(0, append)
            else:
                append()
        except Exception:
            pass

    def flush(self):
        pass


# =====================================================================
# 3. Khai báo các biến và cấu hình mô hình
# =====================================================================
MODEL_OMNIVOICE = "k2-fsa/OmniVoice"
MODEL_TOKENIZER = "eustlb/higgs-audio-v2-tokenizer"
MODEL_ASR = "openai/whisper-large-v3-turbo"

loaded_model = None
model_loading = False
model_generating = False
download_in_progress = False

current_play_process = None
download_progress_callback = None

# =====================================================================
# 4. Monkey patch tqdm để bắt tiến trình tải của huggingface_hub
# =====================================================================
import tqdm
original_tqdm = tqdm.tqdm

class TqdmCallback(original_tqdm):
    def __init__(self, *args, **kwargs):
        desc = kwargs.get("desc", "Downloading")
        total = kwargs.get("total", None)
        if download_progress_callback:
            download_progress_callback(desc, total, 0)
        super().__init__(*args, **kwargs)

    def update(self, n=1):
        super().update(n)
        if download_progress_callback:
            # self.n là số bytes đã tải, self.total là tổng số bytes
            download_progress_callback(self.desc, self.total, self.n)

    def close(self):
        super().close()
        if download_progress_callback:
            download_progress_callback(self.desc, self.total, self.total)

# =====================================================================
# 5. Thiết lập giao diện GUI bằng Tkinter
# =====================================================================
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
import ttkbootstrap as tb

class OmniVoiceGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Siêu cấp tool Voice VIP PRO")
        
        # Đặt icon cửa sổ
        icon_path = get_asset_path("icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass
        
        # Tự động điều chỉnh kích thước theo chiều cao màn hình
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = 1100
        height = int(screen_height * 0.9)
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2 - 20
        self.root.geometry(f"{width}x{height}+{x}+{max(0, y)}")
        
        self.root.configure(background="#121214")
        
        # Đặt kích thước tối thiểu
        self.root.minsize(1024, 600)
        
        # Setup Style
        self.setup_styles()
        
        # Header Bar: Logo HTH + Tiêu đề Siêu cấp tool Voice VIP PRO
        header_frame = tk.Frame(self.root, bg="#1A1A1E", height=60)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        
        logo_png_path = get_asset_path("hth_logo.png")
        if os.path.exists(logo_png_path):
            try:
                from PIL import Image, ImageTk
                logo_img = Image.open(logo_png_path).resize((58, 58), Image.Resampling.LANCZOS)
                self.logo_tk = ImageTk.PhotoImage(logo_img)
                lbl_logo = tk.Label(header_frame, image=self.logo_tk, bg="#1A1A1E", bd=0)
                lbl_logo.pack(side=tk.LEFT, padx=(15, 10), pady=1)
            except Exception:
                pass
                
        lbl_title = tk.Label(header_frame, text="✨ SIÊU CẤP TOOL VOICE VIP PRO ✨", font=("Segoe UI", 15, "bold"), fg="#00E5FF", bg="#1A1A1E")
        lbl_title.pack(side=tk.LEFT, pady=10)
        
        lbl_sub = tk.Label(header_frame, text="HTH AI Voice Edition", font=("Segoe UI", 10, "bold italic"), fg="#FF007F", bg="#1A1A1E")
        lbl_sub.pack(side=tk.LEFT, padx=(10, 0), pady=14)
        
        # Giao diện chính chia làm 2 phần: Notebook ở trên, Log Panel ở dưới
        self.main_pane = tk.PanedWindow(self.root, orient=tk.VERTICAL, bg="#E9ECEF", bd=0, sashwidth=4)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))
        
        # Phần trên: Tabs điều khiển
        self.notebook = ttk.Notebook(self.main_pane)
        self.main_pane.add(self.notebook, minsize=480, stretch="always")
        
        # Tạo các tab
        self.tab_settings = ttk.Frame(self.notebook)
        self.tab_clone = ttk.Frame(self.notebook)
        self.tab_design = ttk.Frame(self.notebook)
        self.tab_engine = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_settings, text=" Cài đặt & Tải Model ")
        # self.notebook.add(self.tab_clone, text=" Voice Clone (Nhái Giọng) ") # Ẩn Tab Voice Clone
        self.notebook.add(self.tab_engine, text=" Cỗ máy tạo âm thanh ")
        
        # Phần dưới: Log Panel
        self.create_log_panel()
        
        # Hàm tự động cố định độ cao Log Panel ở đáy màn hình
        def _fix_log_sash():
            try:
                h = self.root.winfo_height()
                if h > 300:
                    self.main_pane.sash_place(0, 0, h - 135)
            except Exception:
                pass
        self.root.after(150, _fix_log_sash)
        self.root.after(500, _fix_log_sash)
        
        # Khởi tạo các biến cấu hình & nạp config
        self.gemini_key_var = tk.StringVar()
        self.run_mode_var = tk.StringVar(value="Cloud API (Chạy trên Colab/Kaggle)")
        self.api_server_url_var = tk.StringVar(value="http://127.0.0.1:8000")
        self.kaggle_username_var = tk.StringVar()
        self.kaggle_key_var = tk.StringVar()
        self.kaggle_flux_key_var = tk.StringVar()
        self.proxy_var = tk.StringVar()
        self.kaggle_secret_id = ""
        self.kaggle_flux_secret_id = ""
        self.kaggle_gpu = "NvidiaTeslaT4"
        self.merge_silence_duration = 0.2
        self.flux_server_url = "http://127.0.0.1:8188"
        self.imported_txt_name = None
        self.status_omnivoice_val = tk.StringVar(value="Đang kiểm tra...")
        self.status_tokenizer_val = tk.StringVar(value="Đang kiểm tra...")
        self.status_asr_val = tk.StringVar(value="Đang kiểm tra...")
        
        # Biến lưu trữ cấu hình Modal & Cloud API
        self.load_config()
        self.flux_server_url_var = tk.StringVar(value=self.flux_server_url)
        self.flux_ref_image_path = ""
        self.flux_stop_generation = False
        self.gemini_key_var.set(self.gemini_api_key)
        self.run_mode_var.set(self.run_mode)
        self.api_server_url_var.set(self.api_server_url)
        self.proxy_var.set(self.proxy_val)
        
        self.chunk_len_var = tk.IntVar(value=500)
        self.model_lock = threading.Lock()
        self.stop_generating_flag = False
        
        # Xây dựng nội dung từng tab
        self.build_settings_tab()
        self.on_run_mode_changed()
        self.build_clone_tab()
        self.build_engine_tab()
        
        # Đăng ký callback download
        global download_progress_callback
        download_progress_callback = self.update_download_progress_ui
        
        # Biến lưu trữ đường dẫn file âm thanh tham chiếu
        self.ref_audio_path = tk.StringVar(value="")
        self.saved_voices_dir = saved_voices_dir
        
        # Khởi tạo kiểm tra trạng thái model
        self.check_models_status_async()
        
        # Nạp danh sách giọng đọc đã lưu từ GitHub Repo chính thức
        self.load_saved_voices()
        
        # Log khởi động thành công
        self.log("Sẵn sàng sử dụng Siêu cấp tool Voice VIP PRO (Powered by Modal Cloud & GitHub).")

    def setup_styles(self):
        # Khởi tạo style từ ttkbootstrap với theme "minty" cực kỳ tươi tắn, sáng sủa
        self.style = tb.Style(theme="minty")
        style = self.style
        
        # Cấu hình lại các layout đặc thù để hài hòa với theme sáng
        style.configure("Card.TFrame", background="#F8F9FA", relief="flat", borderwidth=1)
        style.configure("Inner.TFrame", background="#F8F9FA")
        
        style.configure("Card.TLabel", background="#F8F9FA", foreground="#212529")
        style.configure("Title.TLabel", foreground="#20C997", font=("Segoe UI", 14, "bold"))
        style.configure("Section.TLabel", background="#F8F9FA", foreground="#20C997", font=("Segoe UI", 11, "bold"))
        style.configure("Status.TLabel", background="#F8F9FA", foreground="#6C757D", font=("Segoe UI", 9, "italic"))
        
        # Style cho các Button
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        style.configure("Accent.TButton", background="#28A745", foreground="#FFFFFF", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=6)
        style.map("Accent.TButton", background=[("active", "#218838"), ("disabled", "#E9ECEF")], foreground=[("disabled", "#6C757D")])
        
        style.configure("Stop.TButton", background="#DC3545", foreground="#FFFFFF", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=6)
        style.map("Stop.TButton", background=[("active", "#C82333")])


    def load_config(self):
        config_path = os.path.join(current_dir, "config.json")
        self.gemini_api_key = ""
        self.run_mode = "Cloud API (Modal.com Serverless GPU)"
        self.api_server_url = "https://modal.com"
        self.proxy_val = ""
        self.merge_silence_duration = 0.2
        self.flux_server_url = "http://127.0.0.1:8188"
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.gemini_api_key = data.get("gemini_api_key", "")
                    self.api_server_url = data.get("api_server_url", "https://modal.com")
                    self.proxy_val = data.get("proxy_val", "")
                    self.merge_silence_duration = data.get("merge_silence_duration", 0.2)
                    self.flux_server_url = data.get("flux_server_url", "http://127.0.0.1:8188")
            except Exception:
                pass
        self.apply_proxy()
        if self.proxy_val:
            threading.Thread(target=self.check_proxy_live_worker, daemon=True).start()
                
    def save_config(self):
        config_path = os.path.join(current_dir, "config.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "gemini_api_key": self.gemini_api_key,
                    "modal_urls": getattr(self, 'modal_urls', []),
                    "merge_silence_duration": float(self.merge_silence_duration_var.get() if hasattr(self, 'merge_silence_duration_var') else 0.2)
                }, f, indent=4, ensure_ascii=False)
            logger.debug("Đã lưu tệp config.json thành công!")
        except Exception as e:
            self.log(f"Lỗi khi lưu file config.json: {e}", "ERROR")

    def check_and_reset_kaggle_quota(self):
        try:
            from datetime import datetime, timedelta, timezone
            # Định nghĩa múi giờ UTC+7 (Việt Nam)
            tz_vn = timezone(timedelta(hours=7))
            now = datetime.now(tz_vn)
            
            # weekday() trả về 0 cho Thứ Hai, 5 cho Thứ Bảy.
            # Số ngày cần trừ đi để quay về thứ Bảy gần nhất:
            days_since_saturday = (now.weekday() - 5) % 7
            last_saturday = now - timedelta(days=days_since_saturday)
            last_saturday_reset = datetime(last_saturday.year, last_saturday.month, last_saturday.day, 7, 0, 0, tzinfo=tz_vn)
            
            # Nếu thời điểm hiện tại vẫn trước 07:00 sáng thứ Bảy tuần này:
            if now < last_saturday_reset:
                last_saturday_reset -= timedelta(days=7)
                
            last_saturday_ts = last_saturday_reset.timestamp()
            
            # Nếu mốc reset gần nhất lớn hơn thời điểm reset cuối cùng được ghi nhận
            if self.last_reset_timestamp < last_saturday_ts:
                for key in self.kaggle_api_keys_data:
                    if isinstance(self.kaggle_api_keys_data[key], dict):
                        self.kaggle_api_keys_data[key]["total_hours"] = 0.0
                    else:
                        self.kaggle_api_keys_data[key] = {"total_hours": 0.0}
                self.last_reset_timestamp = last_saturday_ts
                self.save_config()
        except Exception as e:
            self.log(f"[Kaggle] Lỗi khi kiểm tra reset định mức giờ API: {e}", "ERROR")

    def apply_proxy(self):
        self._clear_system_proxy()
        return
        try:
            proxy_str = self.proxy_var.get().strip()
            if proxy_str:
                raw_proxies = [p.strip() for p in proxy_str.split(",") if p.strip()]
                if not raw_proxies:
                    self._clear_system_proxy()
                    return
                    
                live_list = getattr(self, "live_proxies", [])
                chosen_proxy = None
                if live_list:
                    import random
                    chosen_proxy = random.choice(live_list)
                else:
                    import random
                    chosen_proxy = random.choice(raw_proxies)
                    
                parts = chosen_proxy.split(":")
                if len(parts) == 4:
                    ip, port, user, pw = parts
                    formatted_proxy = f"http://{user}:{pw}@{ip}:{port}"
                elif len(parts) == 2:
                    ip, port = parts
                    formatted_proxy = f"http://{ip}:{port}"
                else:
                    formatted_proxy = chosen_proxy
                
                os.environ["HTTP_PROXY"] = formatted_proxy
                os.environ["HTTPS_PROXY"] = formatted_proxy
                os.environ["http_proxy"] = formatted_proxy
                os.environ["https_proxy"] = formatted_proxy
                self.log(f"[Proxy] Đã áp dụng proxy hệ thống ngẫu nhiên: {ip}:{port}")
            else:
                self._clear_system_proxy()
        except Exception as e:
            self.log(f"[Proxy] Lỗi khi áp dụng proxy: {e}", "ERROR")

    def _clear_system_proxy(self):
        for env_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
            if env_var in os.environ:
                del os.environ[env_var]

    def check_proxy_live_thread(self):
        self.btn_check_proxy.configure(state="disabled")
        self.lbl_proxy_status.configure(text="🟡 Đang kiểm tra...", foreground="#FFA726")
        threading.Thread(target=self.check_proxy_live_worker, daemon=True).start()

    def check_proxy_live_worker(self):
        try:
            proxy_str = self.proxy_var.get().strip()
            if not proxy_str:
                self.live_proxies = []
                self.root.after(0, lambda: self.lbl_proxy_status.configure(text="Trạng thái: Chưa cấu hình", foreground="#A0A0AA"))
                self.root.after(0, lambda: self.btn_check_proxy.configure(state="normal"))
                return
                
            raw_proxies = [p.strip() for p in proxy_str.split(",") if p.strip()]
            self.live_proxies = []
            
            def check_single(p):
                parts = p.split(":")
                if len(parts) == 4:
                    ip, port, user, pw = parts
                    fmt = f"http://{user}:{pw}@{ip}:{port}"
                elif len(parts) == 2:
                    ip, port = parts
                    fmt = f"http://{ip}:{port}"
                else:
                    fmt = p
                proxies = {"http": fmt, "https": fmt}
                try:
                    r = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=5)
                    if r.status_code == 200:
                        return p, r.json().get("origin", "")
                except Exception:
                    pass
                return p, None

            from concurrent.futures import ThreadPoolExecutor
            checked_results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(check_single, raw_proxies)
                for p, origin_ip in results:
                    if origin_ip:
                        self.live_proxies.append(p)
                        checked_results.append((p, origin_ip))
            
            total = len(raw_proxies)
            live_count = len(self.live_proxies)
            
            if total == 1:
                if live_count == 1:
                    origin_ip = checked_results[0][1]
                    self.root.after(0, lambda: self.lbl_proxy_status.configure(text=f"🟢 Proxy Live (IP: {origin_ip})", foreground="#00E676"))
                    self.log(f"[Proxy] Kiểm tra proxy thành công! Proxy Live, phản hồi IP: {origin_ip}")
                else:
                    self.root.after(0, lambda: self.lbl_proxy_status.configure(text="🔴 Proxy Die / Lỗi kết nối", foreground="#FF3366"))
                    self.log("[Proxy] Kiểm tra proxy thất bại! Proxy bị lỗi hoặc không phản hồi.", "ERROR")
            else:
                if live_count > 0:
                    self.root.after(0, lambda: self.lbl_proxy_status.configure(text=f"🟢 Proxy Live: {live_count}/{total}", foreground="#00E676"))
                    self.log(f"[Proxy] Đã kiểm tra xong: {live_count}/{total} proxy hoạt động (Live).")
                else:
                    self.root.after(0, lambda: self.lbl_proxy_status.configure(text=f"🔴 Tất cả proxy đều Die ({live_count}/{total})", foreground="#FF3366"))
                    self.log("[Proxy] Kiểm tra hoàn tất. Không có proxy nào hoạt động!", "ERROR")
                    
            self.apply_proxy()
            
        except Exception as e:
            self.root.after(0, lambda: self.lbl_proxy_status.configure(text="🔴 Lỗi kiểm tra proxy", foreground="#FF3366"))
            self.log(f"[Proxy] Lỗi trong tiến trình kiểm tra proxy: {e}", "ERROR")
        finally:
            self.root.after(0, lambda: self.btn_check_proxy.configure(state="normal"))

    def save_all_settings(self):
        self.gemini_api_key = self.gemini_key_var.get().strip()
        self.run_mode = "Cloud API (Chạy trên Colab/Kaggle)"
        self.api_server_url = self.api_server_url_var.get().strip()
        if hasattr(self, 'txt_kaggle_key'):
            self.kaggle_key = self.txt_kaggle_key.get("1.0", tk.END).strip()
        else:
            self.kaggle_key = self.kaggle_key_var.get().strip()

        if hasattr(self, 'txt_kaggle_flux_key'):
            self.kaggle_flux_key = self.txt_kaggle_flux_key.get("1.0", tk.END).strip()
        else:
            self.kaggle_flux_key = self.kaggle_flux_key_var.get().strip()

        self.proxy_val = self.proxy_var.get().strip()
        self.save_config()
        self.apply_proxy()
        messagebox.showinfo("Thành công", "Đã lưu tất cả cấu hình thành công!")

    def on_run_mode_changed(self, event=None):
        pass

    def insert_expressions_with_gemini(self):
        text = self.txt_engine_input.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập văn bản cần chèn biểu cảm!")
            return
            
        api_key = self.gemini_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập và Lưu Google Studio API Key ở tab 'Cài đặt & Tải Model' trước khi sử dụng tính năng này!")
            self.notebook.select(self.tab_settings)
            return
            
        def worker():
            self.log("Đang kết nối tới Google Gemini để phân tích ngữ cảnh và chèn biểu cảm tự động...")
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                
                model = genai.GenerativeModel("gemini-3.5-flash")
                
                selected_engine = self.selected_ai_engine_var.get() if hasattr(self, 'selected_ai_engine_var') else ""
                
                if "VieNeu-TTS" in selected_engine:
                    prompt_tags = (
                        "DANH SÁCH CÁC THẺ CẢM XÚC VIENEU-TTS HỖ TRỢ (TUYỆT ĐỐI KHÔNG TỰ SINH THẺ MỚI KHÁC DANH SÁCH NÀY):\n"
                        "1. [cười] : Dùng khi có tiếng cười, sự vui vẻ, hài hước, châm biếm.\n"
                        "2. [thở dài] : Dùng khi thở dài, mệt mỏi, buồn chán, suy tư.\n"
                        "3. [hắng giọng] : Dùng khi hắng giọng, ngắt giọng hoặc chuẩn bị phát biểu.\n"
                        "4. [thì thầm] : Dùng khi nói nhỏ, thì thầm bí mật.\n"
                        "5. [ngập ngừng] : Dùng khi ngập ngừng, đắn đo, do dự.\n"
                        "6. [nói chậm] : Dùng khi đọc chậm rãi, từ tốn.\n"
                        "7. [nhấn giọng] : Dùng khi cần nhấn giọng mạnh mẽ.\n"
                    )
                else:
                    prompt_tags = (
                        "DANH SÁCH 13 THẺ CẢM XÚC HỖ TRỢ (TUYỆT ĐỐI KHÔNG TỰ SINH THẺ MỚI KHÁC DANH SÁCH NÀY):\n"
                        "1. [laughter] : Dùng khi có tiếng cười, sự vui vẻ, châm biếm nhẹ.\n"
                        "2. [sigh] : Dùng khi thở dài, mệt mỏi, buồn chán, suy tư.\n"
                        "3. [confirmation-en] : Từ xác nhận ngắn như 'uh-huh', 'yeah' (tiếng Anh).\n"
                        "4. [question-en] : Nhấn giọng nghi vấn hỏi tiếng Anh (như 'En?').\n"
                        "5. [question-ah] : Nhấn giọng nghi vấn hỏi tiếng Việt/Trung (như 'Á?', 'Ủa?').\n"
                        "6. [question-oh] : Nhấn giọng nghi vấn ngạc nhiên (như 'Ồ?').\n"
                        "7. [question-ei] : Nhấn giọng nghi vấn hỏi lại (như 'Ê?', 'Hả?').\n"
                        "8. [question-yi] : Nhấn giọng nghi vấn thắc mắc (như 'Ý?').\n"
                        "9. [surprise-ah] : Biểu lộ ngạc nhiên, sửng sốt (như 'A!', 'Á!').\n"
                        "10. [surprise-oh] : Biểu lộ ngạc nhiên, ngỡ ngàng (như 'Ồ!').\n"
                        "11. [surprise-wa] : Biểu lộ kinh ngạc, trầm trồ (như 'Oa!').\n"
                        "12. [surprise-yo] : Tiếng gọi ngạc nhiên, hào hứng (như 'Yo!', 'Dô!').\n"
                        "13. [dissatisfaction-hnn] : Bày tỏ sự bất bình, hậm hực, thất vọng (như 'Hừm...', 'Hnn...').\n"
                    )

                prompt = (
                    "Bạn là một chuyên gia biên tập kịch bản cho giọng đọc AI.\n"
                    f"Nhiệm vụ của bạn là phân tích ngữ cảnh văn bản và chèn các thẻ cảm xúc/nhãn biểu cảm của mô hình AI ({'VieNeu-TTS' if 'VieNeu-TTS' in selected_engine else 'OmniVoice'}) dưới đây vào đúng vị trí để giọng đọc AI diễn cảm, sống động nhất.\n\n"
                    f"{prompt_tags}\n"
                    "YÊU CẦU NGHIÊM NGẶT:\n"
                    "1. Chỉ sử dụng các thẻ trong danh sách trên. TUYỆT ĐỐI KHÔNG tự tạo ra bất kỳ thẻ mới nào ngoài danh sách này.\n"
                    "2. KHÔNG thêm bớt hay thay đổi bất kỳ từ ngữ nào của văn bản gốc. Chỉ chèn thẻ vào vị trí hợp lý.\n"
                    "3. ĐẶT THẺ CẢM XÚC Ở ĐẦU CÂU (TRƯỚC CÂU) HOẶC CUỐI CÂU (KHI ĐÃ KẾT THÚC CÂU). TUYỆT ĐỐI KHÔNG đặt thẻ cảm xúc chen ngang ở giữa câu.\n"
                    "4. Chèn một cách tự nhiên và vừa phải (khoảng 2-4 câu chèn 1 thẻ, tránh chèn quá dày đặc).\n"
                    "5. KHÔNG thêm bất kỳ câu giải thích hay ghi chú nào trước hoặc sau văn bản kết quả.\n"
                    "6. Chỉ trả về duy nhất văn bản cuối cùng sau khi đã được chèn thẻ cảm xúc.\n\n"
                    "Văn bản gốc cần xử lý:\n"
                    f"\"\"\"\n{text}\n\"\"\""
                )
                
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                
                if res_text.startswith('"""') and res_text.endswith('"""'):
                    res_text = res_text[3:-3].strip()
                elif res_text.startswith('```') and res_text.endswith('```'):
                    lines = res_text.split('\n')
                    if lines[0].startswith('```'):
                        lines = lines[1:]
                    if lines[-1].startswith('```'):
                        lines = lines[:-1]
                    res_text = '\n'.join(lines).strip()
                
                if res_text:
                    def update_ui():
                        self.txt_engine_input.delete("1.0", tk.END)
                        self.txt_engine_input.insert(tk.END, res_text)
                        self.log("Đã tự động chèn biểu cảm bằng Gemini thành công!")
                        self.split_text_to_chunks()
                        messagebox.showinfo("Thành công", "Đã chèn biểu cảm bằng Gemini và tự động chia đoạn hoàn tất!")
                        
                    self.root.after(0, update_ui)
                else:
                    self.log("Gemini trả về chuỗi rỗng.", "WARNING")
                    
            except Exception as err:
                self.log(f"Lỗi khi gọi API Gemini: {err}", "ERROR")
                err_msg = str(err)
                self.root.after(0, lambda msg=err_msg: messagebox.showerror("Lỗi", f"Lỗi khi gọi API Gemini:\n{msg}"))
                
        threading.Thread(target=worker, daemon=True).start()

    def log(self, message, level="INFO"):
        # Ghi log ra file/console
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)
            
        # Hiển thị lên UI Log Panel
        def append_log():
            self.log_text.configure(state='normal')
            self.log_text.insert('end', f"[{time.strftime('%H:%M:%S')}] [{level}] {message}\n")
            self.log_text.configure(state='disabled')
            self.log_text.see('end')
            
        self.root.after(0, append_log)

    # =====================================================================
    # Log Panel (Phần dưới giao diện)
    # =====================================================================
    def create_log_panel(self):
        log_frame = ttk.Frame(self.main_pane, height=110)
        self.main_pane.add(log_frame, minsize=80, stretch="never")
        
        # Tiêu đề Log
        title_label = ttk.Label(log_frame, text="Nhật ký hoạt động (App Logs)", font=("Segoe UI", 9, "bold"), foreground="#20C997")
        title_label.pack(anchor=tk.W, pady=(2, 1))
        
        # Khung Text hiển thị log cố định chiều cao 4 dòng
        self.log_text = tk.Text(log_frame, height=4, bg="#F8F9FA", fg="#495057", insertbackground="black",
                                font=("Consolas", 9), wrap=tk.WORD, state='disabled', relief='flat')
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Scrollbar cho Log
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        # Chuyển hướng stdout và stderr sang khung log của GUI
        sys.stdout = RedirectText(self.log_text, log_file)
        sys.stderr = RedirectText(self.log_text, log_file)


    # =====================================================================
    # Tab 1: Cài đặt Gemini & Hệ thống
    # =====================================================================
    def build_settings_tab(self):
        container = ttk.Frame(self.tab_settings, padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        
        lbl_title = ttk.Label(container, text="⚙️ CẤU HÌNH AI & CÀI ĐẶT HỆ THỐNG", font=("Segoe UI", 13, "bold"))
        lbl_title.pack(anchor=tk.W, pady=(0, 15))
        
        # Frame Gemini API Key Config
        gemini_frame = ttk.LabelFrame(container, text=" 🤖 Google AI Studio (Gemini API Key) ", padding=15)
        gemini_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(gemini_frame, text="Google AI Studio API Key (Gemini cho AI Kịch bản / Dịch thuật):").pack(anchor=tk.W, pady=(2, 5))
        self.gemini_key_entry = ttk.Entry(gemini_frame, textvariable=self.gemini_key_var, show="*", width=50)
        self.gemini_key_entry.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))
        
        btn_save_settings = ttk.Button(gemini_frame, text="💾 Lưu cấu hình Gemini", style="Accent.TButton", command=self.save_all_settings)
        btn_save_settings.pack(anchor=tk.W, pady=(5, 0))

    # =====================================================================
    # Tab 2: Voice Clone
    # =====================================================================
    def build_clone_tab(self):
        container = ttk.Frame(self.tab_clone)
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Cột trái: Nhập liệu & Cấu hình
        left_col = ttk.Frame(container)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # 1. Nhập văn bản cần đọc
        ttk.Label(left_col, text="Nhập văn bản cần sinh giọng nói:").pack(anchor=tk.W, pady=(0, 5))
        self.txt_clone_input = tk.Text(left_col, bg="#FFFFFF", fg="#212529", insertbackground="black",
                                       font=("Segoe UI", 10), height=5, wrap=tk.WORD, relief="flat", bd=1)
        self.txt_clone_input.pack(fill=tk.X, pady=(0, 5))
        self.txt_clone_input.insert("1.0", "Xin chào! Đây là bản thử nghiệm tính năng nhái giọng nói chất lượng cao chạy hoàn toàn offline trên ổ đĩa E.")
        
        # 1.1 Thanh chèn biểu cảm (Expression Toolbar)
        f_express = ttk.Frame(left_col)
        f_express.pack(fill=tk.X, pady=(0, 15))
        ttk.Label(f_express, text="Nhấn nhá biểu cảm:", font=("Segoe UI", 9, "bold"), foreground="#20C997").pack(side=tk.LEFT, padx=(0, 5))
        
        expressions = [
            ("Cười 😊", "[laughter]"),
            ("Thở dài 😮‍💨", "[sigh]"),
            ("Ngạc nhiên 😲", "[surprise-ah]"),
            ("Ồ! 😲", "[surprise-oh]"),
            ("Hỏi (En?) ❓", "[question-en]"),
            ("Bất bình 😠", "[dissatisfaction-hnn]")
        ]
        
        for name, tag in expressions:
            btn = ttk.Button(f_express, text=name, width=12,
                             command=lambda t=tag: self.insert_expression_tag(self.txt_clone_input, t))
            btn.pack(side=tk.LEFT, padx=2)
        
        # 2. File âm thanh mẫu
        card_ref = ttk.LabelFrame(left_col, text=" Âm thanh mẫu (Reference Audio) ", padding=10)
        card_ref.pack(fill=tk.X, pady=(0, 15))
        
        # 2.0 Chọn giọng đã lưu (Saved Voices)
        f_saved = ttk.Frame(card_ref)
        f_saved.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(f_saved, text="Chọn giọng đã lưu:").pack(side=tk.LEFT, padx=(0, 5))
        self.saved_voices_combo = ttk.Combobox(f_saved, state="readonly", width=25)
        self.saved_voices_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.saved_voices_combo.bind("<<ComboboxSelected>>", self.on_saved_voice_selected)
        
        f_select = ttk.Frame(card_ref)
        f_select.pack(fill=tk.X, pady=5)
        self.ent_ref_path = ttk.Entry(f_select, width=40, font=("Segoe UI", 9))
        self.ent_ref_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        btn_select = ttk.Button(f_select, text="Chọn file...", command=self.select_ref_audio)
        btn_select.pack(side=tk.RIGHT)
        
        # Hướng dẫn
        ttk.Label(card_ref, text="Khuyến nghị: File âm thanh mẫu dài từ 3 giây đến 10 giây.", font=("Segoe UI", 8, "italic"), foreground="#A0A0AA").pack(anchor=tk.W, pady=(0, 10))
        
        # Phát & dừng file mẫu
        f_play_ref = ttk.Frame(card_ref)
        f_play_ref.pack(fill=tk.X, pady=(0, 10))
        self.btn_play_ref = ttk.Button(f_play_ref, text="▶ Phát thử file mẫu", command=self.play_ref_audio)
        self.btn_play_ref.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_stop_ref = ttk.Button(f_play_ref, text="⏹ Dừng phát", style="Stop.TButton", command=self.stop_audio_playback)
        self.btn_stop_ref.pack(side=tk.LEFT)
        
        # 2.2 Lưu giọng hiện tại
        f_save_voice = ttk.Frame(card_ref)
        f_save_voice.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(f_save_voice, text="Tên để lưu giọng:").pack(side=tk.LEFT, padx=(0, 5))
        self.ent_save_voice_name = ttk.Entry(f_save_voice, font=("Segoe UI", 9), width=20)
        self.ent_save_voice_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        btn_save_voice = ttk.Button(f_save_voice, text="Lưu giọng này", command=self.save_current_voice)
        btn_save_voice.pack(side=tk.RIGHT)
        
        # 3. Văn bản của file mẫu (Reference Text)
        ttk.Label(card_ref, text="Văn bản của file mẫu (Reference Text):").pack(anchor=tk.W, pady=(10, 5))
        self.ent_ref_text = ttk.Entry(card_ref, font=("Segoe UI", 10))
        self.ent_ref_text.pack(fill=tk.X, pady=(0, 5))

        
        self.asr_enabled_var = tk.BooleanVar(value=True)
        self.chk_asr = ttk.Checkbutton(card_ref, text="Tự động nhận diện văn bản mẫu bằng Whisper ASR (nếu bỏ trống)", variable=self.asr_enabled_var)
        self.chk_asr.pack(anchor=tk.W, pady=5)

        # Cột phải: Cấu hình nâng cao & Tạo kết quả
        right_col = ttk.Frame(container)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        # Nhóm Cấu hình sinh
        card_config = ttk.LabelFrame(right_col, text=" Cấu hình tạo giọng nói (Tùy chọn) ", padding=12)
        card_config.pack(fill=tk.X, pady=(0, 20))
        
        # Ngôn ngữ
        ttk.Label(card_config, text="Ngôn ngữ đọc (Language):").pack(anchor=tk.W, pady=(0, 2))
        self.clone_lang_var = tk.StringVar(value="Auto")
        self.clone_lang_combo = ttk.Combobox(card_config, textvariable=self.clone_lang_var, state="readonly")
        self.clone_lang_combo['values'] = ["Auto", "Vietnamese", "English", "Chinese", "Korean", "Japanese", "French", "German", "Spanish", "Russian"]
        self.clone_lang_combo.pack(fill=tk.X, pady=(0, 10))
        
        # Tốc độ đọc
        ttk.Label(card_config, text="Tốc độ đọc (Speed):").pack(anchor=tk.W, pady=(0, 2))
        self.clone_speed_var = tk.DoubleVar(value=1.0)
        self.clone_speed_slider = ttk.Scale(card_config, from_=0.5, to=1.5, variable=self.clone_speed_var, orient=tk.HORIZONTAL)
        self.clone_speed_slider.pack(fill=tk.X, pady=(0, 2))
        self.lbl_clone_speed_val = ttk.Label(card_config, text="1.0x", font=("Segoe UI", 9, "bold"), foreground="#00ADB5")
        self.lbl_clone_speed_val.pack(anchor=tk.E, pady=(0, 10))
        self.clone_speed_var.trace_add("write", lambda *args: self.lbl_clone_speed_val.configure(text=f"{self.clone_speed_var.get():.2f}x"))
        
        # Số bước Inference Steps
        ttk.Label(card_config, text="Số bước khử nhiễu (Inference Steps):").pack(anchor=tk.W, pady=(0, 2))
        self.clone_steps_var = tk.IntVar(value=32)
        self.clone_steps_slider = ttk.Scale(card_config, from_=4, to=64, variable=self.clone_steps_var, orient=tk.HORIZONTAL)
        self.clone_steps_slider.pack(fill=tk.X, pady=(0, 2))
        self.lbl_clone_steps_val = ttk.Label(card_config, text="32 bước", font=("Segoe UI", 9, "bold"), foreground="#00ADB5")
        self.lbl_clone_steps_val.pack(anchor=tk.E, pady=(0, 10))
        self.clone_steps_var.trace_add("write", lambda *args: self.lbl_clone_steps_val.configure(text=f"{int(self.clone_steps_var.get())} bước"))
        
        # Nhóm Nút Generate và Kết quả
        self.btn_clone_generate = ttk.Button(right_col, text="🔥 BẮT ĐẦU NHÁI GIỌNG", style="Accent.TButton", command=self.generate_voice_clone)
        self.btn_clone_generate.pack(fill=tk.X, ipady=5, pady=(0, 15))
        
        # Cửa sổ Kết quả
        card_result = ttk.LabelFrame(right_col, text=" Kết quả đầu ra ", padding=12)
        card_result.pack(fill=tk.X)
        
        self.lbl_clone_result_status = ttk.Label(card_result, text="Chưa sinh file.", font=("Segoe UI", 9, "italic"))
        self.lbl_clone_result_status.pack(anchor=tk.W, pady=(0, 10))
        
        f_play_res = ttk.Frame(card_result)
        f_play_res.pack(fill=tk.X, pady=5)
        self.btn_play_clone_res = ttk.Button(f_play_res, text="▶ Phát âm thanh", command=self.play_clone_result)
        self.btn_play_clone_res.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_stop_clone_res = ttk.Button(f_play_res, text="⏹ Dừng", style="Stop.TButton", command=self.stop_audio_playback)
        self.btn_stop_clone_res.pack(side=tk.LEFT, padx=(0, 10))
        
        btn_open_dir = ttk.Button(f_play_res, text="📂 Mở thư mục", command=self.open_output_folder)
        btn_open_dir.pack(side=tk.RIGHT)
        
        # Đường dẫn file đã lưu
        self.clone_output_file = ""

    # =====================================================================
    # Tab 3: Voice Design
    # =====================================================================
    def build_design_tab(self):
        container = ttk.Frame(self.tab_design)
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Cột trái: Nhập liệu & Cấu hình các thuộc tính giọng nói
        left_col = ttk.Frame(container)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # 1. Nhập văn bản cần đọc
        ttk.Label(left_col, text="Nhập văn bản cần sinh giọng nói:").pack(anchor=tk.W, pady=(0, 5))
        self.txt_design_input = tk.Text(left_col, bg="#FFFFFF", fg="#212529", insertbackground="black",
                                       font=("Segoe UI", 10), height=5, wrap=tk.WORD, relief="flat", bd=1)
        self.txt_design_input.pack(fill=tk.X, pady=(0, 5))
        self.txt_design_input.insert("1.0", "Hello! This is a voice designed based on custom speaker attributes. You can control age, gender, pitch and accent.")
        
        # 1.1 Thanh chèn biểu cảm cho tab Design
        f_express_design = ttk.Frame(left_col)
        f_express_design.pack(fill=tk.X, pady=(0, 15))
        ttk.Label(f_express_design, text="Nhấn nhá biểu cảm:", font=("Segoe UI", 9, "bold"), foreground="#20C997").pack(side=tk.LEFT, padx=(0, 5))
        
        expressions = [
            ("Cười 😊", "[laughter]"),
            ("Thở dài 😮‍💨", "[sigh]"),
            ("Ngạc nhiên 😲", "[surprise-ah]"),
            ("Ồ! 😲", "[surprise-oh]"),
            ("Hỏi (En?) ❓", "[question-en]"),
            ("Bất bình 😠", "[dissatisfaction-hnn]")
        ]
        
        for name, tag in expressions:
            btn = ttk.Button(f_express_design, text=name, width=12,
                             command=lambda t=tag: self.insert_expression_tag(self.txt_design_input, t))
            btn.pack(side=tk.LEFT, padx=2)
            
        # 2. Thiết kế giọng (Speaker Attributes)
        card_attributes = ttk.LabelFrame(left_col, text=" Thiết kế các thuộc tính Giọng nói (Voice Attributes) ", padding=12)
        card_attributes.pack(fill=tk.X)

        
        # Dùng grid 2 cột cho các dropdown
        grid_frame = ttk.Frame(card_attributes)
        grid_frame.pack(fill=tk.X)
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)
        
        # Giới tính (Gender)
        ttk.Label(grid_frame, text="Giới tính (Gender):").grid(row=0, column=0, sticky=tk.W, pady=(5, 2), padx=(0, 10))
        self.vd_gender_var = tk.StringVar(value="Auto")
        self.vd_gender_combo = ttk.Combobox(grid_frame, textvariable=self.vd_gender_var, state="readonly")
        self.vd_gender_combo['values'] = ["Auto", "Male / Nam", "Female / 女"]
        self.vd_gender_combo.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10), padx=(0, 10))
        
        # Tuổi tác (Age)
        ttk.Label(grid_frame, text="Độ tuổi (Age):").grid(row=0, column=1, sticky=tk.W, pady=(5, 2))
        self.vd_age_var = tk.StringVar(value="Auto")
        self.vd_age_combo = ttk.Combobox(grid_frame, textvariable=self.vd_age_var, state="readonly")
        self.vd_age_combo['values'] = ["Auto", "Child / 儿童", "Teenager / 少年", "Young Adult / 青年", "Middle-aged / 中年", "Elderly / 老年"]
        self.vd_age_combo.grid(row=1, column=1, sticky=tk.EW, pady=(0, 10))
        
        # Cao độ (Pitch)
        ttk.Label(grid_frame, text="Âm điệu (Pitch):").grid(row=2, column=0, sticky=tk.W, pady=(5, 2), padx=(0, 10))
        self.vd_pitch_var = tk.StringVar(value="Auto")
        self.vd_pitch_combo = ttk.Combobox(grid_frame, textvariable=self.vd_pitch_var, state="readonly")
        self.vd_pitch_combo['values'] = ["Auto", "Very Low Pitch / 极低音调", "Low Pitch / 低音调", "Moderate Pitch / 中音调", "High Pitch / 高音调", "Very High Pitch / 极高音调"]
        self.vd_pitch_combo.grid(row=3, column=0, sticky=tk.EW, pady=(0, 10), padx=(0, 10))
        
        # Phong cách (Style)
        ttk.Label(grid_frame, text="Phong cách (Style):").grid(row=2, column=1, sticky=tk.W, pady=(5, 2))
        self.vd_style_var = tk.StringVar(value="Auto")
        self.vd_style_combo = ttk.Combobox(grid_frame, textvariable=self.vd_style_var, state="readonly")
        self.vd_style_combo['values'] = ["Auto", "Whisper / 耳语"]
        self.vd_style_combo.grid(row=3, column=1, sticky=tk.EW, pady=(0, 10))
        
        # Giọng Tiếng Anh (English Accent)
        ttk.Label(grid_frame, text="Khẩu âm Tiếng Anh (Accent):").grid(row=4, column=0, sticky=tk.W, pady=(5, 2), padx=(0, 10))
        self.vd_accent_var = tk.StringVar(value="Auto")
        self.vd_accent_combo = ttk.Combobox(grid_frame, textvariable=self.vd_accent_var, state="readonly")
        self.vd_accent_combo['values'] = ["Auto", "American Accent / 美式口音", "British Accent / 英国口音", "Australian Accent / 澳大利亚口音", "Chinese Accent / 中国口音", "Canadian Accent / 加拿大口音", "Indian Accent / 印度口音", "Japanese Accent / 日本口音"]
        self.vd_accent_combo.grid(row=5, column=0, sticky=tk.EW, pady=(0, 10), padx=(0, 10))
        
        # Giọng địa phương Tiếng Trung (Chinese Dialect)
        ttk.Label(grid_frame, text="Phương ngôn Trung Quốc (Dialect):").grid(row=4, column=1, sticky=tk.W, pady=(5, 2))
        self.vd_dialect_var = tk.StringVar(value="Auto")
        self.vd_dialect_combo = ttk.Combobox(grid_frame, textvariable=self.vd_dialect_var, state="readonly")
        self.vd_dialect_combo['values'] = ["Auto", "Sichuan Dialect / 四川话", "Henan Dialect / 河南话", "Shaanxi Dialect / 陕西话", "Northeast Dialect / 东北话"]
        self.vd_dialect_combo.grid(row=5, column=1, sticky=tk.EW, pady=(0, 10))

        # Cột phải: Cấu hình & Kết quả
        right_col = ttk.Frame(container)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        # Nhóm Cấu hình sinh
        card_config = ttk.LabelFrame(right_col, text=" Cấu hình tạo giọng nói (Tùy chọn) ", padding=12)
        card_config.pack(fill=tk.X, pady=(0, 20))
        
        # Ngôn ngữ
        ttk.Label(card_config, text="Ngôn ngữ đọc (Language):").pack(anchor=tk.W, pady=(0, 2))
        self.design_lang_var = tk.StringVar(value="Auto")
        self.design_lang_combo = ttk.Combobox(card_config, textvariable=self.design_lang_var, state="readonly")
        self.design_lang_combo['values'] = ["Auto", "English", "Vietnamese", "Chinese", "Korean", "Japanese", "French", "German", "Spanish", "Russian"]
        self.design_lang_combo.pack(fill=tk.X, pady=(0, 10))
        
        # Tốc độ đọc
        ttk.Label(card_config, text="Tốc độ đọc (Speed):").pack(anchor=tk.W, pady=(0, 2))
        self.design_speed_var = tk.DoubleVar(value=1.0)
        self.design_speed_slider = ttk.Scale(card_config, from_=0.5, to=1.5, variable=self.design_speed_var, orient=tk.HORIZONTAL)
        self.design_speed_slider.pack(fill=tk.X, pady=(0, 2))
        self.lbl_design_speed_val = ttk.Label(card_config, text="1.0x", font=("Segoe UI", 9, "bold"), foreground="#00ADB5")
        self.lbl_design_speed_val.pack(anchor=tk.E, pady=(0, 10))
        self.design_speed_var.trace_add("write", lambda *args: self.lbl_design_speed_val.configure(text=f"{self.design_speed_var.get():.2f}x"))
        
        # Số bước Inference Steps
        ttk.Label(card_config, text="Số bước khử nhiễu (Inference Steps):").pack(anchor=tk.W, pady=(0, 2))
        self.design_steps_var = tk.IntVar(value=32)
        self.design_steps_slider = ttk.Scale(card_config, from_=4, to=64, variable=self.design_steps_var, orient=tk.HORIZONTAL)
        self.design_steps_slider.pack(fill=tk.X, pady=(0, 2))
        self.lbl_design_steps_val = ttk.Label(card_config, text="32 bước", font=("Segoe UI", 9, "bold"), foreground="#00ADB5")
        self.lbl_design_steps_val.pack(anchor=tk.E, pady=(0, 10))
        self.design_steps_var.trace_add("write", lambda *args: self.lbl_design_steps_val.configure(text=f"{int(self.design_steps_var.get())} bước"))
        
        # Nhóm Nút Generate và Kết quả
        self.btn_design_generate = ttk.Button(right_col, text="✨ THIẾT KẾ GIỌNG NÓI", style="Accent.TButton", command=self.generate_voice_design)
        self.btn_design_generate.pack(fill=tk.X, ipady=5, pady=(0, 15))
        
        # Cửa sổ Kết quả
        card_result = ttk.LabelFrame(right_col, text=" Kết quả đầu ra ", padding=12)
        card_result.pack(fill=tk.X)
        
        self.lbl_design_result_status = ttk.Label(card_result, text="Chưa sinh file.", font=("Segoe UI", 9, "italic"))
        self.lbl_design_result_status.pack(anchor=tk.W, pady=(0, 10))
        
        f_play_res = ttk.Frame(card_result)
        f_play_res.pack(fill=tk.X, pady=5)
        self.btn_play_design_res = ttk.Button(f_play_res, text="▶ Phát âm thanh", command=self.play_design_result)
        self.btn_play_design_res.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_stop_design_res = ttk.Button(f_play_res, text="⏹ Dừng", style="Stop.TButton", command=self.stop_audio_playback)
        self.btn_stop_design_res.pack(side=tk.LEFT, padx=(0, 10))
        
        btn_open_dir = ttk.Button(f_play_res, text="📂 Mở thư mục", command=self.open_output_folder)
        btn_open_dir.pack(side=tk.RIGHT)
        
        # Đường dẫn file đã lưu
        self.design_output_file = ""

    def build_engine_tab(self):
        container = ttk.Frame(self.tab_engine, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        
        # PanedWindow chia 2 cột trái phải
        pane = tk.PanedWindow(container, orient=tk.HORIZONTAL, bg="#E9ECEF", bd=0, sashwidth=4)
        pane.pack(fill=tk.BOTH, expand=True)
        
        left_col = ttk.Frame(pane)
        right_col = ttk.Frame(pane)
        
        pane.add(left_col, minsize=560)
        pane.add(right_col, minsize=350)
        
        # --- CỘT TRÁI: Nhập văn bản & Quản lý đoạn ---
        # 1. Khung soạn thảo / Import
        f_import = ttk.Frame(left_col)
        f_import.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(f_import, text="Văn bản cần đọc (Nhập hoặc import file):", font=("Segoe UI", 10, "bold"), foreground="#20C997").pack(side=tk.LEFT)
        ttk.Button(f_import, text="📂 Import file TXT", command=self.import_txt_file).pack(side=tk.RIGHT)
        
        self.txt_engine_input = tk.Text(left_col, height=4, bg="#FFFFFF", fg="#212529", insertbackground="black", font=("Segoe UI", 10), wrap=tk.WORD)
        self.txt_engine_input.pack(fill=tk.X, pady=(0, 5))
        
        # Nút biểu cảm nhấn nhá (Thay đổi động theo AI Engine được chọn)
        self.f_express = ttk.Frame(left_col)
        self.f_express.pack(fill=tk.X, pady=(0, 5))
        self.update_expression_tags_ui()
            
        # 2. Khung cấu hình chia đoạn (Chunking)
        f_chunk_config = ttk.Frame(left_col)
        f_chunk_config.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(f_chunk_config, text="Cách chia đoạn:").pack(side=tk.LEFT, padx=(0, 10))
        
        self.chunk_mode_var = tk.StringVar(value="line")
        ttk.Radiobutton(f_chunk_config, text="Theo dòng mới (\\n)", variable=self.chunk_mode_var, value="line").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(f_chunk_config, text="Theo câu (. ! ?)", variable=self.chunk_mode_var, value="sentence").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(f_chunk_config, text="Theo số ký tự", variable=self.chunk_mode_var, value="length").pack(side=tk.LEFT, padx=5)
        
        # Spinbox cấu hình giới hạn ký tự
        ttk.Label(f_chunk_config, text="Giới hạn ký tự:").pack(side=tk.LEFT, padx=(10, 2))
        self.spin_chunk_len = ttk.Spinbox(f_chunk_config, from_=50, to=5000, increment=50, width=6, textvariable=self.chunk_len_var)
        self.spin_chunk_len.pack(side=tk.LEFT, padx=(0, 5))
        
        # Dòng nút hành động (Auto chèn biểu cảm Gemini & Chia đoạn)
        f_chunk_actions = ttk.Frame(left_col)
        f_chunk_actions.pack(fill=tk.X, pady=(0, 5))
        
        btn_gemini = ttk.Button(f_chunk_actions, text="✨ Auto chèn biểu cảm (Gemini)", command=self.insert_expressions_with_gemini)
        btn_gemini.pack(side=tk.LEFT, padx=(0, 10))
        
        btn_split = ttk.Button(f_chunk_actions, text="⚡ Chia đoạn văn bản", style="Accent.TButton", command=self.split_text_to_chunks)
        btn_split.pack(side=tk.LEFT)
        
        # 3. Danh sách các đoạn
        f_tree_label = ttk.Frame(left_col)
        f_tree_label.pack(fill=tk.X, pady=(5, 2))
        ttk.Label(f_tree_label, text="Danh sách các đoạn văn bản sau chia nhỏ:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        
        f_tree = ttk.Frame(left_col)
        f_tree.pack(fill=tk.BOTH, expand=True)
        
        columns = ("stt", "content", "status", "take", "file")
        self.tree_chunks = ttk.Treeview(f_tree, columns=columns, show="headings", height=5)
        
        # Cho phép nhấn vào tiêu đề để sắp xếp
        self.tree_chunks.heading("stt", text="STT", command=lambda: self.sort_treeview_column("stt", False))
        self.tree_chunks.heading("content", text="Nội dung đoạn", command=lambda: self.sort_treeview_column("content", False))
        self.tree_chunks.heading("status", text="Trạng thái", command=lambda: self.sort_treeview_column("status", False))
        self.tree_chunks.heading("take", text="Bản chọn (Take)", command=lambda: self.sort_treeview_column("take", False))
        self.tree_chunks.heading("file", text="Đường dẫn file tạm", command=lambda: self.sort_treeview_column("file", False))
        
        self.tree_chunks.column("stt", width=40, minwidth=35, anchor=tk.CENTER)
        self.tree_chunks.column("content", width=260, minwidth=180, anchor=tk.W)
        self.tree_chunks.column("status", width=85, minwidth=70, anchor=tk.CENTER)
        self.tree_chunks.column("take", width=95, minwidth=80, anchor=tk.CENTER)
        self.tree_chunks.column("file", width=120, minwidth=90, anchor=tk.W)
        
        vsb = ttk.Scrollbar(f_tree, orient="vertical", command=self.tree_chunks.yview)
        self.tree_chunks.configure(yscrollcommand=vsb.set)
        
        self.tree_chunks.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Double click to play
        self.tree_chunks.bind("<Double-1>", lambda event: self.play_selected_chunk())
        self.tree_chunks.bind("<<TreeviewSelect>>", self.on_chunk_selected)
        
        # Các nút thao tác trên treeview (tất cả trên 1 hàng ngang, text rút gọn để hiển thị đầy đủ)
        f_actions = ttk.Frame(left_col, padding=5)
        f_actions.pack(fill=tk.X, pady=(5, 0))
        
        self.btn_engine_gen_all = ttk.Button(f_actions, text="🎙️ Tạo tất cả", style="Accent.TButton", command=self.generate_all_chunks)
        self.btn_engine_gen_all.pack(side=tk.LEFT, padx=3)
        
        self.btn_engine_stop_gen = ttk.Button(f_actions, text="🛑 Dừng tạo", style="Stop.TButton", command=self.stop_generating_voice)
        self.btn_engine_stop_gen.pack(side=tk.LEFT, padx=3)
        
        self.btn_engine_gen_sel = ttk.Button(f_actions, text="🎙️ Tạo đoạn chọn", command=self.generate_selected_chunk)
        self.btn_engine_gen_sel.pack(side=tk.LEFT, padx=3)
        
        self.btn_engine_gen_failed = ttk.Button(f_actions, text="🔄 Tạo lại lỗi", command=self.generate_failed_chunks)
        self.btn_engine_gen_failed.pack(side=tk.LEFT, padx=3)
        
        self.btn_engine_play_sel = ttk.Button(f_actions, text="▶️ Phát chọn", command=self.play_selected_chunk)
        self.btn_engine_play_sel.pack(side=tk.LEFT, padx=3)
        
        self.btn_engine_stop = ttk.Button(f_actions, text="⏹️ Dừng", style="Stop.TButton", command=self.stop_audio_playback)
        self.btn_engine_stop.pack(side=tk.LEFT, padx=3)
        
        # Hàng quản lý Bản chọn (Takes) dưới hàng actions
        f_take_actions = ttk.Frame(left_col, padding=5)
        f_take_actions.pack(fill=tk.X, pady=(2, 0))
        
        ttk.Label(f_take_actions, text="Chọn phiên bản đọc (Take):", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(3, 5))
        self.combo_engine_takes = ttk.Combobox(f_take_actions, state="readonly", width=12)
        self.combo_engine_takes.pack(side=tk.LEFT, padx=3)
        self.combo_engine_takes.bind("<<ComboboxSelected>>", self.on_take_selected)
        
        self.btn_engine_del_take = ttk.Button(f_take_actions, text="🗑️ Xóa Take", command=self.delete_selected_take)
        self.btn_engine_del_take.pack(side=tk.LEFT, padx=10)
        
        # --- CỘT PHẢI: Cấu hình giọng & Xuất file ---
        # 1. Chọn giọng đọc tham chiếu (Voice Clone)
        card_ref = ttk.LabelFrame(right_col, text=" 👤 Giọng đọc tham chiếu (Voice Clone) ", padding=6)
        card_ref.pack(fill=tk.X, pady=(0, 10))
        
        # --- Bộ Lọc Đa Điều Kiện cho Voice Mẫu ---
        f_voice_filters = ttk.Frame(card_ref)
        f_voice_filters.pack(fill=tk.X, pady=(0, 4))
        
        # 1. Bộ lọc Ngôn ngữ
        self.filter_lang_var = tk.StringVar(value="Ngôn ngữ: Tất cả")
        self.combo_filter_lang = ttk.Combobox(f_voice_filters, textvariable=self.filter_lang_var, state="readonly", width=12)
        self.combo_filter_lang.pack(side=tk.LEFT, padx=(0, 2))
        self.combo_filter_lang.bind("<<ComboboxSelected>>", self.apply_voice_filters)
        
        # 2. Bộ lọc Giới tính
        self.filter_gender_var = tk.StringVar(value="Giới tính: Tất cả")
        self.combo_filter_gender = ttk.Combobox(f_voice_filters, textvariable=self.filter_gender_var, state="readonly", width=12)
        self.combo_filter_gender.pack(side=tk.LEFT, padx=2)
        self.combo_filter_gender.bind("<<ComboboxSelected>>", self.apply_voice_filters)
        
        # 3. Bộ lọc Thể loại
        self.filter_cat_var = tk.StringVar(value="Thể loại: Tất cả")
        self.combo_filter_cat = ttk.Combobox(f_voice_filters, textvariable=self.filter_cat_var, state="readonly", width=14)
        self.combo_filter_cat.pack(side=tk.LEFT, padx=(2, 0))
        self.combo_filter_cat.bind("<<ComboboxSelected>>", self.apply_voice_filters)

        # 4. Ô nhập Voice ID để tự chọn giọng trùng khớp
        f_voice_id_search = ttk.Frame(card_ref)
        f_voice_id_search.pack(fill=tk.X, pady=(2, 4))
        
        ttk.Label(f_voice_id_search, text="🔍 Nhập Voice ID:", font=("Segoe UI", 9, "bold"), foreground="#00E5FF").pack(side=tk.LEFT, padx=(0, 5))
        self.voice_id_search_var = tk.StringVar()
        self.ent_voice_id_search = ttk.Entry(f_voice_id_search, textvariable=self.voice_id_search_var, font=("Segoe UI", 9))
        self.ent_voice_id_search.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.voice_id_search_var.trace_add("write", lambda *args: self.search_voice_by_id())

        ttk.Label(card_ref, text="Chọn giọng đã lưu:").pack(anchor=tk.W, pady=(2, 2))
        self.engine_saved_voices_combo = ttk.Combobox(card_ref, state="readonly")
        self.engine_saved_voices_combo.pack(fill=tk.X, pady=(0, 4))
        self.engine_saved_voices_combo.bind("<<ComboboxSelected>>", self.on_engine_voice_selected)
        
        self.engine_ref_audio = tk.StringVar(value="")
        self.engine_ref_text = tk.StringVar(value="")
        
        self.lbl_engine_voice_info = ttk.Label(card_ref, text="Chưa chọn giọng tham chiếu.", font=("Segoe UI", 9, "italic"), foreground="#A0A0AA")
        self.lbl_engine_voice_info.pack(anchor=tk.W, pady=1)
        
        # 2. Đặc tính giọng nói (Voice Design)
        card_config = ttk.LabelFrame(right_col, text=" 🎛️ Tinh chỉnh phát âm & Đặc tính giọng ", padding=8)
        card_config.pack(fill=tk.X, pady=(0, 8))
        
        # Chọn Mô hình AI Engine (OmniVoice vs VieNeu-TTS)
        f_engine_choice = ttk.Frame(card_config)
        f_engine_choice.pack(fill=tk.X, pady=(0, 6))
        
        ttk.Label(f_engine_choice, text="🚀 AI Engine:", font=("Segoe UI", 9, "bold"), foreground="#00E676").pack(side=tk.LEFT, padx=(0, 5))
        self.selected_ai_engine_var = tk.StringVar(value="OmniVoice v0.2.1 (Multi-lingual)")
        self.combo_ai_engine = ttk.Combobox(f_engine_choice, textvariable=self.selected_ai_engine_var, state="readonly", width=38)
        self.combo_ai_engine['values'] = [
            "OmniVoice v0.2.1 (Multi-lingual)",
            "VieNeu-TTS v3 Turbo (48kHz Tiếng Việt Cảm xúc)"
        ]
        self.combo_ai_engine.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def on_ai_engine_changed(event=None):
            selected = self.selected_ai_engine_var.get() if hasattr(self, 'selected_ai_engine_var') else ""
            is_vieneu = "VieNeu-TTS" in selected
            
            if hasattr(self, 'update_expression_tags_ui'):
                self.update_expression_tags_ui()
                
            widgets_to_hide = [
                'lbl_engine_lang', 'engine_lang_combo',
                'lbl_engine_style', 'engine_style_combo',
                'lbl_engine_pitch', 'engine_pitch_combo',
                'lbl_engine_steps', 'f_steps',
                'lbl_engine_cfg', 'f_cfg',
                'lbl_engine_temp', 'f_temp'
            ]
            
            for w_name in widgets_to_hide:
                if hasattr(self, w_name):
                    w = getattr(self, w_name)
                    if is_vieneu:
                        w.grid_remove()
                    else:
                        w.grid()

        self.combo_ai_engine.bind("<<ComboboxSelected>>", on_ai_engine_changed)

        # Grid layout để tiết kiệm không gian đứng, tránh tràn màn hình
        grid_config = ttk.Frame(card_config)
        grid_config.pack(fill=tk.X)
        grid_config.columnconfigure(0, weight=1)
        grid_config.columnconfigure(1, weight=1)
        
        # Hàng 0, 1: Ngôn ngữ (Cột 0) và Đặc tính (Cột 1)
        self.lbl_engine_lang = ttk.Label(grid_config, text="Ngôn ngữ đọc (Language):")
        self.lbl_engine_lang.grid(row=0, column=0, sticky=tk.W, pady=(2, 2), padx=(0, 10))
        self.engine_lang_var = tk.StringVar(value="Auto")
        self.engine_lang_combo = ttk.Combobox(grid_config, textvariable=self.engine_lang_var, state="readonly")
        self.engine_lang_combo['values'] = ["Auto", "English", "Vietnamese", "Chinese", "Korean", "Japanese", "French", "German", "Spanish", "Russian"]
        self.engine_lang_combo.grid(row=1, column=0, sticky=tk.EW, pady=(0, 6), padx=(0, 10))
        
        self.lbl_engine_style = ttk.Label(grid_config, text="Đặc tính / Accent (Instruct):")
        self.lbl_engine_style.grid(row=0, column=1, sticky=tk.W, pady=(2, 2))
        self.engine_style_var = tk.StringVar(value="Auto")
        self.engine_style_combo = ttk.Combobox(grid_config, textvariable=self.engine_style_var, state="readonly")
        self.engine_style_combo['values'] = [
            "Auto", "Male / Giọng nam", "Female / Giọng nữ", "Whisper / Thì thầm", 
            "Child / Trẻ em", "Teenager / Thiếu niên", "Young adult / Thanh niên", 
            "Middle-aged / Trung niên", "Elderly / Người già", "American accent / Giọng Mỹ", 
            "British accent / Giọng Anh", "Australian accent / Giọng Úc", "Indian accent / Giọng Ấn Độ"
        ]
        self.engine_style_combo.grid(row=1, column=1, sticky=tk.EW, pady=(0, 6))
        
        # Hàng 2, 3: Cao độ (Cột 0) và Số luồng tạo (Cột 1)
        self.lbl_engine_pitch = ttk.Label(grid_config, text="Cao độ (Pitch):")
        self.lbl_engine_pitch.grid(row=2, column=0, sticky=tk.W, pady=(2, 2), padx=(0, 10))
        self.engine_pitch_var = tk.StringVar(value="Auto")
        self.engine_pitch_combo = ttk.Combobox(grid_config, textvariable=self.engine_pitch_var, state="readonly")
        self.engine_pitch_combo['values'] = [
            "Auto", "Very low pitch / Cực trầm", "Low pitch / Giọng trầm", 
            "Moderate pitch / Giọng vừa", "High pitch / Giọng cao", "Very high pitch / Cực cao"
        ]
        self.engine_pitch_combo.grid(row=3, column=0, sticky=tk.EW, pady=(0, 6), padx=(0, 10))

        ttk.Label(grid_config, text="Số luồng tạo (Threads):").grid(row=2, column=1, sticky=tk.W, pady=(2, 2))
        self.engine_threads_var = tk.StringVar(value="1")
        self.engine_threads_combo = ttk.Combobox(grid_config, textvariable=self.engine_threads_var, state="readonly")
        self.engine_threads_combo['values'] = ["1", "2", "3", "4", "6", "8", "12", "16"]
        self.engine_threads_combo.grid(row=3, column=1, sticky=tk.EW, pady=(0, 6))
        
        # Hàng 4, 5: Khử nhiễu (Ẩn thanh kéo, giữ mặc định 64) và Tốc độ đọc (Cột 1)
        self.lbl_engine_steps = ttk.Label(grid_config, text="Khử nhiễu (Steps):")
        self.f_steps = ttk.Frame(grid_config)
        # Ẩn thanh kéo khỏi giao diện theo yêu cầu
        # self.lbl_engine_steps.grid(row=4, column=0, sticky=tk.W, pady=(2, 2), padx=(0, 10))
        # self.f_steps.grid(row=5, column=0, sticky=tk.EW, pady=(0, 4), padx=(0, 10))
        
        self.engine_steps_var = tk.IntVar(value=64)
        self.engine_steps_slider = ttk.Scale(self.f_steps, from_=4, to=64, variable=self.engine_steps_var, orient=tk.HORIZONTAL)
        self.engine_steps_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # Thiết lập Entry nhập tay cho Steps
        self.ent_engine_steps_val = ttk.Entry(self.f_steps, width=6, justify=tk.CENTER)
        self.ent_engine_steps_val.pack(side=tk.RIGHT)
        self.ent_engine_steps_val.insert(0, "64")
        
        self.steps_trace_id = None
        def on_steps_slider_changed(*args):
            try:
                val = int(self.engine_steps_var.get())
                self.ent_engine_steps_val.delete(0, tk.END)
                self.ent_engine_steps_val.insert(0, str(val))
            except Exception:
                pass
                
        self.steps_trace_id = self.engine_steps_var.trace_add("write", on_steps_slider_changed)
        
        def on_steps_entry_enter(event):
            try:
                val = int(self.ent_engine_steps_val.get().strip())
                if val < 4:
                    val = 4
                elif val > 64:
                    val = 64
                
                # Tạm thời gỡ trace để tránh loop
                self.engine_steps_var.trace_remove("write", self.steps_trace_id)
                self.engine_steps_var.set(val)
                self.steps_trace_id = self.engine_steps_var.trace_add("write", on_steps_slider_changed)
                
                self.ent_engine_steps_val.delete(0, tk.END)
                self.ent_engine_steps_val.insert(0, str(val))
                self.root.focus()
            except ValueError:
                on_steps_slider_changed()
                
        self.ent_engine_steps_val.bind("<Return>", on_steps_entry_enter)

        ttk.Label(grid_config, text="Tốc độ đọc (Speed):").grid(row=4, column=1, sticky=tk.W, pady=(2, 2))
        f_speed = ttk.Frame(grid_config)
        f_speed.grid(row=5, column=1, sticky=tk.EW, pady=(0, 4))
        
        self.engine_speed_var = tk.DoubleVar(value=1.0)
        self.engine_speed_slider = ttk.Scale(f_speed, from_=0.5, to=1.5, variable=self.engine_speed_var, orient=tk.HORIZONTAL)
        self.engine_speed_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # Thiết lập Entry nhập tay cho Speed
        self.ent_engine_speed_val = ttk.Entry(f_speed, width=7, justify=tk.CENTER)
        self.ent_engine_speed_val.pack(side=tk.RIGHT)
        self.ent_engine_speed_val.insert(0, "1.00x")
        
        self.speed_trace_id = None
        def on_speed_slider_changed(*args):
            try:
                val = self.engine_speed_var.get()
                self.ent_engine_speed_val.delete(0, tk.END)
                self.ent_engine_speed_val.insert(0, f"{val:.2f}x")
            except Exception:
                pass
                
        self.speed_trace_id = self.engine_speed_var.trace_add("write", on_speed_slider_changed)
        
        def on_speed_entry_enter(event):
            try:
                val_str = self.ent_engine_speed_val.get().strip().replace("x", "")
                val = float(val_str)
                if val < 0.5:
                    val = 0.5
                elif val > 1.5:
                    val = 1.5
                
                # Tạm thời gỡ trace để tránh loop
                self.engine_speed_var.trace_remove("write", self.speed_trace_id)
                self.engine_speed_var.set(val)
                self.speed_trace_id = self.engine_speed_var.trace_add("write", on_speed_slider_changed)
                
                self.ent_engine_speed_val.delete(0, tk.END)
                self.ent_engine_speed_val.insert(0, f"{val:.2f}x")
                self.root.focus()
            except ValueError:
                on_speed_slider_changed()
                
        self.ent_engine_speed_val.bind("<Return>", on_speed_entry_enter)
        
        # Hàng 6, 7: Độ bám sát (CFG Scale) (Cột 0) và Độ biến hóa (Temperature) (Cột 1)
        self.lbl_engine_cfg = ttk.Label(grid_config, text="Độ bám sát giọng (CFG Scale):")
        self.lbl_engine_cfg.grid(row=6, column=0, sticky=tk.W, pady=(2, 2), padx=(0, 10))
        self.f_cfg = ttk.Frame(grid_config)
        self.f_cfg.grid(row=7, column=0, sticky=tk.EW, pady=(0, 4), padx=(0, 10))
        
        self.engine_cfg_var = tk.DoubleVar(value=2.0)
        self.engine_cfg_slider = ttk.Scale(self.f_cfg, from_=1.0, to=5.0, variable=self.engine_cfg_var, orient=tk.HORIZONTAL)
        self.engine_cfg_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.ent_engine_cfg_val = ttk.Entry(self.f_cfg, width=6, justify=tk.CENTER)
        self.ent_engine_cfg_val.pack(side=tk.RIGHT)
        self.ent_engine_cfg_val.insert(0, "2.0")
        
        self.cfg_trace_id = None
        def on_cfg_slider_changed(*args):
            try:
                val = self.engine_cfg_var.get()
                self.ent_engine_cfg_val.delete(0, tk.END)
                self.ent_engine_cfg_val.insert(0, f"{val:.1f}")
            except Exception:
                pass
        self.cfg_trace_id = self.engine_cfg_var.trace_add("write", on_cfg_slider_changed)
        
        def on_cfg_entry_enter(event):
            try:
                val = float(self.ent_engine_cfg_val.get().strip())
                if val < 1.0:
                    val = 1.0
                elif val > 5.0:
                    val = 5.0
                self.engine_cfg_var.trace_remove("write", self.cfg_trace_id)
                self.engine_cfg_var.set(val)
                self.cfg_trace_id = self.engine_cfg_var.trace_add("write", on_cfg_slider_changed)
                self.ent_engine_cfg_val.delete(0, tk.END)
                self.ent_engine_cfg_val.insert(0, f"{val:.1f}")
                self.root.focus()
            except ValueError:
                on_cfg_slider_changed()
        self.ent_engine_cfg_val.bind("<Return>", on_cfg_entry_enter)

        self.lbl_engine_temp = ttk.Label(grid_config, text="Độ biến hóa (Temperature):")
        self.lbl_engine_temp.grid(row=6, column=1, sticky=tk.W, pady=(2, 2))
        self.f_temp = ttk.Frame(grid_config)
        self.f_temp.grid(row=7, column=1, sticky=tk.EW, pady=(0, 4))
        
        self.engine_temp_var = tk.DoubleVar(value=5.0)
        self.engine_temp_slider = ttk.Scale(self.f_temp, from_=1.0, to=10.0, variable=self.engine_temp_var, orient=tk.HORIZONTAL)
        self.engine_temp_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.ent_engine_temp_val = ttk.Entry(self.f_temp, width=7, justify=tk.CENTER)
        self.ent_engine_temp_val.pack(side=tk.RIGHT)
        self.ent_engine_temp_val.insert(0, "5.0")
        
        self.temp_trace_id = None
        def on_temp_slider_changed(*args):
            try:
                val = self.engine_temp_var.get()
                self.ent_engine_temp_val.delete(0, tk.END)
                self.ent_engine_temp_val.insert(0, f"{val:.1f}")
            except Exception:
                pass
        self.temp_trace_id = self.engine_temp_var.trace_add("write", on_temp_slider_changed)
        
        def on_temp_entry_enter(event):
            try:
                val = float(self.ent_engine_temp_val.get().strip())
                if val < 1.0:
                    val = 1.0
                elif val > 10.0:
                    val = 10.0
                self.engine_temp_var.trace_remove("write", self.temp_trace_id)
                self.engine_temp_var.set(val)
                self.temp_trace_id = self.engine_temp_var.trace_add("write", on_temp_slider_changed)
                self.ent_engine_temp_val.delete(0, tk.END)
                self.ent_engine_temp_val.insert(0, f"{val:.1f}")
                self.root.focus()
            except ValueError:
                on_temp_slider_changed()
        self.ent_engine_temp_val.bind("<Return>", on_temp_entry_enter)
        
        # Hàng 8, 9: Khoảng đệm lặng (Pad Duration) (Cột 0) và Độ mượt hòa âm (Fade Duration) (Cột 1)
        ttk.Label(grid_config, text="Khoảng đệm lặng (Pad Duration - s):").grid(row=8, column=0, sticky=tk.W, pady=(2, 2), padx=(0, 10))
        f_pad = ttk.Frame(grid_config)
        f_pad.grid(row=9, column=0, sticky=tk.EW, pady=(0, 4), padx=(0, 10))
        
        self.engine_pad_var = tk.DoubleVar(value=0.0)
        self.engine_pad_slider = ttk.Scale(f_pad, from_=0.0, to=2.0, variable=self.engine_pad_var, orient=tk.HORIZONTAL)
        self.engine_pad_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.ent_engine_pad_val = ttk.Entry(f_pad, width=6, justify=tk.CENTER)
        self.ent_engine_pad_val.pack(side=tk.RIGHT)
        self.ent_engine_pad_val.insert(0, "0.00s")
        
        def on_pad_slider_changed(*args):
            try:
                val = self.engine_pad_var.get()
                self.ent_engine_pad_val.delete(0, tk.END)
                self.ent_engine_pad_val.insert(0, f"{val:.2f}s")
            except Exception:
                pass
        self.engine_pad_var.trace_add("write", on_pad_slider_changed)

        ttk.Label(grid_config, text="Độ mượt hòa âm (Fade Duration - s):").grid(row=8, column=1, sticky=tk.W, pady=(2, 2))
        f_fade = ttk.Frame(grid_config)
        f_fade.grid(row=9, column=1, sticky=tk.EW, pady=(0, 4))
        
        self.engine_fade_var = tk.DoubleVar(value=0.05)
        self.engine_fade_slider = ttk.Scale(f_fade, from_=0.0, to=1.0, variable=self.engine_fade_var, orient=tk.HORIZONTAL)
        self.engine_fade_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.ent_engine_fade_val = ttk.Entry(f_fade, width=6, justify=tk.CENTER)
        self.ent_engine_fade_val.pack(side=tk.RIGHT)
        self.ent_engine_fade_val.insert(0, "0.05s")
        
        def on_fade_slider_changed(*args):
            try:
                val = self.engine_fade_var.get()
                self.ent_engine_fade_val.delete(0, tk.END)
                self.ent_engine_fade_val.insert(0, f"{val:.2f}s")
            except Exception:
                pass
        self.engine_fade_var.trace_add("write", on_fade_slider_changed)
        
        # 3. Gộp & Xuất bản
        card_export = ttk.LabelFrame(right_col, text=" 📦 Gộp & Xuất bản tệp hoàn chỉnh ", padding=8)
        card_export.pack(fill=tk.X, pady=(0, 6))
        
        ttk.Label(card_export, text="Đường dẫn lưu file hoàn chỉnh:").pack(anchor=tk.W, pady=(0, 2))
        self.engine_dest_path = tk.StringVar(value="")
        
        f_dest = ttk.Frame(card_export)
        f_dest.pack(fill=tk.X, pady=(0, 6))
        self.ent_engine_dest = ttk.Entry(f_dest, textvariable=self.engine_dest_path)
        self.ent_engine_dest.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(f_dest, text="📂 Chọn", command=self.select_engine_export_path).pack(side=tk.RIGHT)
        
        # Checkbox cấu hình tự động xóa file tạm
        self.delete_temp_after_merge_var = tk.BooleanVar(value=True)
        self.chk_delete_temp = ttk.Checkbutton(card_export, text="Tự động dọn dẹp (xóa) toàn bộ file tạm sau khi gộp", variable=self.delete_temp_after_merge_var)
        self.chk_delete_temp.pack(anchor=tk.W, pady=(0, 6))
        
        # Cấu hình khoảng lặng giữa các đoạn
        f_silence = ttk.Frame(card_export)
        f_silence.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(f_silence, text="Khoảng lặng giữa các đoạn (giây):").pack(side=tk.LEFT, padx=(0, 5))
        
        init_silence = getattr(self, 'merge_silence_duration', 0.2)
        self.merge_silence_duration_var = tk.StringVar(value=str(init_silence))
        self.spn_silence = ttk.Spinbox(f_silence, from_=0.0, to=2.0, increment=0.1, textvariable=self.merge_silence_duration_var, width=8)
        self.spn_silence.pack(side=tk.LEFT)
        
        def on_silence_changed(event=None):
            self.save_config()
            
        self.spn_silence.bind("<FocusOut>", on_silence_changed)
        self.spn_silence.bind("<Return>", on_silence_changed)
        
        self.btn_engine_merge = ttk.Button(card_export, text="📦 GỘP CÁC ĐOẠN & DỌN DẸP FILE TẠM", style="Accent.TButton", command=self.merge_all_chunks)
        self.btn_engine_merge.pack(fill=tk.X, ipady=4)
        
        # Dữ liệu chunks trống
        self.chunks_data = []

    # =====================================================================
    # Xử lý Logic & Đa luồng (Threading)
    # =====================================================================
    def check_models_status_async(self):
        # Chạy kiểm tra bất đồng bộ tránh lag giao diện lúc bắt đầu
        threading.Thread(target=self.check_models_status_task, daemon=True).start()

    def check_models_status_task(self):
        from huggingface_hub import snapshot_download
        
        # 1. Check OmniVoice
        try:
            snapshot_download(repo_id=MODEL_OMNIVOICE, local_files_only=True)
            self.status_omnivoice_val.set("Đã tải xong")
        except Exception:
            self.status_omnivoice_val.set("Chưa tải")
            
        # 2. Check Higgs Tokenizer
        try:
            snapshot_download(repo_id=MODEL_TOKENIZER, local_files_only=True)
            self.status_tokenizer_val.set("Đã tải xong")
        except Exception:
            self.status_tokenizer_val.set("Chưa tải")
            
        # 3. Check Whisper ASR
        try:
            snapshot_download(repo_id=MODEL_ASR, local_files_only=True)
            self.status_asr_val.set("Đã tải xong")
        except Exception:
            self.status_asr_val.set("Chưa tải (Tùy chọn)")

    def update_download_progress_ui(self, desc, total, current):
        # Callback được gọi từ tqdm trong luồng download
        clean_desc = str(desc).strip()
        if not clean_desc or clean_desc == "None":
            clean_desc = "Đang tải tệp tin"
            
        if total and total > 0:
            percent = (current / total) * 100
            total_mb = total / (1024 * 1024)
            current_mb = current / (1024 * 1024)
            
            self.root.after(0, lambda: self.lbl_download_filename.configure(text=f"{clean_desc}"))
            self.root.after(0, lambda: self.download_progress_val.set(percent))
            self.root.after(0, lambda: self.lbl_download_pct.configure(text=f"{percent:.1f}% ({current_mb:.1f} MB / {total_mb:.1f} MB)"))
        else:
            current_kb = current / 1024
            self.root.after(0, lambda: self.lbl_download_filename.configure(text=f"{clean_desc}"))
            self.root.after(0, lambda: self.download_progress_val.set(0))
            self.root.after(0, lambda: self.lbl_download_pct.configure(text=f"Đã tải {current_kb:.1f} KB"))

    def start_download_models(self):
        global download_in_progress
        if download_in_progress:
            messagebox.showinfo("Thông báo", "Quá trình tải model đang diễn ra!")
            return
            
        download_in_progress = True
        self.btn_download.configure(state="disabled")
        self.log("Bắt đầu tải các model AI chưa có về ổ E...")
        
        # Monkey patch tqdm
        tqdm.tqdm = TqdmCallback
        
        threading.Thread(target=self.download_models_worker, daemon=True).start()

    def download_models_worker(self):
        from huggingface_hub import snapshot_download
        global download_in_progress
        
        repos = [MODEL_OMNIVOICE, MODEL_TOKENIZER, MODEL_ASR]
        success_count = 0
        
        for repo in repos:
            try:
                self.log(f"Đang kiểm tra và tải model: {repo}...")
                snapshot_download(repo_id=repo)
                self.log(f"Đã tải xong hoặc tệp đã có sẵn cho: {repo}")
                success_count += 1
            except Exception as e:
                self.log(f"Lỗi khi tải {repo}: {e}", "ERROR")
                
        # Khôi phục tqdm gốc
        tqdm.tqdm = original_tqdm
        download_in_progress = False
        
        self.root.after(0, lambda: self.btn_download.configure(state="normal"))
        self.root.after(0, lambda: self.lbl_download_filename.configure(text="Quá trình tải hoàn tất!"))
        self.root.after(0, lambda: self.download_progress_val.set(100.0))
        self.root.after(0, lambda: self.lbl_download_pct.configure(text="100% hoàn thành"))
        
        # Cập nhật lại UI trạng thái các model
        self.check_models_status_task()
        
        if success_count == len(repos):
            self.log("Chúc mừng! Đã tải đầy đủ tất cả model cần thiết về ổ E.")
            self.root.after(0, lambda: messagebox.showinfo("Thành công", "Đã tải đầy đủ tất cả model về ổ E!"))
        else:
            self.log("Một số model chưa được tải thành công. Vui lòng thử lại.", "WARNING")
            self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", "Có lỗi xảy ra khi tải một số model. Xem log để biết chi tiết."))

    def start_load_model(self):
        global model_loading
        if model_loading:
            return
            
        # Kiểm tra xem đã tải model chính chưa
        self.check_models_status_task()
        if self.status_omnivoice_val.get() != "Đã tải xong" or self.status_tokenizer_val.get() != "Đã tải xong":
            messagebox.showerror("Lỗi", "Vui lòng tải đầy đủ các model cần thiết (OmniVoice & Tokenizer) về ổ E trước khi nạp!")
            return
            
        model_loading = True
        self.btn_load_model.configure(state="disabled")
        self.lbl_load_status.configure(text="Đang nạp mô hình vào RAM/VRAM... Vui lòng đợi.", foreground="#FFB300")
        
        # Bắt đầu thanh chạy tiến trình
        self.load_progress_val.set(0.0)
        self.load_progress_bar.configure(mode="indeterminate")
        self.load_progress_bar.start(10)
        
        self.log("Bắt đầu nạp mô hình OmniVoice vào bộ nhớ máy...")
        
        threading.Thread(target=self.load_model_worker, daemon=True).start()

    def load_model_worker(self):
        global loaded_model, model_loading
        import torch
        from omnivoice.models.omnivoice import OmniVoice
        
        device_selection = self.device_var.get()
        if device_selection == "CUDA (NVIDIA GPU)":
            device = "cuda"
        elif device_selection == "CPU":
            device = "cpu"
        else:
            # Tự động chọn
            device = "cuda" if torch.cuda.is_available() else "cpu"
            
        # Kiểm tra xem có hỗ trợ ASR không
        load_asr = (self.status_asr_val.get() == "Đã tải xong")
        
        try:
            self.log(f"Đang nạp model OmniVoice lên thiết bị: {device.upper()}...")
            
            # Khởi tạo mô hình
            loaded_model = OmniVoice.from_pretrained(
                MODEL_OMNIVOICE,
                device_map=device,
                dtype=torch.float16 if device == "cuda" else torch.float32,
                load_asr=load_asr,
                asr_model_name=MODEL_ASR if load_asr else None
            )
            
            self.log(f"Nạp mô hình thành công! Thiết bị hiện tại: {device.upper()}")
            
            # Cập nhật UI
            status_txt = f"Mô hình: Đã sẵn sàng trên {device.upper()}."
            if load_asr:
                status_txt += " (Hỗ trợ Tự động nhận diện ASR)"
            else:
                status_txt += " (Không có ASR - Nhập text mẫu thủ công)"
                
            self.root.after(0, lambda: self.lbl_load_status.configure(text=status_txt, foreground="#00E676"))
            # Vô hiệu hóa nút nạp mô hình khi đã nạp thành công
            self.root.after(0, lambda: self.btn_load_model.configure(state="disabled"))
            
            # Đặt thanh tiến trình hoàn thành 100%
            self.root.after(0, self.load_progress_bar.stop)
            self.root.after(0, lambda: self.load_progress_bar.configure(mode="determinate"))
            self.root.after(0, lambda: self.load_progress_val.set(100.0))
            
        except Exception as e:
            self.log(f"Lỗi khi nạp mô hình: {e}", "ERROR")
            self.root.after(0, lambda: self.lbl_load_status.configure(text="Lỗi: Không thể nạp mô hình.", foreground="#FF3366"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi nạp Model", f"Không thể nạp mô hình vào bộ nhớ:\n{e}"))
            # Bật lại nút nạp để người dùng thử lại
            self.root.after(0, lambda: self.btn_load_model.configure(state="normal"))
            
            # Reset thanh tiến trình về 0%
            self.root.after(0, self.load_progress_bar.stop)
            self.root.after(0, lambda: self.load_progress_bar.configure(mode="determinate"))
            self.root.after(0, lambda: self.load_progress_val.set(0.0))
            
        finally:
            model_loading = False

    # =====================================================================
    # Chức năng Voice Clone (Nhái giọng)
    # =====================================================================
    def select_ref_audio(self):
        file_path = filedialog.askopenfilename(
            title="Chọn file âm thanh mẫu",
            filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac *.ogg")]
        )
        if file_path:
            # Chuyển đổi dấu gạch chéo ngược trên Windows
            file_path = file_path.replace("/", "\\")
            self.ref_audio_path.set(file_path)
            self.ent_ref_path.delete(0, tk.END)
            self.ent_ref_path.insert(0, file_path)
            self.log(f"Đã chọn file âm thanh mẫu: {file_path}")

    def play_ref_audio(self):
        filepath = self.ref_audio_path.get()
        if not filepath or not os.path.exists(filepath):
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file âm thanh mẫu trước!")
            return
        self.play_audio_file(filepath)

    def insert_expression_tag(self, text_widget, tag):
        try:
            cursor_index = text_widget.index(tk.INSERT)
            text_widget.insert(cursor_index, f" {tag} ")
            text_widget.focus()
        except Exception:
            pass

    # load_saved_voices đã được tập trung quản lý tự động nạp từ GitHub Repo bên dưới

    def on_saved_voice_selected(self, event):
        name = self.saved_voices_combo.get()
        if name == "-- Chọn giọng đọc đã lưu --":
            return
        supported_exts = (".wav", ".mp3", ".m4a", ".flac", ".ogg")
        matched_file = None
        for ext in supported_exts:
            test_path = os.path.join(self.saved_voices_dir, f"{name}{ext}")
            if os.path.exists(test_path):
                matched_file = test_path
                break
        if matched_file:
            matched_file = matched_file.replace("/", "\\")
            self.ref_audio_path.set(matched_file)
            self.ent_ref_path.delete(0, tk.END)
            self.ent_ref_path.insert(0, matched_file)
            txt_path = os.path.join(self.saved_voices_dir, f"{name}.txt")
            self.ent_ref_text.delete(0, tk.END)
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, "r", encoding="utf-8") as f:
                        ref_text = f.read().strip()
                        self.ent_ref_text.insert(0, ref_text)
                except Exception as e:
                    self.log(f"Lỗi đọc văn bản mẫu của giọng đã lưu: {e}", "WARNING")
            self.log(f"Đã chọn giọng lưu trữ: {name}")

    def save_current_voice(self):
        ref_audio = self.ref_audio_path.get()
        voice_name = self.ent_save_voice_name.get().strip()
        ref_text = self.ent_ref_text.get().strip()
        if not ref_audio or not os.path.exists(ref_audio):
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file âm thanh mẫu trước khi lưu!")
            return
        if not voice_name:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập tên giọng muốn lưu!")
            return
        import re
        voice_name = re.sub(r'[\\/*?:"<>|]', "", voice_name)
        if not voice_name:
            messagebox.showwarning("Cảnh báo", "Tên giọng không hợp lệ!")
            return
        _, ext = os.path.splitext(ref_audio)
        dest_audio_path = os.path.join(self.saved_voices_dir, f"{voice_name}{ext}")
        dest_txt_path = os.path.join(self.saved_voices_dir, f"{voice_name}.txt")
        try:
            import shutil
            shutil.copy2(ref_audio, dest_audio_path)
            if ref_text:
                with open(dest_txt_path, "w", encoding="utf-8") as f:
                    f.write(ref_text)
            elif os.path.exists(dest_txt_path):
                os.remove(dest_txt_path)
            self.log(f"Đã lưu giọng đọc '{voice_name}' thành công.")
            messagebox.showinfo("Thành công", f"Đã lưu giọng đọc '{voice_name}' thành công!")
            self.load_saved_voices()
            self.ent_save_voice_name.delete(0, tk.END)
        except Exception as e:
            self.log(f"Lỗi khi lưu giọng đọc: {e}", "ERROR")
            messagebox.showerror("Lỗi", f"Không thể lưu giọng đọc:\n{e}")


    # =====================================================================
    # Chức năng Cỗ máy tạo âm thanh (Audio Generator Engine)
    # =====================================================================
    def import_txt_file(self):
        file_path = filedialog.askopenfilename(
            title="Chọn file văn bản TXT",
            filetypes=[("Text files", "*.txt")]
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.txt_engine_input.delete("1.0", tk.END)
                self.txt_engine_input.insert(tk.END, content)
                self.imported_txt_name = os.path.splitext(os.path.basename(file_path))[0]
                self.log(f"Đã import file văn bản: {file_path}")
            except Exception as e:
                self.log(f"Lỗi đọc file TXT: {e}", "ERROR")
                messagebox.showerror("Lỗi", f"Không thể đọc file TXT:\n{e}")

    def split_text_to_chunks(self):
        text = self.txt_engine_input.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập văn bản cần chia đoạn!")
            return
            
        mode = self.chunk_mode_var.get()
        chunks = []
        
        if mode == "line":
            chunks = [line.strip() for line in text.split("\n") if line.strip()]
        elif mode == "sentence":
            import re
            raw_chunks = re.split(r'(?<=[.!?。！？])\s+|\n', text)
            chunks = [c.strip() for c in raw_chunks if c.strip()]
        else:
            # Theo số ký tự lùi tìm dấu câu
            try:
                max_chars = int(self.chunk_len_var.get())
                if max_chars < 10:
                    max_chars = 500
            except:
                max_chars = 500
                
            start = 0
            length = len(text)
            punctuation = set(['.', '?', '!', '\n', ';'])
            sub_punctuation = set([',', ':', '-'])
            
            while start < length:
                if start + max_chars >= length:
                    chunk = text[start:].strip()
                    if chunk:
                        chunks.append(chunk)
                    break
                    
                end = start + max_chars
                found_idx = -1
                # Giới hạn lùi tối đa 35% độ dài để không chia quá nhỏ
                min_back = int(max_chars * 0.65)
                
                # 1. Tìm dấu câu chính (. ? ! \n ;)
                for i in range(end, start + min_back, -1):
                    if text[i] in punctuation:
                        found_idx = i + 1
                        break
                        
                # 2. Tìm dấu câu phụ (, : -)
                if found_idx == -1:
                    for i in range(end, start + min_back, -1):
                        if text[i] in sub_punctuation:
                            found_idx = i + 1
                            break
                            
                # 3. Tìm khoảng trắng
                if found_idx == -1:
                    for i in range(end, start + min_back, -1):
                        if text[i] in [' ', '\t']:
                            found_idx = i + 1
                            break
                            
                # 4. Cắt cứng tại giới hạn tối đa
                if found_idx == -1:
                    found_idx = end
                    
                chunk = text[start:found_idx].strip()
                if chunk:
                    chunks.append(chunk)
                start = found_idx
                
        # Xóa Treeview cũ
        for item in self.tree_chunks.get_children():
            self.tree_chunks.delete(item)
            
        self.chunks_data = []
        for i, chunk in enumerate(chunks, 1):
            item_id = self.tree_chunks.insert("", tk.END, values=(i, chunk, "Chưa tạo", "-", ""))
            self.chunks_data.append({
                'item_id': item_id,
                'index': i,
                'text': chunk,
                'status': 'Chưa tạo',
                'file_path': None,
                'takes': [],
                'selected_take_index': -1
            })
            
        self.log(f"Đã chia văn bản thành {len(chunks)} đoạn thành công.")

    def on_engine_voice_selected(self, event):
        name = self.engine_saved_voices_combo.get()
        if name == "-- Chọn giọng đọc đã lưu --":
            self.engine_ref_audio.set("")
            self.engine_ref_text.set("")
            self.lbl_engine_voice_info.configure(text="Chưa chọn giọng tham chiếu.", foreground="#A0A0AA")
            return
            
        matched_file = None
        if hasattr(self, 'voice_name_to_path_map') and name in self.voice_name_to_path_map:
            matched_file = self.voice_name_to_path_map[name]
        else:
            supported_exts = (".wav", ".mp3", ".m4a", ".flac", ".ogg")
            for ext in supported_exts:
                test_path = os.path.join(self.saved_voices_dir, f"{name}{ext}")
                if os.path.exists(test_path):
                    matched_file = test_path
                    break
                
        if matched_file and os.path.exists(matched_file):
            matched_file = matched_file.replace("/", "\\")
            self.engine_ref_audio.set(matched_file)
            
            txt_path = os.path.splitext(matched_file)[0] + ".txt"
            ref_text = ""
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, "r", encoding="utf-8") as f:
                        ref_text = f.read().strip()
                except Exception:
                    pass
            self.engine_ref_text.set(ref_text)
            
            info_txt = f"🎯 ĐÃ CHỌN GIỌNG: {name} ({os.path.basename(matched_file)})"
            if ref_text:
                info_txt += f" | Text: \"{ref_text[:20]}...\""
            self.lbl_engine_voice_info.configure(text=info_txt, foreground="#00E676")
            self.log(f"Đã chọn giọng tham chiếu cho Engine thành công: {name}")

    def select_engine_export_path(self):
        file_path = filedialog.asksaveasfilename(
            title="Chọn nơi lưu file âm thanh hoàn chỉnh",
            defaultextension=".wav",
            filetypes=[("WAV files", "*.wav")]
        )
        if file_path:
            file_path = file_path.replace("/", "\\")
            self.engine_dest_path.set(file_path)
            self.log(f"Đã chọn đường dẫn lưu file xuất bản: {file_path}")

    def generate_selected_chunk(self):
        selected_item = self.tree_chunks.focus()
        if not selected_item:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một đoạn trong danh sách để tạo!")
            return
            
        chunk_info = None
        for c in self.chunks_data:
            if c['item_id'] == selected_item:
                chunk_info = c
                break
                
        if not chunk_info:
            return
            
        global loaded_model, model_generating, model_loading
        if "Cloud API" not in self.run_mode_var.get():
            if loaded_model is None:
                if model_loading:
                    messagebox.showinfo("Thông báo", "Đang nạp mô hình trong nền, vui lòng đợi một chút rồi bấm lại!")
                    return
                self.log("Mô hình chưa được nạp. Đang tự động nạp mô hình trước...")
                self.start_load_model()
                return
            
        if model_generating:
            messagebox.showwarning("Cảnh báo", "Mô hình đang bận xử lý tác vụ khác, vui lòng đợi!")
            return
            
        # Lấy giá trị thô trên Main Thread để đảm bảo an toàn cho giao diện Tkinter
        raw_ref_audio = self.engine_ref_audio.get()
        raw_ref_text = self.engine_ref_text.get()
        raw_pitch = self.engine_pitch_var.get()
        raw_style = self.engine_style_var.get()
        raw_voice_combo = self.engine_saved_voices_combo.get()

        model_generating = True
        self.tree_chunks.item(chunk_info['item_id'], values=(chunk_info['index'], chunk_info['text'], "Đang xử lý...", ""))
        
        threading.Thread(
            target=self.generate_chunk_worker, 
            args=(chunk_info, raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo), 
            daemon=True
        ).start()

    def _resolve_engine_parameters(self, raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo):
        ref_audio = raw_ref_audio
        ref_text = raw_ref_text.strip()
        
        # 1. Nếu chưa chọn giọng tham chiếu, tự động lấy giọng Thanh Ngọc làm mặc định để làm prompt ổn định
        if not ref_audio or not os.path.exists(ref_audio):
            default_ref = os.path.join(self.saved_voices_dir, "Thanh Ngọc - 11labs.mp3")
            if os.path.exists(default_ref):
                ref_audio = default_ref
                txt_path = os.path.join(self.saved_voices_dir, "Thanh Ngọc - 11labs.txt")
                if os.path.exists(txt_path):
                    try:
                        with open(txt_path, "r", encoding="utf-8") as f:
                            ref_text = f.read().strip()
                    except Exception:
                        ref_text = ""
                else:
                    ref_text = ""
            else:
                ref_audio = None
                ref_text = None

        # 2. Tự động chạy ASR nhận dạng giọng mẫu nếu ref_text trống
        if ref_audio and not ref_text:
            txt_path = os.path.splitext(ref_audio)[0] + ".txt"
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, "r", encoding="utf-8") as f:
                        ref_text = f.read().strip()
                except Exception:
                    pass
            if not ref_text and "Cloud API" not in self.run_mode_var.get():
                self.log(f"Đang tự động nhận dạng văn bản cho giọng mẫu: {os.path.basename(ref_audio)} (ASR)...")
                try:
                    if loaded_model is not None:
                        if loaded_model._asr_pipe is None:
                            loaded_model.load_asr_model()
                        ref_text = loaded_model.transcribe(ref_audio)
                        self.log(f"Đã nhận dạng thành công: \"{ref_text}\"")
                        # Lưu lại file txt để tăng tốc cho lần sau
                        with open(txt_path, "w", encoding="utf-8") as f:
                            f.write(ref_text)
                    else:
                        ref_text = None
                except Exception as e:
                    self.log(f"Lỗi nhận dạng ASR cho giọng mẫu: {e}", "WARNING")
                    ref_text = None

        # Đảm bảo ref_text rỗng được chuẩn hóa về None
        if not ref_text:
            ref_text = None

        # 3. Giải quyết Pitch & Style
        instruct_parts = []
        if raw_pitch != "Auto":
            instruct_parts.append(raw_pitch.split(" / ")[0].lower())
        if raw_style != "Auto":
            instruct_parts.append(raw_style.split(" / ")[0].lower())
        instruct_str = ", ".join(instruct_parts) if instruct_parts else None

        # 4. Tránh xung đột chế độ: Nếu người dùng chọn giọng lưu trữ cụ thể của họ (không phải mặc định),
        # thì ta bắt buộc phải đặt instruct_str = None để giữ nguyên ngữ điệu mượt mà của giọng mẫu.
        is_custom_voice = (raw_voice_combo != "-- Chọn giọng đọc đã lưu --")
        if is_custom_voice:
            instruct_str = None

        return ref_audio, ref_text, instruct_str

    def update_expression_tags_ui(self):
        if not hasattr(self, 'f_express') or not self.f_express:
            return
            
        # Xóa toàn bộ nút cũ
        for widget in self.f_express.winfo_children():
            widget.destroy()
            
        ttk.Label(self.f_express, text="Nhấn nhá biểu cảm:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
        selected_engine = self.selected_ai_engine_var.get() if hasattr(self, 'selected_ai_engine_var') else ""
        
        if "VieNeu-TTS" in selected_engine:
            expressions = [
                ("Cười 😊", "[cười]"),
                ("Thở dài 😮‍💨", "[thở dài]"),
                ("Hắng giọng 🗣️", "[hắng giọng]"),
                ("Thì thầm 🤫", "[thì thầm]"),
                ("Ngập ngừng 🤐", "[ngập ngừng]"),
                ("Nói chậm 🐢", "[nói chậm]"),
                ("Nhấn giọng 💥", "[nhấn giọng]")
            ]
        else:
            expressions = [
                ("Cười 😊", "[laughter]"),
                ("Thở dài 😮‍💨", "[sigh]"),
                ("Ngạc nhiên 😲", "[surprise-ah]"),
                ("Ồ! 😲", "[surprise-oh]"),
                ("Hỏi (En?) ❓", "[question-en]"),
                ("Bất bình 😠", "[dissatisfaction-hnn]")
            ]
            
        for name, tag in expressions:
            btn = ttk.Button(self.f_express, text=name, width=12,
                             command=lambda t=tag: self.insert_emotion_tag(t))
            btn.pack(side=tk.LEFT, padx=2)

    def insert_emotion_tag(self, tag):
        try:
            if hasattr(self, 'txt_engine_input') and self.txt_engine_input:
                self.txt_engine_input.insert(tk.INSERT, f" {tag} ")
                self.txt_engine_input.focus()
            elif hasattr(self, 'txt_input_script') and self.txt_input_script:
                self.txt_input_script.insert(tk.INSERT, f" {tag} ")
                self.txt_input_script.focus()
        except Exception:
            pass

    REMOTE_VOICES_REPO = "danghai-245/voice_11labs"  # Chỉ nạp Voice Mẫu Online từ GitHub Repo chính thức này

    def parse_voice_info(self, voice_filename, full_path=""):
        base_name = os.path.splitext(voice_filename)[0]
        parts = [p.strip() for p in base_name.split("-") if p.strip()]
        
        # Bóc tách thông tin đếm ngược từ cuối tên file:
        # ... - [Voice ID] - [Ngôn ngữ] - [Giới tính] - [Độ tuổi] - [Chất lượng / Thể loại]
        category = parts[-1] if len(parts) >= 1 else "Tất cả"
        age = parts[-2] if len(parts) >= 2 else "Tất cả"
        gender = parts[-3] if len(parts) >= 3 else "Tất cả"
        lang = parts[-4] if len(parts) >= 4 else "Tất cả"
        voice_id = parts[-5] if len(parts) >= 5 else ""
        
        # Chỉ lấy Tên giọng đọc sạch (loại bỏ Voice ID và 4 trường thông tin đằng sau)
        if len(parts) > 5:
            display_name = " - ".join(parts[:-5])
        elif len(parts) > 4:
            display_name = " - ".join(parts[:-4])
        elif len(parts) >= 1:
            display_name = parts[0]
        else:
            display_name = base_name
            
        return {
            "raw": base_name,
            "name": display_name,
            "voice_id": voice_id,
            "lang": lang,
            "gender": gender,
            "age": age,
            "category": category,
            "full_path": full_path
        }

    def search_voice_by_id(self):
        if not hasattr(self, 'voice_id_search_var'):
            return
        search_id = self.voice_id_search_var.get().strip().lower()
        if not search_id or not hasattr(self, 'all_voice_metadata'):
            return
            
        matched_voice = None
        for v in self.all_voice_metadata:
            v_id = v.get("voice_id", "").lower()
            v_raw = v.get("raw", "").lower()
            if search_id == v_id or (len(search_id) >= 3 and (search_id in v_id or search_id in v_raw)):
                matched_voice = v
                break
                
        if matched_voice and hasattr(self, 'engine_saved_voices_combo'):
            name = matched_voice['name']
            if name in self.engine_saved_voices_combo['values']:
                self.engine_saved_voices_combo.set(name)
                self.on_engine_voice_selected(None)

    def load_saved_voices(self):
        if not os.path.exists(self.saved_voices_dir):
            os.makedirs(self.saved_voices_dir, exist_ok=True)
            
        supported_exts = (".wav", ".mp3", ".m4a", ".flac", ".ogg")
        repo_name = getattr(self, 'REMOTE_VOICES_REPO', '').strip()
        
        if repo_name and "/" in repo_name:
            def sync_remote_voices():
                try:
                    import requests
                    from concurrent.futures import ThreadPoolExecutor
                    
                    if hasattr(self, 'lbl_engine_voice_info') and self.lbl_engine_voice_info:
                        self.root.after(0, lambda: self.lbl_engine_voice_info.configure(
                            text="🔄 Đang đồng bộ giọng đọc VIP từ GitHub Online...", foreground="#FFB300"))
                    
                    # 1. Thử lấy danh sách file từ GitHub Contents API
                    items = []
                    api_url = f"https://api.github.com/repos/{repo_name}/contents/"
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                        'Accept': 'application/vnd.github.v3+json'
                    }
                    
                    try:
                        resp = requests.get(api_url, headers=headers, timeout=10)
                        if resp.status_code == 200:
                            items = resp.json()
                    except Exception:
                        pass

                    # Fallback nếu API bị Rate Limit hoặc lỗi: lấy từ Git Tree main
                    if not items:
                        try:
                            tree_url = f"https://api.github.com/repos/{repo_name}/git/trees/main?recursive=1"
                            resp_tree = requests.get(tree_url, headers=headers, timeout=10)
                            if resp_tree.status_code == 200:
                                tree_data = resp_tree.json().get('tree', [])
                                for t in tree_data:
                                    path_str = t.get('path', '')
                                    if path_str.lower().endswith(supported_exts):
                                        raw_url = f"https://raw.githubusercontent.com/{repo_name}/main/{path_str}"
                                        items.append({'name': os.path.basename(path_str), 'download_url': raw_url})
                        except Exception:
                            pass
                    
                    if items and isinstance(items, list):
                        remote_file_names = set()
                        download_tasks = []
                        for item in items:
                            f_name = item.get('name', '')
                            download_url = item.get('download_url', '')
                            if download_url and f_name.lower().endswith(supported_exts):
                                remote_file_names.add(f_name)
                                dest_p = os.path.join(self.saved_voices_dir, f_name)
                                if not os.path.exists(dest_p):
                                    download_tasks.append((download_url, dest_p))
                        
                        # Cập nhật UI ngay lập tức với các file local sẵn có
                        if hasattr(self, 'root') and self.root:
                            self.root.after(0, self.update_voice_filter_combos)

                        # Tải song song 20 luồng siêu tốc và cập nhật UI liên tục
                        if download_tasks:
                            completed_count = [0]
                            def download_file_worker(task):
                                d_url, d_path = task
                                try:
                                    r = requests.get(d_url, timeout=20)
                                    if r.status_code == 200:
                                        with open(d_path, "wb") as f_out:
                                            f_out.write(r.content)
                                        completed_count[0] += 1
                                        # Cập nhật UI nhảy realtime sau mỗi 5 file tải xong
                                        if completed_count[0] % 5 == 0 or completed_count[0] == len(download_tasks):
                                            if hasattr(self, 'root') and self.root:
                                                self.root.after(0, self.update_voice_filter_combos)
                                except Exception as err:
                                    print(f"Lỗi tải file {d_path}: {err}")

                            with ThreadPoolExecutor(max_workers=20) as executor:
                                list(executor.map(download_file_worker, download_tasks))

                        # Loại bỏ các voice local cũ không thuộc Repo Online
                        if remote_file_names:
                            for local_f in os.listdir(self.saved_voices_dir):
                                if local_f.lower().endswith(supported_exts) and local_f not in remote_file_names:
                                    try:
                                        os.remove(os.path.join(self.saved_voices_dir, local_f))
                                    except Exception:
                                        pass

                        # Cập nhật chốt bộ lọc trên luồng chính UI lần cuối
                        if hasattr(self, 'root') and self.root:
                            self.root.after(0, self.update_voice_filter_combos)
                        else:
                            self.update_voice_filter_combos()
                    else:
                        print(f"⚠️ Không lấy được danh sách file từ Repo {repo_name}")
                except Exception as e:
                    print(f"❌ Lỗi đồng bộ Voice từ Repo '{repo_name}': {e}")
                    if hasattr(self, 'root') and self.root:
                        self.root.after(0, self.update_voice_filter_combos)

            import threading
            threading.Thread(target=sync_remote_voices, daemon=True).start()

        self.update_voice_filter_combos()

    def update_voice_filter_combos(self):
        supported_exts = (".wav", ".mp3", ".m4a", ".flac", ".ogg")
        if not os.path.exists(self.saved_voices_dir):
            return
        files = [f for f in os.listdir(self.saved_voices_dir) if f.lower().endswith(supported_exts)]
        
        self.all_voice_metadata = []
        self.voice_name_to_path_map = {}
        
        for f in files:
            full_p = os.path.join(self.saved_voices_dir, f).replace("/", "\\")
            meta = self.parse_voice_info(f, full_p)
            self.all_voice_metadata.append(meta)
            self.voice_name_to_path_map[meta['name']] = full_p
            self.voice_name_to_path_map[meta['raw']] = full_p
        
        LANG_MAP_PY = {
            "en": "Tiếng Anh (English)", "english": "Tiếng Anh (English)",
            "vi": "Tiếng Việt (Vietnamese)", "vietnamese": "Tiếng Việt (Vietnamese)",
            "zh": "Tiếng Trung (Chinese)", "chinese": "Tiếng Trung (Chinese)",
            "ja": "Tiếng Nhật (Japanese)", "japanese": "Tiếng Nhật (Japanese)",
            "ko": "Tiếng Hàn (Korean)", "korean": "Tiếng Hàn (Korean)",
            "fr": "Tiếng Pháp (French)", "french": "Tiếng Pháp (French)",
            "de": "Tiếng Đức (German)", "german": "Tiếng Đức (German)",
            "es": "Tiếng Tây Ban Nha (Spanish)", "spanish": "Tiếng Tây Ban Nha (Spanish)",
            "ru": "Tiếng Nga (Russian)", "russian": "Tiếng Nga (Russian)",
            "pt": "Tiếng Bồ Đào Nha (Portuguese)", "portuguese": "Tiếng Bồ Đào Nha (Portuguese)",
            "it": "Tiếng Ý (Italian)", "italian": "Tiếng Ý (Italian)",
            "hi": "Tiếng Ấn Độ (Hindi)", "hindi": "Tiếng Ấn Độ (Hindi)",
            "ar": "Tiếng Ả Rập (Arabic)", "arabic": "Tiếng Ả Rập (Arabic)",
            "id": "Tiếng Indonesia", "indonesian": "Tiếng Indonesia",
            "th": "Tiếng Thái (Thai)", "thai": "Tiếng Thái (Thai)",
            "tr": "Tiếng Thổ Nhĩ Kỳ (Turkish)", "turkish": "Tiếng Thổ Nhĩ Kỳ (Turkish)",
            "pl": "Tiếng Ba Lan (Polish)", "polish": "Tiếng Ba Lan (Polish)",
            "nl": "Tiếng Hà Lan (Dutch)", "dutch": "Tiếng Hà Lan (Dutch)"
        }
        
        def format_lang_py(code):
            if not code: return "Khác"
            return LANG_MAP_PY.get(code.strip().lower(), code)

        raw_langs = set(v['lang'] for v in self.all_voice_metadata if v['lang'])
        full_langs = sorted(list(set(format_lang_py(l) for l in raw_langs)))
        
        # Ưu tiên Tiếng Anh và Tiếng Việt lên đầu danh sách
        def sort_lang_priority(item):
            if "Tiếng Anh" in item:
                return (0, item)
            elif "Tiếng Việt" in item:
                return (1, item)
            return (2, item)
            
        full_langs.sort(key=sort_lang_priority)

        genders = sorted(list(set(v['gender'] for v in self.all_voice_metadata if v['gender'])))
        categories = sorted(list(set(v['category'] for v in self.all_voice_metadata if v['category'])))
        
        if hasattr(self, 'combo_filter_lang'):
            self.combo_filter_lang['values'] = ["Ngôn ngữ: Tất cả"] + full_langs
            if not self.filter_lang_var.get() or self.filter_lang_var.get() not in self.combo_filter_lang['values']:
                self.filter_lang_var.set("Ngôn ngữ: Tất cả")
                
        if hasattr(self, 'combo_filter_gender'):
            self.combo_filter_gender['values'] = ["Giới tính: Tất cả"] + genders
            if not self.filter_gender_var.get() or self.filter_gender_var.get() not in self.combo_filter_gender['values']:
                self.filter_gender_var.set("Giới tính: Tất cả")
                
        if hasattr(self, 'combo_filter_cat'):
            self.combo_filter_cat['values'] = ["Thể loại: Tất cả"] + categories
            if not self.filter_cat_var.get() or self.filter_cat_var.get() not in self.combo_filter_cat['values']:
                self.filter_cat_var.set("Thể loại: Tất cả")
            
        self.apply_voice_filters()

    def apply_voice_filters(self, event=None):
        LANG_MAP_PY = {
            "en": "Tiếng Anh (English)", "english": "Tiếng Anh (English)",
            "vi": "Tiếng Việt (Vietnamese)", "vietnamese": "Tiếng Việt (Vietnamese)",
            "zh": "Tiếng Trung (Chinese)", "chinese": "Tiếng Trung (Chinese)",
            "ja": "Tiếng Nhật (Japanese)", "japanese": "Tiếng Nhật (Japanese)",
            "ko": "Tiếng Hàn (Korean)", "korean": "Tiếng Hàn (Korean)",
            "fr": "Tiếng Pháp (French)", "french": "Tiếng Pháp (French)",
            "de": "Tiếng Đức (German)", "german": "Tiếng Đức (German)",
            "es": "Tiếng Tây Ban Nha (Spanish)", "spanish": "Tiếng Tây Ban Nha (Spanish)",
            "ru": "Tiếng Nga (Russian)", "russian": "Tiếng Nga (Russian)",
            "pt": "Tiếng Bồ Đào Nha (Portuguese)", "portuguese": "Tiếng Bồ Đào Nha (Portuguese)",
            "it": "Tiếng Ý (Italian)", "italian": "Tiếng Ý (Italian)",
            "hi": "Tiếng Ấn Độ (Hindi)", "hindi": "Tiếng Ấn Độ (Hindi)",
            "ar": "Tiếng Ả Rập (Arabic)", "arabic": "Tiếng Ả Rập (Arabic)",
            "id": "Tiếng Indonesia", "indonesian": "Tiếng Indonesia",
            "th": "Tiếng Thái (Thai)", "thai": "Tiếng Thái (Thai)",
            "tr": "Tiếng Thổ Nhĩ Kỳ (Turkish)", "turkish": "Tiếng Thổ Nhĩ Kỳ (Turkish)",
            "pl": "Tiếng Ba Lan (Polish)", "polish": "Tiếng Ba Lan (Polish)",
            "nl": "Tiếng Hà Lan (Dutch)", "dutch": "Tiếng Hà Lan (Dutch)"
        }
        def format_lang_py(code):
            if not code: return "Khác"
            return LANG_MAP_PY.get(code.strip().lower(), code)

        if not hasattr(self, 'all_voice_metadata') or not self.all_voice_metadata:
            supported_exts = (".wav", ".mp3", ".m4a", ".flac", ".ogg")
            if os.path.exists(self.saved_voices_dir):
                files = [f for f in os.listdir(self.saved_voices_dir) if f.lower().endswith(supported_exts)]
                self.all_voice_metadata = [self.parse_voice_info(f, os.path.join(self.saved_voices_dir, f)) for f in files]
            else:
                self.all_voice_metadata = []

        selected_lang = self.filter_lang_var.get() if hasattr(self, 'filter_lang_var') else "Ngôn ngữ: Tất cả"
        selected_gender = self.filter_gender_var.get() if hasattr(self, 'filter_gender_var') else "Giới tính: Tất cả"
        selected_cat = self.filter_cat_var.get() if hasattr(self, 'filter_cat_var') else "Thể loại: Tất cả"

        filtered_voices = []
        for v in self.all_voice_metadata:
            v_full_lang = format_lang_py(v['lang'])
            if selected_lang != "Ngôn ngữ: Tất cả" and v_full_lang != selected_lang and v['lang'] != selected_lang:
                continue
            if selected_gender != "Giới tính: Tất cả" and v['gender'] != selected_gender:
                continue
            if selected_cat != "Thể loại: Tất cả" and v['category'] != selected_cat:
                continue
            filtered_voices.append(v['name'])

        filtered_voices.sort()
        
        if hasattr(self, 'saved_voices_combo'):
            self.saved_voices_combo['values'] = ["-- Chọn giọng đọc đã lưu --"] + filtered_voices
            if filtered_voices:
                self.saved_voices_combo.set(filtered_voices[0])
            else:
                self.saved_voices_combo.set("-- Chọn giọng đọc đã lưu --")
            
        if hasattr(self, 'engine_saved_voices_combo'):
            self.engine_saved_voices_combo['values'] = ["-- Chọn giọng đọc đã lưu --"] + filtered_voices
            if filtered_voices:
                self.engine_saved_voices_combo.set(filtered_voices[0])
                self.on_engine_voice_selected(None)
            else:
                self.engine_saved_voices_combo.set("-- Chọn giọng đọc đã lưu --")
                self.on_engine_voice_selected(None)

    HARDCODED_MODAL_SERVERS = []  # Đã tắt hoàn toàn link dán cứng, bắt buộc nạp 100% từ Gist Admin

    def _call_cloud_api(self, text, language, ref_audio, ref_text, instruct_str, speed, num_step, cfg_scale=2.0, temperature=5.0, pad_duration=0.0, fade_duration=0.0, chunk_index=None, progress_cb=None):
        import shutil, re, urllib.request, json
        selected_engine = self.selected_ai_engine_var.get() if hasattr(self, 'selected_ai_engine_var') else ""
        
        # 1. Thu thập danh sách URL Serverless (100% bắt buộc lấy từ Gist Admin Online)
        url_list = []
        
        # Tự động tải từ Máy chủ Admin (Remote Config URL)
        remote_url = getattr(self, 'REMOTE_CONFIG_URL', '').strip()
        if not remote_url:
            remote_url = "https://jdhjimqktyiwffueaksh.supabase.co/storage/v1/object/public/hth_voice/server_config.json"
        if remote_url:
            try:
                req = urllib.request.Request(remote_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = resp.read().decode('utf-8')
                    try:
                        remote_json = json.loads(data)
                        if isinstance(remote_json, dict):
                            remote_list = remote_json.get("gpu_urls", [])
                        else:
                            remote_list = remote_json
                    except Exception:
                        remote_list = [line.strip() for line in data.splitlines() if 'https://' in line]
                    
                    if isinstance(remote_list, list):
                        for u in remote_list:
                            if u and isinstance(u, str) and u.strip():
                                u_clean = u.strip().rstrip("/").replace("--vieneu-tts-serverless-vieneumodel-generate", "--omnivoice-tts-serverless-omnivoicemodel-generate")
                                if u_clean not in url_list:
                                    url_list.append(u_clean)
            except Exception as e:
                pass

        if not url_list:
            raw_urls = self.api_server_url_var.get().strip() if hasattr(self, 'api_server_url_var') else ""
            if raw_urls and "🔒" not in raw_urls:
                url_list = [u.strip().rstrip("/") for u in re.split(r'[,\n\r]+', raw_urls) if u.strip()]

        url_list = [u.replace("--vieneu-tts-serverless-vieneumodel-generate", "--omnivoice-tts-serverless-omnivoicemodel-generate") for u in url_list]

        if not url_list:
            url_list = ["https://hai319959--omnivoice-tts-serverless-omnivoicemodel-generate.modal.run"]
            
        MAX_RETRIES = 2
        last_error = None

        for u_idx, server_url in enumerate(url_list, 1):
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    if progress_cb:
                        progress_cb(10, 100)
                        
                    engine_label = "VieNeu-TTS 48kHz" if "VieNeu-TTS" in selected_engine else "OmniVoice"
                    # Log sạch không lộ URL hay thông tin Modal
                    self.log(f"Đang gửi yêu cầu sinh giọng nói [{engine_label}] tới Server #{u_idx}...")
                    
                    clean_text = text
                    cleaned = re.sub(r'\[.*?\]', '', clean_text).strip()
                    if cleaned:
                        clean_text = cleaned
                    else:
                        clean_text = text.strip() if (text and text.strip()) else "."

                    if "modal.run" in server_url:
                        api_endpoint = server_url
                        json_payload = {
                            "text": clean_text,
                            "speed": float(speed),
                            "ref_text": ref_text or ""
                        }
                        if ref_audio and os.path.exists(ref_audio):
                            try:
                                import base64
                                with open(ref_audio, "rb") as f_ref:
                                    b64_str = base64.b64encode(f_ref.read()).decode("utf-8")
                                    json_payload["ref_audio_base64"] = b64_str
                                    json_payload["ref_audio"] = b64_str
                            except Exception as e_b64:
                                print(f"Lỗi mã hóa ref_audio base64: {e_b64}")

                        res = requests.post(api_endpoint, json=json_payload, timeout=120)
                    else:
                        clean_text = text
                        extracted_instruct = instruct_str or ""
                        
                        tags_found = re.findall(r'\[(.*?)\]', clean_text)
                        if tags_found:
                            first_tag = tags_found[0].lower().strip()
                            tag_to_instruct = {
                                "laughter": "laughter", "cười": "laughter",
                                "sigh": "sigh", "thở dài": "sigh",
                                "surprise-ah": "surprised", "surprise-oh": "surprised",
                                "question-en": "questioning", "dissatisfaction-hnn": "dissatisfied",
                                "thì thầm": "whispering", "hắng giọng": "clearing throat",
                                "ngập ngừng": "hesitant", "nói chậm": "slow speed", "nhấn giọng": "emphasized"
                            }
                            if not extracted_instruct or extracted_instruct == "Auto":
                                extracted_instruct = tag_to_instruct.get(first_tag, first_tag)
                        
                        clean_text = re.sub(r'\[.*?\]', '', clean_text)
                        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                        
                        api_endpoint = f"{server_url}/api/generate"
                        data = {
                            "text": clean_text,
                            "language": language or "",
                            "speed": str(speed),
                            "num_step": str(num_step),
                            "instruct": extracted_instruct or "",
                            "ref_text": ref_text or "",
                            "pad_duration": str(pad_duration),
                            "fade_duration": str(fade_duration)
                        }
                        files = {}
                        if ref_audio and os.path.exists(ref_audio):
                            files["ref_audio"] = (os.path.basename(ref_audio), open(ref_audio, "rb"))

                        res = requests.post(api_endpoint, data=data, files=files, timeout=120)
                        if files.get("ref_audio"):
                            files["ref_audio"][1].close()

                    if res.status_code == 200:
                        temp_dir = os.path.join(output_dir, "temp_chunks")
                        os.makedirs(temp_dir, exist_ok=True)
                        suffix = f"_{chunk_index}" if chunk_index is not None else "_cloud"
                        filename = f"chunk_{time.strftime('%Y%m%d_%H%M%S')}{suffix}.wav"
                        filepath = os.path.join(temp_dir, filename)
                        
                        with open(filepath, "wb") as f_out:
                            f_out.write(res.content)
                            
                        if "VieNeu-TTS" in selected_engine:
                            try:
                                import soundfile as sf
                                import numpy as np
                                audio, sr = sf.read(filepath)
                                if len(audio) > 0:
                                    fade_len = int(sr * 0.03)
                                    if len(audio) > fade_len * 2:
                                        fade_in = np.linspace(0.0, 1.0, fade_len)
                                        fade_out = np.linspace(1.0, 0.0, fade_len)
                                        if audio.ndim == 1:
                                            audio[:fade_len] *= fade_in
                                            audio[-fade_len:] *= fade_out
                                        else:
                                            audio[:fade_len, :] *= fade_in[:, None]
                                            audio[-fade_len:, :] *= fade_out[:, None]
                                        sf.write(filepath, audio, sr)
                            except Exception as e_post:
                                self.log(f"Cảnh báo làm sạch âm thanh VieNeu: {e_post}", "DEBUG")
                            
                        if progress_cb:
                            progress_cb(100, 100)
                        return filepath
                    else:
                        raise Exception(f"HTTP Status {res.status_code}")
                except Exception as e:
                    last_error = e
                    self.log(f"Lỗi gửi request tới Server #{u_idx} - Lần thử {attempt}/{MAX_RETRIES}: {e}", "WARNING")
                    time.sleep(1)

            if len(url_list) > 1 and u_idx < len(url_list):
                self.log(f"⚠️ Server #{u_idx} không phản hồi hoặc quá tải. Tự động chuyển sang Server #{u_idx + 1}...", "WARNING")

        raise Exception(f"Tất cả {len(url_list)} Server Cloud đều thất bại hoặc quá tải. Lỗi cuối: {last_error}")


    def generate_chunk_worker(self, chunk_info, raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo):
        global loaded_model, model_generating
        import soundfile as sf
        import shutil
        
        lang = self.engine_lang_var.get()
        language = lang if lang != "Auto" else None
        speed = float(self.engine_speed_var.get())
        num_step = int(self.engine_steps_var.get())
        cfg_scale = float(self.engine_cfg_var.get())
        temperature = float(self.engine_temp_var.get())
        
        # Tiền xử lý chuẩn hóa chữ số/ký tự tiếng Việt
        try:
            from omnivoice.utils.vietnamese_normalizer import normalize_vietnamese_text
            norm_text = normalize_vietnamese_text(chunk_info['text'])
        except Exception as e:
            self.log(f"Không nạp được bộ chuẩn hóa tiếng Việt: {e}. Dùng văn bản gốc.", "WARNING")
            norm_text = chunk_info['text']
            
        # Giải quyết các tham số tham chiếu và phong cách an toàn trong luồng phụ
        ref_audio, ref_text, instruct_str = self._resolve_engine_parameters(
            raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo
        )
        
        self.log(f"Đoạn {chunk_info['index']} đang tạo voice")
        
        temp_dir = os.path.join(output_dir, "temp_chunks")
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            def progress_cb(step, total_steps):
                pct = int(step / total_steps * 100)
                # Đảm bảo hiển thị đúng số cột (5 cột)
                take_val = f"Take {chunk_info['selected_take_index'] + 1}/{len(chunk_info['takes'])}" if ('takes' in chunk_info and chunk_info['takes']) else "-"
                self.root.after(0, lambda: self.tree_chunks.item(
                    chunk_info['item_id'], 
                    values=(chunk_info['index'], chunk_info['text'], f"Đang xử lý ({pct}%)", take_val, "")
                ))

            # Xác định số thứ tự Take tiếp theo
            if 'takes' not in chunk_info:
                chunk_info['takes'] = []
                chunk_info['selected_take_index'] = -1
                
            take_num = len(chunk_info['takes']) + 1
            filename = f"chunk_{time.strftime('%Y%m%d_%H%M%S')}_{chunk_info['index']}_take{take_num}.wav"
            filepath = os.path.join(temp_dir, filename)

            pad_duration = float(self.engine_pad_var.get()) if hasattr(self, 'engine_pad_var') else 0.0
            fade_duration = float(self.engine_fade_var.get()) if hasattr(self, 'engine_fade_var') else 0.0

            if "Cloud API" in self.run_mode_var.get():
                temp_filepath = self._call_cloud_api(
                    text=norm_text,
                    language=language,
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                    instruct_str=instruct_str,
                    speed=speed,
                    num_step=num_step,
                    cfg_scale=cfg_scale,
                    temperature=temperature,
                    pad_duration=pad_duration,
                    fade_duration=fade_duration,
                    chunk_index=chunk_info['index'],
                    progress_cb=progress_cb
                )
                shutil.move(temp_filepath, filepath)
            else:
                import inspect
                sig = inspect.signature(loaded_model.generate)
                gen_kwargs = {
                    "text": norm_text,
                    "language": language,
                    "ref_audio": ref_audio,
                    "ref_text": ref_text,
                    "instruct": instruct_str,
                    "speed": speed,
                    "num_step": num_step,
                    "guidance_scale": cfg_scale,
                    "position_temperature": temperature,
                    "progress_callback": progress_cb
                }
                if "pad_duration" in sig.parameters:
                    gen_kwargs["pad_duration"] = pad_duration
                if "fade_duration" in sig.parameters:
                    gen_kwargs["fade_duration"] = fade_duration

                audio_data = loaded_model.generate(**gen_kwargs)
                sf.write(filepath, audio_data[0], loaded_model.sampling_rate)
            
            # Sao chép file ra outputs chính thức theo cấu hình tên người dùng
            dest_filename = f"{self.imported_txt_name or 'voice'}_{chunk_info['index']}.wav"
            dest_filepath = os.path.join(output_dir, dest_filename)
            try:
                shutil.copy2(filepath, dest_filepath)
                chunk_info['file_path'] = dest_filepath
                filepath = dest_filepath
            except Exception as ce:
                self.log(f"Lỗi khi copy file lẻ ra thư mục outputs: {ce}", "WARNING")
            
            chunk_info['takes'].append(filepath)
            chunk_info['selected_take_index'] = len(chunk_info['takes']) - 1
            chunk_info['status'] = "Hoàn thành"
            
            take_text = f"Take {chunk_info['selected_take_index'] + 1}/{len(chunk_info['takes'])}"
            
            self.root.after(0, lambda: self.tree_chunks.item(
                chunk_info['item_id'], 
                values=(chunk_info['index'], chunk_info['text'], "Hoàn thành", take_text, filepath)
            ))
            # Cập nhật Combobox và log
            self.root.after(0, self.on_chunk_selected)
            self.log(f"Đoạn {chunk_info['index']} hoàn thành")
            
        except Exception as e:
            chunk_info['status'] = "Lỗi"
            take_val = f"Take {chunk_info['selected_take_index'] + 1}/{len(chunk_info['takes'])}" if ('takes' in chunk_info and chunk_info['takes']) else "-"
            self.root.after(0, lambda: self.tree_chunks.item(
                chunk_info['item_id'], 
                values=(chunk_info['index'], chunk_info['text'], "Lỗi", take_val, "")
            ))
            self.log(f"Đoạn {chunk_info['index']} lỗi: {e}", "ERROR")
            
        finally:
            model_generating = False

    def generate_all_chunks(self):
        if not hasattr(self, 'chunks_data') or not self.chunks_data:
            messagebox.showwarning("Cảnh báo", "Vui lòng chia đoạn văn bản trước!")
            return
            
        global loaded_model, model_generating, model_loading
        if "Cloud API" not in self.run_mode_var.get():
            if loaded_model is None:
                if model_loading:
                    messagebox.showinfo("Thông báo", "Đang nạp mô hình trong nền, vui lòng đợi một chút rồi bấm lại!")
                    return
                self.log("Mô hình chưa được nạp. Đang tự động nạp mô hình trước...")
                self.start_load_model()
                return
            
        if model_generating:
            messagebox.showwarning("Cảnh báo", "Mô hình đang bận xử lý tác vụ khác, vui lòng đợi!")
            return
            
        self.stop_generating_flag = False
        for chunk in self.chunks_data:
            self.tree_chunks.item(chunk['item_id'], values=(chunk['index'], chunk['text'], "Chờ xử lý...", ""))
            chunk['status'] = "Chờ xử lý"
            chunk['file_path'] = None
            
        # Lấy giá trị thô trên Main Thread để đảm bảo an toàn cho giao diện Tkinter
        raw_ref_audio = self.engine_ref_audio.get()
        raw_ref_text = self.engine_ref_text.get()
        raw_pitch = self.engine_pitch_var.get()
        raw_style = self.engine_style_var.get()
        raw_voice_combo = self.engine_saved_voices_combo.get()

        model_generating = True
        self.log("Bắt đầu sinh giọng nói tuần tự cho tất cả các đoạn...")
        
        threading.Thread(
            target=self.generate_all_chunks_worker, 
            args=(raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo),
            daemon=True
        ).start()

    def generate_all_chunks_worker(self, raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo):
        global loaded_model, model_generating
        import soundfile as sf
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import shutil
        
        lang = self.engine_lang_var.get()
        language = lang if lang != "Auto" else None
        speed = float(self.engine_speed_var.get())
        num_step = int(self.engine_steps_var.get())
        cfg_scale = float(self.engine_cfg_var.get())
        temperature = float(self.engine_temp_var.get())
        
        # Lấy số luồng tối đa được cấu hình trên giao diện
        try:
            max_workers = int(self.engine_threads_var.get())
        except Exception:
            max_workers = 1
            
        self.log(f"Khởi chạy tiến trình song song với {max_workers} luồng xử lý...")
        
        # Giải quyết các tham số tham chiếu và phong cách an toàn trong luồng phụ
        ref_audio, ref_text, instruct_str = self._resolve_engine_parameters(
            raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo
        )
        
        temp_dir = os.path.join(output_dir, "temp_chunks")
        os.makedirs(temp_dir, exist_ok=True)
        
        success_counter_lock = threading.Lock()
        success_count = 0
        
        def process_chunk(chunk):
            take_val = f"Take {chunk['selected_take_index'] + 1}/{len(chunk['takes'])}" if ('takes' in chunk and chunk['takes']) else "-"
            if self.stop_generating_flag:
                chunk['status'] = "Chưa tạo"
                self.root.after(0, lambda c=chunk, tk_v=take_val: self.tree_chunks.item(c['item_id'], values=(c['index'], c['text'], "Chưa tạo", tk_v, "")))
                return
            nonlocal success_count
            chunk['status'] = "Đang xử lý..."
            self.log(f"Đoạn {chunk['index']} đang tạo voice")
            self.root.after(0, lambda c=chunk, tk_v=take_val: self.tree_chunks.item(c['item_id'], values=(c['index'], c['text'], "Đang xử lý...", tk_v, "")))
            
            # Tiền xử lý chuẩn hóa tiếng Việt
            try:
                from omnivoice.utils.vietnamese_normalizer import normalize_vietnamese_text
                norm_text = normalize_vietnamese_text(chunk['text'])
            except Exception:
                norm_text = chunk['text']
                
            try:
                def make_progress_cb(ch):
                    tk_v2 = f"Take {ch['selected_take_index'] + 1}/{len(ch['takes'])}" if ('takes' in ch and ch['takes']) else "-"
                    return lambda step, total_steps: self.root.after(0, lambda: self.tree_chunks.item(
                        ch['item_id'], 
                        values=(ch['index'], ch['text'], f"Đang xử lý ({int(step / total_steps * 100)}%)", tk_v2, "")
                    ))

                # Xác định file và số take tiếp theo
                if 'takes' not in chunk:
                    chunk['takes'] = []
                    chunk['selected_take_index'] = -1
                take_num = len(chunk['takes']) + 1
                filename = f"chunk_{time.strftime('%Y%m%d_%H%M%S')}_{chunk['index']}_take{take_num}.wav"
                filepath = os.path.join(temp_dir, filename)

                if "Cloud API" in self.run_mode_var.get():
                    temp_filepath = self._call_cloud_api(
                        text=norm_text,
                        language=language,
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        instruct_str=instruct_str,
                        speed=speed,
                        num_step=num_step,
                        cfg_scale=cfg_scale,
                        temperature=temperature,
                        chunk_index=chunk['index'],
                        progress_cb=make_progress_cb(chunk)
                    )
                    shutil.move(temp_filepath, filepath)
                else:
                    # Chế độ chạy local: Sử dụng model_lock để tránh xung đột CUDA context
                    with self.model_lock:
                        audio_data = loaded_model.generate(
                            text=norm_text,
                            language=language,
                            ref_audio=ref_audio,
                            ref_text=ref_text,
                            instruct=instruct_str,
                            speed=speed,
                            num_step=num_step,
                            guidance_scale=cfg_scale,
                            position_temperature=temperature,
                            progress_callback=make_progress_cb(chunk)
                        )
                    sf.write(filepath, audio_data[0], loaded_model.sampling_rate)
                
                # Sao chép file ra outputs chính thức theo cấu hình tên người dùng
                dest_filename = f"{self.imported_txt_name or 'voice'}_{chunk['index']}.wav"
                dest_filepath = os.path.join(output_dir, dest_filename)
                try:
                    shutil.copy2(filepath, dest_filepath)
                    chunk['file_path'] = dest_filepath
                    filepath = dest_filepath
                except Exception as ce:
                    self.log(f"Lỗi khi copy file lẻ ra thư mục outputs: {ce}", "WARNING")
                
                chunk['takes'].append(filepath)
                chunk['selected_take_index'] = len(chunk['takes']) - 1
                chunk['status'] = "Hoàn thành"
                
                take_text = f"Take {chunk['selected_take_index'] + 1}/{len(chunk['takes'])}"
                
                self.root.after(0, lambda c=chunk, path=filepath, tk_t=take_text: self.tree_chunks.item(
                    c['item_id'], 
                    values=(c['index'], c['text'], "Hoàn thành", tk_t, path)
                ))
                with success_counter_lock:
                    success_count += 1
                
                # Cập nhật Combobox nếu dòng này đang chọn
                self.root.after(0, self.on_chunk_selected)
                self.log(f"Đoạn {chunk['index']} hoàn thành")
                
            except Exception as e:
                chunk['status'] = "Lỗi"
                tk_v3 = f"Take {chunk['selected_take_index'] + 1}/{len(chunk['takes'])}" if ('takes' in chunk and chunk['takes']) else "-"
                self.root.after(0, lambda c=chunk, tk_v=tk_v3: self.tree_chunks.item(
                    c['item_id'], 
                    values=(c['index'], c['text'], "Lỗi", tk_v, "")
                ))
                self.log(f"Đoạn {chunk['index']} lỗi", "ERROR")

        # Sử dụng ThreadPoolExecutor để quản lý và phân phối các luồng xử lý
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(process_chunk, self.chunks_data)
            
        model_generating = False
        self.log(f"Hoàn thành quá trình sinh: {success_count}/{len(self.chunks_data)} đoạn thành công.")

    def sort_treeview_column(self, col, reverse):
        # Lấy dữ liệu các hàng trong Treeview
        items = [(self.tree_chunks.set(k, col), k) for k in self.tree_chunks.get_children('')]
        
        # Sắp xếp
        if col == "stt":
            try:
                items.sort(key=lambda t: int(t[0]), reverse=reverse)
            except ValueError:
                items.sort(reverse=reverse)
        else:
            items.sort(reverse=reverse)
            
        # Sắp xếp lại thứ tự các hàng hiển thị
        for index, (val, k) in enumerate(items):
            self.tree_chunks.move(k, '', index)
            
        # Gán lại callback cho tiêu đề với reverse ngược lại cho click tiếp theo
        self.tree_chunks.heading(col, command=lambda: self.sort_treeview_column(col, not reverse))

    def on_chunk_selected(self, event=None):
        selected_item = self.tree_chunks.focus()
        if not selected_item:
            self.combo_engine_takes.configure(values=[])
            self.combo_engine_takes.set("")
            return
            
        chunk = None
        for c in self.chunks_data:
            if c['item_id'] == selected_item:
                chunk = c
                break
                
        if chunk and 'takes' in chunk and chunk['takes']:
            take_options = [f"Take {i+1}" for i in range(len(chunk['takes']))]
            self.combo_engine_takes.configure(values=take_options)
            self.combo_engine_takes.set(f"Take {chunk['selected_take_index'] + 1}")
        else:
            self.combo_engine_takes.configure(values=[])
            self.combo_engine_takes.set("")

    def on_take_selected(self, event=None):
        selected_item = self.tree_chunks.focus()
        if not selected_item:
            return
            
        chunk = None
        for c in self.chunks_data:
            if c['item_id'] == selected_item:
                chunk = c
                break
                
        if chunk and 'takes' in chunk and chunk['takes']:
            sel_str = self.combo_engine_takes.get()
            try:
                idx = int(sel_str.replace("Take ", "")) - 1
                if 0 <= idx < len(chunk['takes']):
                    chunk['selected_take_index'] = idx
                    chunk['file_path'] = chunk['takes'][idx]
                    
                    take_text = f"Take {idx + 1}/{len(chunk['takes'])}"
                    self.tree_chunks.item(
                        chunk['item_id'],
                        values=(chunk['index'], chunk['text'], chunk['status'], take_text, chunk['file_path'])
                    )
                    self.log(f"Đã chuyển sang {sel_str} cho đoạn {chunk['index']}")
            except Exception as e:
                pass

    def delete_selected_take(self):
        selected_item = self.tree_chunks.focus()
        if not selected_item:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một đoạn trong bảng danh sách trước!")
            return
            
        chunk = None
        for c in self.chunks_data:
            if c['item_id'] == selected_item:
                chunk = c
                break
                
        if not chunk or 'takes' not in chunk or not chunk['takes']:
            messagebox.showinfo("Thông báo", "Đoạn này chưa có phiên bản nào được tạo!")
            return
            
        idx = chunk['selected_take_index']
        filepath = chunk['takes'][idx]
        
        # Xóa file thực tế trên đĩa
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                self.log(f"Không thể xóa file {os.path.basename(filepath)}: {e}", "WARNING")
                
        # Xóa khỏi danh sách takes
        chunk['takes'].pop(idx)
        
        if not chunk['takes']:
            chunk['selected_take_index'] = -1
            chunk['file_path'] = None
            chunk['status'] = "Chưa tạo"
            take_text = "-"
            status_text = "Chưa tạo"
            file_text = ""
        else:
            # Chuyển focus sang take cuối cùng còn lại
            chunk['selected_take_index'] = len(chunk['takes']) - 1
            chunk['file_path'] = chunk['takes'][-1]
            take_text = f"Take {chunk['selected_take_index'] + 1}/{len(chunk['takes'])}"
            status_text = chunk['status']
            file_text = chunk['file_path']
            
        self.tree_chunks.item(
            chunk['item_id'],
            values=(chunk['index'], chunk['text'], status_text, take_text, file_text)
        )
        
        # Cập nhật lại combo box
        self.on_chunk_selected()
        self.log(f"Đã xóa phiên bản Take {idx+1} của đoạn {chunk['index']}.")

    def stop_generating_voice(self):
        global model_generating
        if not model_generating:
            return
        self.stop_generating_flag = True
        self.log("Đã kích hoạt cờ dừng tạo. Các luồng đang chạy sẽ bỏ qua các đoạn còn lại...", "WARNING")

    def generate_failed_chunks(self):
        if not hasattr(self, 'chunks_data') or not self.chunks_data:
            messagebox.showwarning("Cảnh báo", "Vui lòng chia đoạn văn bản trước!")
            return
            
        failed_chunks = [c for c in self.chunks_data if c['status'] == "Lỗi"]
        if not failed_chunks:
            messagebox.showinfo("Thông báo", "Không có đoạn nào bị lỗi để tạo lại!")
            return
            
        global loaded_model, model_generating, model_loading
        if "Cloud API" not in self.run_mode_var.get():
            if loaded_model is None:
                if model_loading:
                    messagebox.showinfo("Thông báo", "Đang nạp mô hình trong nền, vui lòng đợi một chút rồi bấm lại!")
                    return
                self.log("Mô hình chưa được nạp. Đang tự động nạp mô hình trước...")
                self.start_load_model()
                return
            
        if model_generating:
            messagebox.showwarning("Cảnh báo", "Mô hình đang bận xử lý tác vụ khác, vui lòng đợi!")
            return
            
        self.stop_generating_flag = False
        for chunk in failed_chunks:
            self.tree_chunks.item(chunk['item_id'], values=(chunk['index'], chunk['text'], "Chờ xử lý...", ""))
            chunk['status'] = "Chờ xử lý"
            chunk['file_path'] = None
            
        # Lấy giá trị thô trên Main Thread để đảm bảo an toàn cho giao diện Tkinter
        raw_ref_audio = self.engine_ref_audio.get()
        raw_ref_text = self.engine_ref_text.get()
        raw_pitch = self.engine_pitch_var.get()
        raw_style = self.engine_style_var.get()
        raw_voice_combo = self.engine_saved_voices_combo.get()

        model_generating = True
        self.log(f"Bắt đầu tạo lại {len(failed_chunks)} đoạn bị lỗi...")
        
        threading.Thread(
            target=self.generate_failed_chunks_worker, 
            args=(failed_chunks, raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo),
            daemon=True
        ).start()

    def generate_failed_chunks_worker(self, failed_chunks, raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo):
        global loaded_model, model_generating
        import soundfile as sf
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import shutil
        
        lang = self.engine_lang_var.get()
        language = lang if lang != "Auto" else None
        speed = float(self.engine_speed_var.get())
        num_step = int(self.engine_steps_var.get())
        cfg_scale = float(self.engine_cfg_var.get())
        temperature = float(self.engine_temp_var.get())
        
        # Lấy số luồng tối đa được cấu hình trên giao diện
        try:
            max_workers = int(self.engine_threads_var.get())
        except Exception:
            max_workers = 1
            
        self.log(f"Khởi chạy tiến trình song song tạo lại lỗi với {max_workers} luồng xử lý...")
        
        # Giải quyết các tham số tham chiếu và phong cách an toàn trong luồng phụ
        ref_audio, ref_text, instruct_str = self._resolve_engine_parameters(
            raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo
        )
        
        temp_dir = os.path.join(output_dir, "temp_chunks")
        os.makedirs(temp_dir, exist_ok=True)
        
        success_counter_lock = threading.Lock()
        success_count = 0
        
        def process_chunk(chunk):
            take_val = f"Take {chunk['selected_take_index'] + 1}/{len(chunk['takes'])}" if ('takes' in chunk and chunk['takes']) else "-"
            if self.stop_generating_flag:
                chunk['status'] = "Lỗi"
                self.root.after(0, lambda c=chunk, tk_v=take_val: self.tree_chunks.item(c['item_id'], values=(c['index'], c['text'], "Lỗi", tk_v, "")))
                return
            nonlocal success_count
            chunk['status'] = "Đang xử lý..."
            self.log(f"Đoạn {chunk['index']} đang tạo voice")
            self.root.after(0, lambda c=chunk, tk_v=take_val: self.tree_chunks.item(c['item_id'], values=(c['index'], c['text'], "Đang xử lý...", tk_v, "")))
            
            # Tiền xử lý chuẩn hóa tiếng Việt
            try:
                from omnivoice.utils.vietnamese_normalizer import normalize_vietnamese_text
                norm_text = normalize_vietnamese_text(chunk['text'])
            except Exception:
                norm_text = chunk['text']
                
            try:
                def make_progress_cb(ch):
                    tk_v2 = f"Take {ch['selected_take_index'] + 1}/{len(ch['takes'])}" if ('takes' in ch and ch['takes']) else "-"
                    return lambda step, total_steps: self.root.after(0, lambda: self.tree_chunks.item(
                        ch['item_id'], 
                        values=(ch['index'], ch['text'], f"Đang xử lý ({int(step / total_steps * 100)}%)", tk_v2, "")
                    ))

                # Xác định file và số take tiếp theo
                if 'takes' not in chunk:
                    chunk['takes'] = []
                    chunk['selected_take_index'] = -1
                take_num = len(chunk['takes']) + 1
                filename = f"chunk_{time.strftime('%Y%m%d_%H%M%S')}_{chunk['index']}_take{take_num}.wav"
                filepath = os.path.join(temp_dir, filename)

                pad_duration = float(self.engine_pad_var.get()) if hasattr(self, 'engine_pad_var') else 0.0
                fade_duration = float(self.engine_fade_var.get()) if hasattr(self, 'engine_fade_var') else 0.0

                if "Cloud API" in self.run_mode_var.get():
                    temp_filepath = self._call_cloud_api(
                        text=norm_text,
                        language=language,
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        instruct_str=instruct_str,
                        speed=speed,
                        num_step=num_step,
                        cfg_scale=cfg_scale,
                        temperature=temperature,
                        pad_duration=pad_duration,
                        fade_duration=fade_duration,
                        chunk_index=chunk['index'],
                        progress_cb=make_progress_cb(chunk)
                    )
                    shutil.move(temp_filepath, filepath)
                else:
                    import inspect
                    sig = inspect.signature(loaded_model.generate)
                    gen_kwargs = {
                        "text": norm_text,
                        "language": language,
                        "ref_audio": ref_audio,
                        "ref_text": ref_text,
                        "instruct": instruct_str,
                        "speed": speed,
                        "num_step": num_step,
                        "guidance_scale": cfg_scale,
                        "position_temperature": temperature,
                        "progress_callback": make_progress_cb(chunk)
                    }
                    if "pad_duration" in sig.parameters:
                        gen_kwargs["pad_duration"] = pad_duration
                    if "fade_duration" in sig.parameters:
                        gen_kwargs["fade_duration"] = fade_duration

                    # Chế độ chạy local: Sử dụng model_lock để tránh xung đột CUDA context
                    with self.model_lock:
                        audio_data = loaded_model.generate(**gen_kwargs)
                    sf.write(filepath, audio_data[0], loaded_model.sampling_rate)
                
                # Sao chép file ra outputs chính thức theo cấu hình tên người dùng
                dest_filename = f"{self.imported_txt_name or 'voice'}_{chunk['index']}.wav"
                dest_filepath = os.path.join(output_dir, dest_filename)
                try:
                    shutil.copy2(filepath, dest_filepath)
                    chunk['file_path'] = dest_filepath
                    filepath = dest_filepath
                except Exception as ce:
                    self.log(f"Lỗi khi copy file lẻ ra thư mục outputs: {ce}", "WARNING")
                
                chunk['takes'].append(filepath)
                chunk['selected_take_index'] = len(chunk['takes']) - 1
                chunk['status'] = "Hoàn thành"
                
                take_text = f"Take {chunk['selected_take_index'] + 1}/{len(chunk['takes'])}"
                
                self.root.after(0, lambda c=chunk, path=filepath, tk_t=take_text: self.tree_chunks.item(
                    c['item_id'], 
                    values=(c['index'], c['text'], "Hoàn thành", tk_t, path)
                ))
                with success_counter_lock:
                    success_count += 1
                
                # Cập nhật Combobox nếu dòng này đang chọn
                self.root.after(0, self.on_chunk_selected)
                self.log(f"Đoạn {chunk['index']} hoàn thành")
                
            except Exception as e:
                chunk['status'] = "Lỗi"
                tk_v3 = f"Take {chunk['selected_take_index'] + 1}/{len(chunk['takes'])}" if ('takes' in chunk and chunk['takes']) else "-"
                self.root.after(0, lambda c=chunk, tk_v=tk_v3: self.tree_chunks.item(
                    c['item_id'], 
                    values=(c['index'], c['text'], "Lỗi", tk_v, "")
                ))
                self.log(f"Đoạn {chunk['index']} lỗi", "ERROR")

        # Sử dụng ThreadPoolExecutor để quản lý và phân phối các luồng xử lý
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(process_chunk, failed_chunks)
            
        model_generating = False
        self.log(f"Tiến trình tạo lại hoàn tất. Thành công: {success_count}/{len(failed_chunks)} đoạn.")
        self.root.after(0, lambda: messagebox.showinfo("Thành công", f"Đã hoàn thành tạo lại các đoạn lỗi!\nThành công: {success_count}/{len(failed_chunks)} đoạn."))

    def play_selected_chunk(self):
        selected_item = self.tree_chunks.focus()
        if not selected_item:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn đoạn cần phát nghe thử!")
            return
            
        chunk_info = None
        for c in self.chunks_data:
            if c['item_id'] == selected_item:
                chunk_info = c
                break
                
        if not chunk_info or not chunk_info['file_path'] or not os.path.exists(chunk_info['file_path']):
            messagebox.showwarning("Cảnh báo", "Đoạn này chưa được tạo hoặc file tạm không tồn tại!")
            return
            
        self.play_audio_file(chunk_info['file_path'])

    def merge_all_chunks(self):
        if not hasattr(self, 'chunks_data') or not self.chunks_data:
            messagebox.showwarning("Cảnh báo", "Chưa có danh sách đoạn để gộp!")
            return
            
        dest_path = self.engine_dest_path.get().strip()
        if not dest_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn đường dẫn lưu file hoàn chỉnh!")
            return
            
        # Chuẩn hóa đuôi file âm thanh (mặc định là .wav nếu người dùng nhập thiếu hoặc sai đuôi)
        _, ext = os.path.splitext(dest_path)
        if ext.lower() not in ['.wav', '.flac', '.ogg', '.mp3']:
            dest_path += ".wav"
            self.engine_dest_path.set(dest_path)
            
        temp_files = []
        for chunk in self.chunks_data:
            if chunk['status'] == "Hoàn thành" and chunk['file_path'] and os.path.exists(chunk['file_path']):
                temp_files.append(chunk['file_path'])
                
        if not temp_files:
            messagebox.showwarning("Cảnh báo", "Không có đoạn nào ở trạng thái 'Hoàn thành' để gộp!")
            return
            
        if len(temp_files) < len(self.chunks_data):
            ans = messagebox.askyesno("Xác nhận", f"Chỉ có {len(temp_files)}/{len(self.chunks_data)} đoạn đã hoàn thành. Bạn có muốn gộp trước các đoạn này không?")
            if not ans:
                return
                
        self.stop_audio_playback()  # Dừng phát thử để giải phóng file đang khóa
        self.log("Bắt đầu gộp các đoạn âm thanh thành file duy nhất...")
        
        import wave
        import gc
        import time
        
        try:
            if temp_files:
                # Đọc thông số của file đầu tiên làm mẫu
                with wave.open(temp_files[0], 'rb') as w:
                    params = w.getparams()
                
                # Tính toán khoảng lặng
                try:
                    silence_sec = float(self.merge_silence_duration_var.get())
                except Exception:
                    silence_sec = 0.2
                    
                num_silence_frames = int(params.framerate * silence_sec)
                silence_bytes = b'\x00' * (num_silence_frames * params.sampwidth * params.nchannels)
                
                with wave.open(dest_path, 'wb') as w_out:
                    w_out.setparams(params)
                    for i, f in enumerate(temp_files):
                        if i > 0 and len(silence_bytes) > 0:
                            # Chèn khoảng lặng đệm giữa các đoạn
                            w_out.writeframes(silence_bytes)
                        with wave.open(f, 'rb') as w_in:
                            w_out.writeframes(w_in.readframes(w_in.getnframes()))
                
                self.log(f"Đã gộp thành công file hoàn chỉnh tại: {dest_path}")
                messagebox.showinfo("Thành công", f"Đã gộp và xuất file thành công tại:\n{dest_path}")
                
                if hasattr(self, 'delete_temp_after_merge_var') and self.delete_temp_after_merge_var.get():
                    self.log("Đang chờ Windows giải phóng các tệp âm thanh tạm thời...")
                    time.sleep(0.5)  # Tránh việc ffplay/winsound chưa tắt hẳn
                    gc.collect()     # Dọn rác giải phóng handles
                    
                    self.log("Đang tiến hành dọn dẹp các tệp nhỏ tạm thời...")
                    # Gom tất cả các take của các chunk để xóa sạch sẽ
                    files_to_delete = []
                    for chunk in self.chunks_data:
                        if 'takes' in chunk:
                            for tk_file in chunk['takes']:
                                if os.path.exists(tk_file):
                                    files_to_delete.append(tk_file)
                                    
                    for f in files_to_delete:
                        deleted = False
                        for attempt in range(5):
                            try:
                                if os.path.exists(f):
                                    os.remove(f)
                                deleted = True
                                break
                            except Exception:
                                time.sleep(0.3)
                        if not deleted:
                            self.log(f"Không thể xóa file tạm: {os.path.basename(f)} do Windows giữ khóa.", "WARNING")
                    
                    for chunk in self.chunks_data:
                        chunk['takes'] = []
                        chunk['selected_take_index'] = -1
                        chunk['file_path'] = None
                        self.tree_chunks.item(chunk['item_id'], values=(chunk['index'], chunk['text'], chunk['status'], "-", "Đã dọn dẹp"))
                            
                    self.log("Đã hoàn thành dọn dẹp các tệp tạm.")
                else:
                    self.log("Bỏ qua dọn dẹp file tạm theo cấu hình.")
                
        except Exception as e:
            self.log(f"Lỗi khi gộp file: {e}", "ERROR")
            messagebox.showerror("Lỗi", f"Không thể gộp các tệp âm thanh:\n{e}")

    def generate_voice_clone(self):
        global loaded_model, model_generating, model_loading
        
        # Kiểm tra trạng thái
        if model_generating:
            return
            
        text_to_read = self.txt_clone_input.get("1.0", tk.END).strip()
        ref_audio = self.ref_audio_path.get()
        ref_text = self.ent_ref_text.get().strip()
        
        if not text_to_read:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập văn bản cần đọc!")
            return
        if not ref_audio or not os.path.exists(ref_audio):
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file âm thanh mẫu hợp lệ!")
            return
            
        # Nếu chưa nạp model, tiến hành nạp tự động
        if loaded_model is None:
            if model_loading:
                messagebox.showinfo("Thông báo", "Đang nạp mô hình trong nền, vui lòng đợi một chút rồi bấm lại!")
                return
            # Xác nhận trước khi tự nạp
            self.log("Mô hình chưa được nạp. Đang tự động nạp mô hình trước...")
            self.start_load_model()
            return

        # Vô hiệu hóa nút bấm khi đang sinh
        model_generating = True
        self.btn_clone_generate.configure(state="disabled")
        self.lbl_clone_result_status.configure(text="Đang xử lý sinh giọng nói... Vui lòng đợi...", foreground="#FFB300")
        
        # Chạy suy luận trong thread riêng
        threading.Thread(target=self.voice_clone_worker, args=(text_to_read, ref_audio, ref_text), daemon=True).start()

    def voice_clone_worker(self, text_to_read, ref_audio, ref_text):
        global loaded_model, model_generating
        import soundfile as sf
        
        # Chuẩn bị tham số
        lang = self.clone_lang_var.get()
        language = lang if lang != "Auto" else None
        
        speed = float(self.clone_speed_var.get())
        num_step = int(self.clone_steps_var.get())
        
        use_asr = self.asr_enabled_var.get()
        
        # Nếu không có ref_text và bật ASR
        final_ref_text = ref_text
        if not final_ref_text and use_asr:
            if loaded_model._asr_pipe is None:
                self.log("Đang nạp mô hình ASR Whisper để nhận diện văn bản mẫu...")
                try:
                    loaded_model.load_asr_model(model_name=MODEL_ASR)
                except Exception as e:
                    self.log(f"Không thể nạp Whisper ASR: {e}. Vui lòng tự điền văn bản mẫu.", "ERROR")
            
            if loaded_model._asr_pipe is not None:
                self.log("Đang nhận diện giọng nói file mẫu thành văn bản...")
                try:
                    # Chạy nhận diện
                    final_ref_text = loaded_model.transcribe(ref_audio)
                    self.log(f"Văn bản nhận diện được: \"{final_ref_text}\"")
                    # Điền vào GUI
                    self.root.after(0, lambda: self.ent_ref_text.delete(0, tk.END))
                    self.root.after(0, lambda: self.ent_ref_text.insert(0, final_ref_text))
                except Exception as e:
                    self.log(f"Lỗi nhận diện ASR: {e}", "WARNING")
                    final_ref_text = None
        
        if not final_ref_text:
            final_ref_text = None
            
        start_time = time.time()
        self.log(f"Bắt đầu suy luận nhái giọng (Steps={num_step}, Speed={speed:.2f})...")
        
        try:
            # Thực hiện sinh giọng nói
            audio_data = loaded_model.generate(
                text=text_to_read,
                language=language,
                ref_audio=ref_audio,
                ref_text=final_ref_text,
                speed=speed,
                num_step=num_step
            )
            
            # Lưu file kết quả
            filename = f"clone_{time.strftime('%Y%m%d_%H%M%S')}.wav"
            filepath = os.path.join(output_dir, filename)
            
            sf.write(filepath, audio_data[0], loaded_model.sampling_rate)
            
            duration = len(audio_data[0]) / loaded_model.sampling_rate
            elapsed = time.time() - start_time
            rtf = elapsed / duration if duration > 0 else 0
            
            self.clone_output_file = filepath
            success_msg = f"Đã sinh xong file: {filename}\nThời gian sinh: {elapsed:.2f}s | RTF: {rtf:.3f} | Độ dài: {duration:.2f}s"
            self.log(success_msg)
            
            # Cập nhật kết quả lên UI và tự động phát
            self.root.after(0, lambda: self.lbl_clone_result_status.configure(text=f"Hoàn thành: {filename} ({duration:.1f}s)", foreground="#00E676"))
            self.play_audio_file(filepath)
            
        except Exception as e:
            self.log(f"Lỗi sinh giọng nói (Voice Clone): {e}", "ERROR")
            self.root.after(0, lambda: self.lbl_clone_result_status.configure(text="Lỗi: Không thể sinh giọng.", foreground="#FF3366"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi tạo giọng nói", f"Lỗi trong quá trình sinh giọng nói:\n{e}"))
        finally:
            model_generating = False
            self.root.after(0, lambda: self.btn_clone_generate.configure(state="normal"))

    def play_clone_result(self):
        if not self.clone_output_file or not os.path.exists(self.clone_output_file):
            messagebox.showwarning("Cảnh báo", "Chưa có file kết quả để phát!")
            return
        self.play_audio_file(self.clone_output_file)

    # =====================================================================
    # Chức năng Voice Design (Thiết kế giọng)
    # =====================================================================
    def generate_voice_design(self):
        global loaded_model, model_generating, model_loading
        
        # Kiểm tra trạng thái
        if model_generating:
            return
            
        text_to_read = self.txt_design_input.get("1.0", tk.END).strip()
        
        if not text_to_read:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập văn bản cần đọc!")
            return
            
        # Nếu chưa nạp model, tiến hành nạp tự động
        if loaded_model is None:
            if model_loading:
                messagebox.showinfo("Thông báo", "Đang nạp mô hình trong nền, vui lòng đợi một chút rồi bấm lại!")
                return
            self.log("Mô hình chưa được nạp. Đang tự động nạp mô hình trước...")
            self.start_load_model()
            return

        # Vô hiệu hóa nút bấm khi đang sinh
        model_generating = True
        self.btn_design_generate.configure(state="disabled")
        self.lbl_design_result_status.configure(text="Đang xử lý sinh giọng thiết kế... Vui lòng đợi...", foreground="#FFB300")
        
        # Chạy suy luận trong thread riêng
        threading.Thread(target=self.voice_design_worker, args=(text_to_read,), daemon=True).start()

    def voice_design_worker(self, text_to_read):
        global loaded_model, model_generating
        import soundfile as sf
        
        # Lấy thuộc tính thiết kế giọng
        instruct_parts = []
        
        gender = self.vd_gender_var.get()
        if gender != "Auto":
            # Ví dụ "Male / 男" -> Lấy phần tiếng Anh: "Male"
            instruct_parts.append(gender.split(" / ")[0].lower())
            
        age = self.vd_age_var.get()
        if age != "Auto":
            instruct_parts.append(age.split(" / ")[0].lower())
            
        pitch = self.vd_pitch_var.get()
        if pitch != "Auto":
            instruct_parts.append(pitch.split(" / ")[0].lower())
            
        style = self.vd_style_var.get()
        if style != "Auto":
            instruct_parts.append(style.split(" / ")[0].lower())
            
        accent = self.vd_accent_var.get()
        if accent != "Auto":
            instruct_parts.append(accent.split(" / ")[0].lower())
            
        dialect = self.vd_dialect_var.get()
        if dialect != "Auto":
            # Phương ngôn thì lấy phần tiếng Trung (mô hình học theo cụm từ tiếng Trung)
            instruct_parts.append(dialect.split(" / ")[1])
            
        instruct_str = ", ".join(instruct_parts) if instruct_parts else None
        
        # Chuẩn bị các tham số khác
        lang = self.design_lang_var.get()
        language = lang if lang != "Auto" else None
        
        speed = float(self.design_speed_var.get())
        num_step = int(self.design_steps_var.get())
        
        start_time = time.time()
        self.log(f"Bắt đầu thiết kế giọng đọc (Instruct=\"{instruct_str}\", Steps={num_step}, Speed={speed:.2f})...")
        
        try:
            # Thực hiện sinh giọng nói thiết kế
            audio_data = loaded_model.generate(
                text=text_to_read,
                language=language,
                instruct=instruct_str,
                speed=speed,
                num_step=num_step
            )
            
            # Lưu file kết quả
            filename = f"design_{time.strftime('%Y%m%d_%H%M%S')}.wav"
            filepath = os.path.join(output_dir, filename)
            
            sf.write(filepath, audio_data[0], loaded_model.sampling_rate)
            
            duration = len(audio_data[0]) / loaded_model.sampling_rate
            elapsed = time.time() - start_time
            rtf = elapsed / duration if duration > 0 else 0
            
            self.design_output_file = filepath
            success_msg = f"Đã sinh xong file: {filename}\nThời gian sinh: {elapsed:.2f}s | RTF: {rtf:.3f} | Độ dài: {duration:.2f}s"
            self.log(success_msg)
            
            # Cập nhật kết quả lên UI và tự động phát
            self.root.after(0, lambda: self.lbl_design_result_status.configure(text=f"Hoàn thành: {filename} ({duration:.1f}s)", foreground="#00E676"))
            self.play_audio_file(filepath)
            
        except Exception as e:
            self.log(f"Lỗi sinh giọng nói (Voice Design): {e}", "ERROR")
            self.root.after(0, lambda: self.lbl_design_result_status.configure(text="Lỗi: Không thể sinh giọng.", foreground="#FF3366"))
            self.root.after(0, lambda: messagebox.showerror("Lỗi tạo giọng nói", f"Lỗi trong quá trình sinh giọng nói:\n{e}"))
        finally:
            model_generating = False
            self.root.after(0, lambda: self.btn_design_generate.configure(state="normal"))

    def play_design_result(self):
        if not self.design_output_file or not os.path.exists(self.design_output_file):
            messagebox.showwarning("Cảnh báo", "Chưa có file kết quả để phát!")
            return
        self.play_audio_file(self.design_output_file)

    # =====================================================================
    # Trình phát Âm thanh và Tiện ích
    # =====================================================================
    def play_audio_file(self, filepath):
        global current_play_process
        self.stop_audio_playback()
        
        try:
            # Sử dụng ffplay đi kèm ffmpeg để phát không bị đứng GUI, hỗ trợ mọi định dạng
            current_play_process = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            )
            self.log(f"Đang phát âm thanh: {os.path.basename(filepath)}")
        except Exception as e:
            self.log(f"Lỗi phát âm thanh bằng ffplay: {e}. Thử dùng winsound...", "WARNING")
            # Fallback dùng winsound (chỉ chạy với file wav)
            try:
                import winsound
                winsound.PlaySound(filepath, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as ex:
                self.log(f"Không thể phát âm thanh: {ex}", "ERROR")

    def stop_audio_playback(self):
        global current_play_process
        # Dừng tiến trình ffplay
        if current_play_process:
            try:
                current_play_process.terminate()
                current_play_process.wait(timeout=1)
                self.log("Đã dừng phát âm thanh.")
            except Exception:
                pass
            current_play_process = None
            
        # Dừng winsound nếu đang phát
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def disconnect_current_vpn(self):
        if hasattr(self, 'current_vpn_tunnel') and self.current_vpn_tunnel:
            tunnel = self.current_vpn_tunnel
            self.log(f"[VPN] Đang ngắt kết nối VPN Tunnel: {tunnel}...")
            
            wireguard_path = "C:\\Program Files\\WireGuard\\wireguard.exe"
            if not os.path.exists(wireguard_path):
                wireguard_path = "wireguard"
                
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                
            cmd = [wireguard_path, "/uninstalltunnelservice", tunnel]
            try:
                subprocess.run(cmd, startupinfo=startupinfo, capture_output=True)
                self.log(f"[VPN] Đã ngắt kết nối VPN Tunnel: {tunnel}")
            except Exception as e:
                self.log(f"[VPN] Lỗi ngắt kết nối VPN: {e}", "ERROR")
            self.current_vpn_tunnel = None
            time.sleep(2)

    def connect_random_vpn(self):
        try:
            self.disconnect_current_vpn()
            
            config_dir = os.path.join(current_dir, "config")
            if not os.path.exists(config_dir):
                self.log("[VPN] Không tìm thấy thư mục 'config' chứa cấu hình VPN.", "WARNING")
                return
                
            conf_files = [f for f in os.listdir(config_dir) if f.endswith(".conf")]
            if not conf_files:
                self.log("[VPN] Không tìm thấy file cấu hình WireGuard (.conf) nào trong thư mục 'config'.", "WARNING")
                return
                
            import random
            selected_file = random.choice(conf_files)
            tunnel_name = os.path.splitext(selected_file)[0]
            abs_path = os.path.abspath(os.path.join(config_dir, selected_file))
            
            self.log(f"[VPN] Đã chọn ngẫu nhiên file cấu hình VPN: {selected_file}. Đang kết nối...")
            
            wireguard_path = "C:\\Program Files\\WireGuard\\wireguard.exe"
            if not os.path.exists(wireguard_path):
                wireguard_path = "wireguard"
                
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                
            cmd = [wireguard_path, "/installtunnelservice", abs_path]
            
            res = subprocess.run(cmd, startupinfo=startupinfo, capture_output=True, text=True)
            if res.returncode == 0 or "already exists" in res.stderr.lower() or "already exists" in res.stdout.lower():
                self.current_vpn_tunnel = tunnel_name
                self.log(f"[VPN] Đã kích hoạt VPN Tunnel thành công: {tunnel_name}")
                self.log("[VPN] Đang đợi 5 giây để kết nối mạng ổn định...")
                time.sleep(5)
            else:
                self.log(f"[VPN] Lỗi kích hoạt VPN Tunnel: {res.stderr}", "ERROR")
        except Exception as e:
            self.log(f"[VPN] Lỗi kết nối VPN: {e}", "ERROR")

    def start_kaggle_server_thread(self):
        self.btn_start_kaggle.configure(state="disabled")
        self.btn_stop_kaggle.configure(state="normal")
        threading.Thread(target=self.start_kaggle_server_worker, daemon=True).start()

    def start_kaggle_server_worker(self):
        raw_keys = self.txt_kaggle_key.get("1.0", tk.END).strip() if hasattr(self, 'txt_kaggle_key') else getattr(self, 'kaggle_key', '')
        if not raw_keys:
            self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", "Vui lòng nhập Kaggle API Token (KGAT)!"))
            self.root.after(0, lambda: self.btn_start_kaggle.configure(state="normal"))
            return

        # Phân tách danh sách các key (mỗi dòng 1 key hoặc ngăn cách bởi dấu phẩy)
        import re
        keys_list = [k.strip() for k in re.split(r'[,\n\r]+', raw_keys) if k.strip()]
        if not keys_list:
            self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", "Vui lòng nhập ít nhất một Kaggle API Token hợp lệ!"))
            self.root.after(0, lambda: self.btn_start_kaggle.configure(state="normal"))
            return

        # Tìm key đầu tiên hợp lệ (< 29.5 giờ)
        valid_key = None
        for key in keys_list:
            accumulated_time = self.kaggle_api_keys_data.get(key, {}).get("total_hours", 0.0)
            if accumulated_time < 29.5:
                valid_key = key
                break

        if not valid_key:
            self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", "Tất cả các API key đã nhập đều đã sử dụng vượt quá 29.5 giờ! Vui lòng bổ sung API key mới."))
            self.root.after(0, lambda: self.btn_start_kaggle.configure(state="normal"))
            return

        # Gán key hoạt động chính
        self.active_kaggle_key = valid_key
        self.active_key_initial_hours = self.kaggle_api_keys_data.get(valid_key, {}).get("total_hours", 0.0)
        self.log(f"[Kaggle] Bắt đầu khởi chạy server sử dụng API Key có thời gian tích lũy: {self.active_key_initial_hours:.2f} giờ")

        # 1. Đổi IP bằng VPN
        self.connect_random_vpn()

        # 2. Tạo tệp cấu hình xác thực Kaggle API
        kaggle_dir = os.path.expanduser("~/.kaggle")
        os.makedirs(kaggle_dir, exist_ok=True)
        access_token_path = os.path.join(kaggle_dir, "access_token")
        try:
            with open(access_token_path, "w", encoding="utf-8") as f:
                f.write(valid_key)
        except Exception as e:
            self.log(f"Lỗi ghi file access_token: {e}", "ERROR")

        # Thiết lập biến môi trường cho tiến trình cha
        os.environ["KAGGLE_API_TOKEN"] = valid_key

        # 3. Tự động introspect username thực tế
        self.root.after(0, lambda: self.lbl_kaggle_status.configure(text="🟡 Đang xác thực tài khoản...", foreground="#FFB300"))
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            username = api.config_values.get('username')
            if not username:
                raise ValueError("Không lấy được username từ introspect token")
            self.kaggle_username = username
            self.save_config()
            self.log(f"[Kaggle] Xác thực thành công. Username: {username}")
        except Exception as e:
            self.log(f"[Kaggle] Lỗi introspect Kaggle Username từ API Token: {e}", "ERROR")
            self.disconnect_current_vpn()
            self.root.after(0, lambda: messagebox.showerror("Lỗi xác thực", f"Lỗi xác thực Kaggle API Token:\n{e}"))
            self.root.after(0, lambda: self.btn_start_kaggle.configure(state="normal"))
            return

        # Sinh mới ID bí mật ngẫu nhiên cho phiên chạy này để dọn sạch các tín hiệu cũ trên ntfy.sh
        import uuid
        self.kaggle_secret_id = f"omni_{uuid.uuid4().hex[:8]}"
        self.save_config()

        # 4. Chuẩn bị thư mục và tệp notebook đẩy lên Kaggle
        build_dir = os.path.join(current_dir, "kaggle_build")
        os.makedirs(build_dir, exist_ok=True)

        # Cấu hình kernel-metadata.json
        meta = {
            "id": f"{self.kaggle_username}/omnivoice-server-api",
            "title": "OmniVoice Server API",
            "code_file": "omnivoice_server_kaggle.ipynb",
            "language": "python",
            "kernel_type": "notebook",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": []
        }
        gpu_acc_raw = getattr(self, 'kaggle_gpu', 'NvidiaTeslaT4')
        gpu_acc = "NvidiaTeslaT4" if gpu_acc_raw == "NvidiaTeslaT4x2" else gpu_acc_raw
        if gpu_acc:
            meta["machine_shape"] = gpu_acc
        with open(os.path.join(build_dir, "kernel-metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        # Tạo file notebook chạy server
        # Chú ý ntfy.sh gửi link: POST https://ntfy.sh/omnivoice_server_link_{kaggle_secret_id}
        # cell 1: clone và cài đặt môi trường
        # cell 2: khởi chạy server api
        notebook_content = {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "import os\n",
                        "import sys\n",
                        "print(\"[*] Đang tải mã nguồn OmniVoice-Server từ GitHub...\")\n",
                        "os.system(\"rm -rf /kaggle/working/OmniVoice-Server OmniVoice-Server-main OmniVoice-Server-master main.zip\")\n",
                        "ret = os.system(\"wget https://github.com/danghai-245/OmniVoice-Server/archive/refs/heads/main.zip -O main.zip\")\n",
                        "if ret != 0:\n",
                        "    ret = os.system(\"wget https://github.com/danghai-245/OmniVoice-Server/archive/refs/heads/master.zip -O main.zip\")\n",
                        "if not os.path.exists(\"main.zip\") or os.path.getsize(\"main.zip\") < 1000:\n",
                        "    print(\"\\n\" + \"=\"*80)\n",
                        "    print(\"[ERROR] KHÔNG THỂ TẢI MÃ NGUỒN OMNIVOICE SERVER!\")\n",
                        "    print(\"Nguyên nhân: File zip tải về không tồn tại hoặc dung lượng quá nhỏ.\")\n",
                        "    print(\"Vui lòng kiểm tra:\")\n",
                        "    print(\"  1. Repository 'danghai-245/OmniVoice-Server' của bạn có đang ở chế độ PRIVATE hay không?\")\n",
                        "    print(\"     -> Nếu có, vui lòng chuyển sang PUBLIC trên GitHub để Kaggle có thể tải về.\")\n",
                        "    print(\"  2. Tên tài khoản GitHub hoặc tên Repository trong URL có bị viết sai chính tả hay không?\")\n",
                        "    print(\"=\"*80 + \"\\n\")\n",
                        "    raise RuntimeError(\"Tải mã nguồn thất bại - Repo có thể đang là Private.\")\n",
                        "print(\"[*] Đang giải nén mã nguồn...\")\n",
                        "ret_unzip = os.system(\"unzip main.zip\")\n",
                        "if ret_unzip != 0:\n",
                        "    raise RuntimeError(\"Giải nén mã nguồn thất bại.\")\n",
                        "os.system(\"mv OmniVoice-Server-* /kaggle/working/OmniVoice-Server\")\n",
                        "os.system(\"rm -f main.zip\")\n",
                        "if not os.path.exists(\"/kaggle/working/OmniVoice-Server\"):\n",
                        "    raise RuntimeError(\"Không tìm thấy thư mục giải nén /kaggle/working/OmniVoice-Server\")\n",
                        "print(\"[*] Chuẩn bị mã nguồn thành công!\")\n",
                        "os.system(\"ls -la /kaggle/working\")\n"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "import os, sys, subprocess\n",
                        "print(\"[*] Nâng cấp thư viện transformers và cài đặt omnivoice...\")\n",
                        "subprocess.run([sys.executable, \"-m\", \"pip\", \"install\", \"-U\", \"transformers\"])\n",
                        "os.chdir(\"/kaggle/working/OmniVoice-Server\")\n",
                        "subprocess.run([sys.executable, \"-m\", \"pip\", \"install\", \"-e\", \".\"])\n",
                        "\n",
                        "import subprocess\n",
                        "import re\n",
                        "import requests\n",
                        "import time\n",
                        "import sys\n",
                        "import os\n",
                        "\n",
                        "print(\"[*] Khởi động server...\")\n",
                        "env = os.environ.copy()\n",
                        "env[\"PYTHONPATH\"] = \"/kaggle/working/OmniVoice-Server:\" + env.get(\"PYTHONPATH\", \"\")\n",
                        "env[\"GRADIO_SERVER_PORT\"] = \"7860\"\n",
                        "env[\"PYTHONUNBUFFERED\"] = \"1\"\n",
                        "\n",
                        "process = subprocess.Popen(\n",
                        "    [\"python\", \"-u\", \"server_api/run_server.py\", \"--port\", \"7860\"],\n",
                        "    stdout=subprocess.PIPE,\n",
                        "    stderr=subprocess.STDOUT,\n",
                        "    text=True,\n",
                        "    bufsize=1,\n",
                        "    env=env\n",
                        ")\n",
                        "\n",
                        "def listen_control_signals():\n",
                        "    import requests\n",
                        "    import time\n",
                        "    import os\n",
                        f"    control_url = \"https://ntfy.sh/omnivoice_server_control_{self.kaggle_secret_id}/raw\"\n",
                        "    while True:\n",
                        "        try:\n",
                        "            res = requests.get(control_url, timeout=5)\n",
                        "            if res.status_code == 200 and \"SHUTDOWN\" in res.text:\n",
                        "                print(\"\\n[OmniVoice] Nhận được tín hiệu SHUTDOWN từ Client. Đang dừng server...\")\n",
                        "                try:\n",
                        "                    process.terminate()\n",
                        "                    time.sleep(2)\n",
                        "                    process.kill()\n",
                        "                except Exception:\n",
                        "                    pass\n",
                        "                os._exit(0)\n",
                        "        except Exception:\n",
                        "            pass\n",
                        "        time.sleep(5)\n",
                        "\n",
                        "import threading\n",
                        "threading.Thread(target=listen_control_signals, daemon=True).start()\n",
                        "\n",
                        "gradio_url_pattern = re.compile(r\"https://[a-zA-Z0-9-]+\\.gradio\\.live\")\n",
                        "link_sent = False\n",
                        "\n",
                        "for line in iter(process.stdout.readline, ''):\n",
                        "    sys.stdout.write(line)\n",
                        "    sys.stdout.flush()\n",
                        "    \n",
                        "    if not link_sent:\n",
                        "        match = gradio_url_pattern.search(line)\n",
                        "        if match:\n",
                        "            gradio_url = match.group(0).strip()\n",
                        "            print(f\"\\n[OmniVoice] Bắt được link Gradio: {gradio_url}\")\n",
                        "            try:\n",
                        f"                r = requests.post(\"https://ntfy.sh/omnivoice_server_link_{self.kaggle_secret_id}\", data=gradio_url)\n",
                        "                print(f\"[OmniVoice] Gửi link lên ntfy.sh thành công: {r.status_code}\")\n",
                        "                link_sent = True\n",
                        "            except Exception as e:\n",
                        "                print(f\"[OmniVoice] Lỗi gửi link lên ntfy.sh: {e}\")\n"
                    ]
                }
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3"
                },
                "language_info": {
                    "name": "python"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 2
        }
        gpu_acc_raw = getattr(self, 'kaggle_gpu', 'NvidiaTeslaT4')
        gpu_acc = "NvidiaTeslaT4" if gpu_acc_raw == "NvidiaTeslaT4x2" else gpu_acc_raw
        if gpu_acc:
            notebook_content["metadata"]["accelerator"] = gpu_acc
            notebook_content["metadata"]["kaggle"] = {
                "accelerator": gpu_acc,
                "isGpuEnabled": True,
                "isInternetEnabled": True
            }
        else:
            notebook_content["metadata"]["kaggle"] = {
                "isGpuEnabled": True,
                "isInternetEnabled": True
            }

        with open(os.path.join(build_dir, "omnivoice_server_kaggle.ipynb"), "w", encoding="utf-8") as f:
            json.dump(notebook_content, f, indent=2)

        # 5. Đẩy lên Kaggle qua Python API trực tiếp
        self.root.after(0, lambda: self.lbl_kaggle_status.configure(text="🟡 Đang đẩy Notebook lên Kaggle...", foreground="#FFB300"))
        self.log("[Kaggle] Đang đẩy notebook khởi chạy lên Kaggle...")
        
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            if gpu_acc:
                api.kernels_push(build_dir, acc=gpu_acc)
                self.log(f"[Kaggle] Đã đẩy notebook lên Kaggle thành công với GPU {getattr(self, 'kaggle_gpu', 'NvidiaTeslaT4')}. Đang chờ server khởi động...")
            else:
                api.kernels_push(build_dir)
                self.log("[Kaggle] Đã đẩy notebook lên Kaggle thành công (giữ nguyên cấu hình GPU trên Web UI). Đang chờ server khởi động...")
        except Exception as e:
            self.log(f"Kaggle API Push Error: {e}", "ERROR")
            self.disconnect_current_vpn()
            self.root.after(0, lambda: self.lbl_kaggle_status.configure(text="🔴 Lỗi đẩy code", foreground="#FF3366"))
            self.root.after(0, lambda: self.btn_start_kaggle.configure(state="normal"))
            return
            
        # 6. Bắt đầu lắng nghe link URL từ ntfy.sh
        self.root.after(0, lambda: self.lbl_kaggle_status.configure(text="🟡 Đang đợi GPU & link Gradio (1-3 phút)...", foreground="#FFB300"))
        
        # Reset link cũ trên ntfy.sh
        try:
            requests.post(f"https://ntfy.sh/omnivoice_server_link_{self.kaggle_secret_id}", data="")
        except Exception:
            pass
            
        # Khởi chạy luồng check URL Gradio
        self.kaggle_start_time = time.time()
        threading.Thread(target=self.check_kaggle_url_worker, daemon=True).start()

    def check_kaggle_url_worker(self):
        poll_url = f"https://ntfy.sh/omnivoice_server_link_{self.kaggle_secret_id}/raw?poll=1"
        self.log(f"[Kaggle] Bắt đầu dò tìm link Gradio Server...")
        
        while hasattr(self, 'active_kaggle_key') and self.active_kaggle_key:
            # Kiểm tra xem có bị quá thời gian timeout (5 phút) không
            elapsed = time.time() - self.kaggle_start_time
            if elapsed > 300:
                self.log("[Kaggle] Quá thời gian chờ (5 phút). Không nhận được link Gradio từ server.", "ERROR")
                self.disconnect_current_vpn()
                self.root.after(0, lambda: self.lbl_kaggle_status.configure(text="🔴 Timeout khởi động", foreground="#FF3366"))
                self.root.after(0, lambda: self.btn_start_kaggle.configure(state="normal"))
                return
                
            try:
                # Poll link bằng short polling, timeout nhanh 5s
                res = requests.get(poll_url, timeout=5)
                if res.status_code == 200 and res.text:
                    # Tìm tất cả link Gradio bằng regex
                    links = re.findall(r"https://\S+\.gradio\.live", res.text)
                    if links:
                        gradio_link = links[-1].strip() # Lấy link mới nhất
                        self.log(f"[Kaggle] Bắt được link Gradio hoạt động: {gradio_link}")
                        self.api_server_url_var.set(gradio_link)
                        self.api_server_url = gradio_link
                        self.save_config()
                        
                        self.root.after(0, lambda: self.lbl_kaggle_status.configure(text=f"🟢 Đang chạy: {gradio_link}", foreground="#00E676"))
                        self.root.after(0, lambda: self.btn_start_kaggle.configure(state="disabled"))
                        
                        # Ghi nhận thời gian bắt đầu chạy phiên này của API key
                        self.kaggle_session_start_time = time.time()
                        self.kaggle_key_active_status = True
                        
                        # Ngắt VPN ngay lập tức để người dùng dùng mạng thật
                        self.disconnect_current_vpn()
                        break
            except Exception as e:
                self.log(f"[Kaggle] Lỗi khi check ntfy.sh: {e}", "DEBUG")
            time.sleep(5)

    def stop_kaggle_server(self):
        self.btn_stop_kaggle.configure(state="disabled")
        self.lbl_kaggle_status.configure(text="🟡 Đang dừng Server Cloud...", foreground="#FFB300")
        self.log("[Kaggle] Đang gửi yêu cầu dừng Server Cloud...")
        
        # Gửi tín hiệu dừng nhanh qua internet (ntfy.sh)
        try:
            requests.post(f"https://ntfy.sh/omnivoice_server_control_{self.kaggle_secret_id}", data="SHUTDOWN", timeout=5)
        except Exception:
            pass
            
        def worker():
            # Đổi IP bằng VPN để gửi lệnh xóa
            self.connect_random_vpn()
            
            key = self.active_kaggle_key or self.kaggle_key_var.get().strip().split(",")[0].strip()
            if not key:
                self.disconnect_current_vpn()
                self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", "Không tìm thấy API Token để dừng server!"))
                self.root.after(0, lambda: self.btn_stop_kaggle.configure(state="normal"))
                return
                
            # Đảm bảo credentials được ghi nhận
            kaggle_dir = os.path.expanduser("~/.kaggle")
            os.makedirs(kaggle_dir, exist_ok=True)
            access_token_path = os.path.join(kaggle_dir, "access_token")
            try:
                with open(os.path.join(scratch_dir, "vieneu_tts_kaggle.py"), "r", encoding="utf-8") as f:
                    script_lines = f.readlines()
            except Exception as e:
                self.log(f"Lỗi đọc file kịch bản scratch/vieneu_tts_kaggle.py: {e}", "ERROR")
                self.disconnect_current_vpn()
                self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="normal"))
                return

            # Tạo cell
            cell_source = [
                "import os\n",
                f"os.environ['VIENEU_SECRET_ID'] = '{self.kaggle_flux_secret_id}'\n"
            ]
            cell_source.extend(script_lines)

            notebook_content = {
                "cells": [
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": cell_source
                    }
                ],
                "metadata": {
                    "accelerator": "NvidiaTeslaT4",
                    "kaggle": {
                        "accelerator": "NvidiaTeslaT4",
                        "isGpuEnabled": True,
                        "isInternetEnabled": True
                    },
                    "kernelspec": {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3"
                    },
                    "language_info": {
                        "name": "python"
                    }
                },
                "nbformat": 4,
                "nbformat_minor": 2
            }

            with open(os.path.join(build_dir, "vieneu_server_kaggle.ipynb"), "w", encoding="utf-8") as f:
                json.dump(notebook_content, f, indent=2)

            # 5. Đẩy lên Kaggle qua API
            self.root.after(0, lambda: self.lbl_kaggle_flux_status.configure(text="🟡 Đang đẩy Notebook lên Kaggle...", foreground="#FFB300"))
            self.log("[VieNeu-Kaggle] Đang đẩy notebook khởi chạy VieNeu-TTS 48kHz lên Kaggle...")
            
            duration = (time.time() - self.kaggle_session_start_time) / 3600.0
            key_data = self.kaggle_api_keys_data.setdefault(self.active_kaggle_key, {"total_hours": 0.0})
            key_data["total_hours"] += duration
            self.save_config()
            self.kaggle_key_active_status = False
                
            self.active_kaggle_key = None
            
            self.root.after(0, lambda: self.lbl_kaggle_status.configure(text="🔴 Trạng thái Cloud: Đang dừng", foreground="#FF3366"))
            self.root.after(0, lambda: self.btn_start_kaggle.configure(state="normal"))
            self.root.after(0, lambda: self.btn_stop_kaggle.configure(state="normal"))
            self.log("[Kaggle] Đã gửi lệnh dừng server và ngắt kết nối VPN.")
            
        threading.Thread(target=worker, daemon=True).start()

    # =====================================================================
    # VIENEU-TTS KAGGLE SERVER CONTROL (48kHz Voice AI)
    # =====================================================================
    def start_flux_kaggle_server_thread(self):
        self.btn_start_flux_kaggle.configure(state="disabled")
        self.btn_stop_flux_kaggle.configure(state="normal")
        threading.Thread(target=self.start_flux_kaggle_server_worker, daemon=True).start()

    def start_flux_kaggle_server_worker(self):
        raw_keys = self.txt_kaggle_flux_key.get("1.0", tk.END).strip() if hasattr(self, 'txt_kaggle_flux_key') else getattr(self, 'kaggle_flux_key', '')
        if not raw_keys:
            self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", "Vui lòng nhập Kaggle API Token cho VieNeu-TTS!"))
            self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="normal"))
            return

        import re
        keys_list = [k.strip() for k in re.split(r'[,\n\r]+', raw_keys) if k.strip()]
        if not keys_list:
            self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", "Vui lòng nhập ít nhất một Kaggle API Token VieNeu-TTS hợp lệ!"))
            self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="normal"))
            return

        raw_key = keys_list[0]
        self.active_kaggle_flux_key = raw_key
        self.log(f"[VieNeu-Kaggle] Bắt đầu khởi chạy server VieNeu-TTS 48kHz...")

        # 1. Đổi IP bằng VPN nếu có
        self.connect_random_vpn()

        # 2. Tạo tệp cấu hình xác thực Kaggle API
        kaggle_dir = os.path.expanduser("~/.kaggle")
        os.makedirs(kaggle_dir, exist_ok=True)
        access_token_path = os.path.join(kaggle_dir, "access_token")
        try:
            with open(access_token_path, "w", encoding="utf-8") as f:
                f.write(raw_key)
        except Exception as e:
            self.log(f"Lỗi ghi file access_token: {e}", "ERROR")

        os.environ["KAGGLE_API_TOKEN"] = raw_key

        # 3. Tự động introspect username
        self.root.after(0, lambda: self.lbl_kaggle_flux_status.configure(text="🟡 Đang xác thực tài khoản...", foreground="#FFB300"))
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            username = api.config_values.get('username')
            if not username:
                raise ValueError("Không lấy được username từ introspect token")
            self.kaggle_flux_username = username
            self.save_config()
            self.log(f"[VieNeu-Kaggle] Xác thực thành công. Username: {username}")
        except Exception as e:
            self.log(f"[VieNeu-Kaggle] Lỗi introspect Kaggle Username từ API Token: {e}", "ERROR")
            self.disconnect_current_vpn()
            self.root.after(0, lambda: messagebox.showerror("Lỗi xác thực", f"Lỗi xác thực Kaggle API Token:\n{e}"))
            self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="normal"))
            return

        import uuid
        self.kaggle_flux_secret_id = f"vieneu_{uuid.uuid4().hex[:8]}"
        self.save_config()

        # 4. Chuẩn bị thư mục và tệp notebook đẩy lên Kaggle
        build_dir = os.path.join(current_dir, "kaggle_vieneu_build")
        os.makedirs(build_dir, exist_ok=True)

        meta = {
            "id": f"{self.kaggle_flux_username}/omnivoice-vieneu-tts",
            "title": "omnivoice-vieneu-tts",
            "code_file": "omnivoice_vieneu_kaggle.ipynb",
            "language": "python",
            "kernel_type": "notebook",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": []
        }
        meta["machine_shape"] = "NvidiaTeslaT4"
        with open(os.path.join(build_dir, "kernel-metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        # Đọc mã nguồn từ scratch/vieneu_tts_kaggle.py để đẩy trực tiếp vào Notebook cell
        base_dir = getattr(sys, '_MEIPASS', current_dir)
        script_path = os.path.join(base_dir, "scratch", "vieneu_tts_kaggle.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(current_dir, "scratch", "vieneu_tts_kaggle.py")

        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script_lines = f.readlines()
        except Exception as e:
            self.log(f"Lỗi đọc file kịch bản {script_path}: {e}", "ERROR")
            self.disconnect_current_vpn()
            self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="normal"))
            return

        # Tạo cell
        cell_source = [
            "import os\n",
            f"os.environ['VIENEU_SECRET_ID'] = '{self.kaggle_flux_secret_id}'\n"
        ]
        cell_source.extend(script_lines)

        notebook_content = {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": cell_source
                }
            ],
            "metadata": {
                "accelerator": "NvidiaTeslaT4",
                "kaggle": {
                    "accelerator": "NvidiaTeslaT4",
                    "isGpuEnabled": True,
                    "isInternetEnabled": True
                },
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3"
                },
                "language_info": {
                    "name": "python"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 2
        }

        with open(os.path.join(build_dir, "omnivoice_vieneu_kaggle.ipynb"), "w", encoding="utf-8") as f:
            json.dump(notebook_content, f, indent=2)

        # 5. Đẩy lên Kaggle qua API
        self.root.after(0, lambda: self.lbl_kaggle_flux_status.configure(text="🟡 Đang đẩy Notebook VieNeu lên Kaggle...", foreground="#FFB300"))
        self.log("[VieNeu-Kaggle] Đang đẩy notebook khởi chạy VieNeu-TTS 48kHz lên Kaggle...")

        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            try:
                api.kernels_delete(kernel=f"{self.kaggle_flux_username}/omnivoice-vieneu-tts", no_confirm=True)
                time.sleep(1)
            except Exception:
                pass
            api.kernels_push(build_dir, acc="NvidiaTeslaT4")
            self.log(f"[VieNeu-Kaggle] Đẩy notebook thành công. Đang chờ VieNeu-TTS server khởi động...")
        except Exception as e:
            self.log(f"Kaggle API Push Error (VieNeu): {e}", "ERROR")
            self.disconnect_current_vpn()
            self.root.after(0, lambda: self.lbl_kaggle_flux_status.configure(text="🔴 Lỗi đẩy code", foreground="#FF3366"))
            self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="normal"))
            return

        # 6. Lắng nghe link URL từ ntfy.sh
        self.root.after(0, lambda: self.lbl_kaggle_flux_status.configure(text="🟡 Đang đợi GPU & link VieNeu (1-2 phút)...", foreground="#FFB300"))
        self.kaggle_flux_start_time = time.time()
        threading.Thread(target=self.check_flux_kaggle_url_worker, daemon=True).start()

    def check_flux_kaggle_url_worker(self):
        poll_url = f"https://ntfy.sh/omnivoice_control_{self.kaggle_flux_secret_id}/raw?poll=1"
        self.log(f"[VieNeu-Kaggle] Bắt đầu dò tìm link VieNeu-TTS Cloud Server...")

        while hasattr(self, 'active_kaggle_flux_key') and self.active_kaggle_flux_key:
            elapsed = time.time() - self.kaggle_flux_start_time
            if elapsed > 300:
                self.log("[VieNeu-Kaggle] Quá thời gian chờ (5 phút). Không nhận được link từ VieNeu server.", "ERROR")
                self.disconnect_current_vpn()
                self.root.after(0, lambda: self.lbl_kaggle_flux_status.configure(text="🔴 Timeout khởi động", foreground="#FF3366"))
                self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="normal"))
                return

            try:
                res = requests.get(poll_url, timeout=5)
                if res.status_code == 200 and res.text:
                    if "TUNNEL_URL:" in res.text:
                        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", res.text)
                        if match:
                            tunnel_link = match.group(0).strip()
                            self.log(f"[VieNeu-Kaggle] Bắt được link VieNeu-TTS 48kHz hoạt động: {tunnel_link}")
                            self.flux_server_url_var.set(tunnel_link)
                            self.save_config()

                            self.root.after(0, lambda: self.lbl_kaggle_flux_status.configure(text=f"🟢 Đang chạy: {tunnel_link}", foreground="#00E676"))
                            self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="disabled"))
                            
                            self.kaggle_flux_key_active_status = True
                            self.disconnect_current_vpn()
                            break
            except Exception as e:
                self.log(f"[VieNeu-Kaggle] Lỗi khi check ntfy.sh: {e}", "DEBUG")
            time.sleep(5)

    def stop_flux_kaggle_server(self):
        self.btn_stop_flux_kaggle.configure(state="disabled")
        self.lbl_kaggle_flux_status.configure(text="🟡 Đang dừng Server VieNeu-TTS...", foreground="#FFB300")
        self.log("[VieNeu-Kaggle] Đang gửi yêu cầu dừng Server VieNeu-TTS...")

        # 1. Reset biến trạng thái và xóa URL ngay lập tức
        self.active_kaggle_flux_key = None
        self.kaggle_flux_key_active_status = False
        if hasattr(self, 'flux_server_url_var'):
            self.flux_server_url_var.set("")
        self.save_config()

        # 2. Gửi lệnh SHUTDOWN khẩn cấp qua ntfy.sh
        try:
            requests.post(f"https://ntfy.sh/omnivoice_control_{self.kaggle_flux_secret_id}", data="SHUTDOWN", timeout=5)
        except Exception:
            pass

        def worker():
            self.connect_random_vpn()
            raw_keys = self.txt_kaggle_flux_key.get("1.0", tk.END).strip() if hasattr(self, 'txt_kaggle_flux_key') else getattr(self, 'kaggle_flux_key', '')
            import re
            keys_list = [k.strip() for k in re.split(r'[,\n\r]+', raw_keys) if k.strip()]
            key = keys_list[0] if keys_list else self.kaggle_flux_key_var.get().strip()
            if not key:
                self.disconnect_current_vpn()
                self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", "Không tìm thấy API Token để dừng server!"))
                self.root.after(0, lambda: self.btn_stop_flux_kaggle.configure(state="normal"))
                return

            kaggle_dir = os.path.expanduser("~/.kaggle")
            os.makedirs(kaggle_dir, exist_ok=True)
            access_token_path = os.path.join(kaggle_dir, "access_token")
            try:
                with open(access_token_path, "w", encoding="utf-8") as f:
                    f.write(key)
            except Exception:
                pass
            os.environ["KAGGLE_API_TOKEN"] = key

            username = getattr(self, 'kaggle_flux_username', None)
            try:
                from kaggle.api.kaggle_api_extended import KaggleApi
                api = KaggleApi()
                api.authenticate()
                fetched_user = api.config_values.get('username')
                if fetched_user:
                    username = fetched_user
                    self.kaggle_flux_username = fetched_user
            except Exception as e:
                self.log(f"[VieNeu-Kaggle] Lỗi lấy thông tin username khi dừng: {e}", "WARNING")

            if username and username != "unknown":
                try:
                    from kaggle.api.kaggle_api_extended import KaggleApi
                    api = KaggleApi()
                    api.authenticate()
                    api.kernels_delete(kernel=f"{username}/omnivoice-vieneu-tts", no_confirm=True)
                    self.log(f"[VieNeu-Kaggle] Đã xóa notebook ({username}/omnivoice-vieneu-tts) trên Kaggle giải phóng GPU.")
                except Exception as e:
                    self.log(f"[VieNeu-Kaggle] Kết quả xóa notebook (có thể đã dừng): {e}", "DEBUG")

            self.disconnect_current_vpn()

            self.root.after(0, lambda: self.lbl_kaggle_flux_status.configure(text="🔴 Trạng thái VieNeu Cloud: Đang dừng", foreground="#FF3366"))
            self.root.after(0, lambda: self.btn_start_flux_kaggle.configure(state="normal"))
            self.root.after(0, lambda: self.btn_stop_flux_kaggle.configure(state="normal"))
            self.log("[VieNeu-Kaggle] Đã dừng server VieNeu-TTS và ngắt kết nối VPN thành công.")

        threading.Thread(target=worker, daemon=True).start()

    def start_backup_kaggle_server(self, target_key):
        self.log(f"[Kaggle-Backup] Đang khởi chạy server dự phòng bằng API Key có thời gian tích lũy: {self.kaggle_api_keys_data.get(target_key, {}).get('total_hours', 0.0):.2f} giờ...")
        
        def worker():
            # 1. Kết nối VPN đổi IP
            self.connect_random_vpn()
            
            # 2. Ghi access_token
            kaggle_dir = os.path.expanduser("~/.kaggle")
            os.makedirs(kaggle_dir, exist_ok=True)
            access_token_path = os.path.join(kaggle_dir, "access_token")
            try:
                with open(access_token_path, "w", encoding="utf-8") as f:
                    f.write(target_key)
            except Exception:
                pass
            os.environ["KAGGLE_API_TOKEN"] = target_key
            
            # 3. Introspect username cho backup
            backup_username = "unknown"
            try:
                from kaggle.api.kaggle_api_extended import KaggleApi
                api = KaggleApi()
                api.authenticate()
                backup_username = api.config_values.get('username') or "unknown"
            except Exception as e:
                self.log(f"[Kaggle-Backup] Lỗi introspect API Token dự phòng: {e}", "ERROR")
                self.disconnect_current_vpn()
                return
                
            build_dir = os.path.join(current_dir, "kaggle_build_backup")
            os.makedirs(build_dir, exist_ok=True)
            
            meta = {
                "id": f"{backup_username}/omnivoice-server-api",
                "title": "OmniVoice Server API",
                "code_file": "omnivoice_server_kaggle.ipynb",
                "language": "python",
                "kernel_type": "notebook",
                "is_private": True,
                "enable_gpu": True,
                "enable_internet": True,
                "dataset_sources": [],
                "competition_sources": [],
                "kernel_sources": [],
                "model_sources": []
            }
            gpu_acc_raw = getattr(self, 'kaggle_gpu', 'NvidiaTeslaT4')
            gpu_acc = "NvidiaTeslaT4" if gpu_acc_raw == "NvidiaTeslaT4x2" else gpu_acc_raw
            if gpu_acc:
                meta["machine_shape"] = gpu_acc
            with open(os.path.join(build_dir, "kernel-metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
                
            notebook_content = {
                "cells": [
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": [
                            "import os\n",
                            "import sys\n",
                            "print(\"[*] Đang tải mã nguồn OmniVoice-Server từ GitHub...\")\n",
                            "os.system(\"rm -rf /kaggle/working/OmniVoice-Server OmniVoice-Server-main OmniVoice-Server-master main.zip\")\n",
                            "ret = os.system(\"wget https://github.com/danghai-245/OmniVoice-Server/archive/refs/heads/main.zip -O main.zip\")\n",
                            "if ret != 0:\n",
                            "    ret = os.system(\"wget https://github.com/danghai-245/OmniVoice-Server/archive/refs/heads/master.zip -O main.zip\")\n",
                            "if not os.path.exists(\"main.zip\") or os.path.getsize(\"main.zip\") < 1000:\n",
                            "    print(\"\\n\" + \"=\"*80)\n",
                            "    print(\"[ERROR] KHÔNG THỂ TẢI MÃ NGUỒN OMNIVOICE SERVER!\")\n",
                            "    print(\"Nguyên nhân: File zip tải về không tồn tại hoặc dung lượng quá nhỏ.\")\n",
                            "    print(\"Vui lòng kiểm tra:\")\n",
                            "    print(\"  1. Repository 'danghai-245/OmniVoice-Server' của bạn có đang ở chế độ PRIVATE hay không?\")\n",
                            "    print(\"     -> Nếu có, vui lòng chuyển sang PUBLIC trên GitHub để Kaggle có thể tải về.\")\n",
                            "    print(\"  2. Tên tài khoản GitHub hoặc tên Repository trong URL có bị viết sai chính tả hay không?\")\n",
                            "    print(\"=\"*80 + \"\\n\")\n",
                            "    raise RuntimeError(\"Tải mã nguồn thất bại - Repo có thể đang là Private.\")\n",
                            "print(\"[*] Đang giải nén mã nguồn...\")\n",
                            "ret_unzip = os.system(\"unzip main.zip\")\n",
                            "if ret_unzip != 0:\n",
                            "    raise RuntimeError(\"Giải nén mã nguồn thất bại.\")\n",
                            "os.system(\"mv OmniVoice-Server-* /kaggle/working/OmniVoice-Server\")\n",
                            "os.system(\"rm -f main.zip\")\n",
                            "if not os.path.exists(\"/kaggle/working/OmniVoice-Server\"):\n",
                            "    raise RuntimeError(\"Không tìm thấy thư mục giải nén /kaggle/working/OmniVoice-Server\")\n",
                            "print(\"[*] Chuẩn bị mã nguồn thành công!\")\n",
                            "os.system(\"ls -la /kaggle/working\")\n"
                        ]
                    },
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": [
                            "import os, sys, subprocess\n",
                            "print(\"[*] Nâng cấp thư viện transformers và cài đặt omnivoice...\")\n",
                            "subprocess.run([sys.executable, \"-m\", \"pip\", \"install\", \"-U\", \"transformers\"])\n",
                            "os.chdir(\"/kaggle/working/OmniVoice-Server\")\n",
                            "subprocess.run([sys.executable, \"-m\", \"pip\", \"install\", \"-e\", \".\"])\n",
                            "\n",
                            "import subprocess\n",
                            "import re\n",
                            "import requests\n",
                            "import time\n",
                            "import sys\n",
                            "import os\n",
                            "\n",
                            "print(\"[*] Khởi động server...\")\n",
                            "env = os.environ.copy()\n",
                            "env[\"PYTHONPATH\"] = \"/kaggle/working/OmniVoice-Server:\" + env.get(\"PYTHONPATH\", \"\")\n",
                            "env[\"GRADIO_SERVER_PORT\"] = \"7860\"\n",
                            "env[\"PYTHONUNBUFFERED\"] = \"1\"\n",
                            "\n",
                            "process = subprocess.Popen(\n",
                            "    [\"python\", \"-u\", \"server_api/run_server.py\", \"--port\", \"7860\"],\n",
                            "    stdout=subprocess.PIPE,\n",
                            "    stderr=subprocess.STDOUT,\n",
                            "    text=True,\n",
                            "    bufsize=1,\n",
                            "    env=env\n",
                            ")\n",
                            "\n",
                            "def listen_control_signals():\n",
                            "    import requests\n",
                            "    import time\n",
                            "    import os\n",
                            f"    control_url = \"https://ntfy.sh/omnivoice_server_control_{self.next_kaggle_secret_id}\"\n",
                            "    while True:\n",
                            "        try:\n",
                            "            res = requests.get(control_url, timeout=5)\n",
                            "            if res.status_code == 200 and \"SHUTDOWN\" in res.text:\n",
                            "                print(\"\\n[OmniVoice] Nhận được tín hiệu SHUTDOWN từ Client. Đang dừng server dự phòng...\")\n",
                            "                try:\n",
                            "                    process.terminate()\n",
                            "                    time.sleep(2)\n",
                            "                    process.kill()\n",
                            "                except Exception:\n",
                            "                    pass\n",
                            "                os._exit(0)\n",
                            "        except Exception:\n",
                            "            pass\n",
                            "        time.sleep(5)\n",
                            "\n",
                            "import threading\n",
                            "threading.Thread(target=listen_control_signals, daemon=True).start()\n",
                            "\n",
                            "gradio_url_pattern = re.compile(r\"https://[a-zA-Z0-9-]+\\.gradio\\.live\")\n",
                            "link_sent = False\n",
                            "\n",
                            "for line in iter(process.stdout.readline, ''):\n",
                            "    sys.stdout.write(line)\n",
                            "    sys.stdout.flush()\n",
                            "    \n",
                            "    if not link_sent:\n",
                            "        match = gradio_url_pattern.search(line)\n",
                            "        if match:\n",
                            "            gradio_url = match.group(0).strip()\n",
                            "            print(f\"\\n[OmniVoice] Bắt được link Gradio: {gradio_url}\")\n",
                            "            try:\n",
                            f"                r = requests.post(\"https://ntfy.sh/omnivoice_server_link_{self.next_kaggle_secret_id}\", data=gradio_url)\n",
                            "                print(f\"[OmniVoice] Gửi link lên ntfy.sh thành công: {r.status_code}\")\n",
                            "                link_sent = True\n",
                            "            except Exception as e:\n",
                            "                print(f\"[OmniVoice] Lỗi gửi link lên ntfy.sh: {e}\")\n"
                        ]
                    }
                ],
                "metadata": {
                    "kernelspec": {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3"
                    },
                    "language_info": {
                        "name": "python"
                    }
                },
                "nbformat": 4,
                "nbformat_minor": 2
            }
            gpu_acc_raw = getattr(self, 'kaggle_gpu', 'NvidiaTeslaT4')
            gpu_acc = "NvidiaTeslaT4" if gpu_acc_raw == "NvidiaTeslaT4x2" else gpu_acc_raw
            if gpu_acc:
                notebook_content["metadata"]["accelerator"] = gpu_acc
                notebook_content["metadata"]["kaggle"] = {
                    "accelerator": gpu_acc,
                    "isGpuEnabled": True,
                    "isInternetEnabled": True
                }
            else:
                notebook_content["metadata"]["kaggle"] = {
                    "isGpuEnabled": True,
                    "isInternetEnabled": True
                }
            with open(os.path.join(build_dir, "omnivoice_server_kaggle.ipynb"), "w", encoding="utf-8") as f:
                json.dump(notebook_content, f, indent=2)
                
            # Đẩy notebook dự phòng lên qua Python API trực tiếp
            try:
                from kaggle.api.kaggle_api_extended import KaggleApi
                api = KaggleApi()
                api.authenticate()
                if gpu_acc:
                    api.kernels_push(build_dir, acc=gpu_acc)
                else:
                    api.kernels_push(build_dir)
                self.log(f"[Kaggle-Backup] Đã đẩy notebook dự phòng lên thành công với GPU {getattr(self, 'kaggle_gpu', 'NvidiaTeslaT4')}. Đang chờ server dự phòng khởi động...")
            except Exception as e:
                self.log(f"[Kaggle-Backup] Lỗi đẩy code dự phòng: {e}", "ERROR")
                self.disconnect_current_vpn()
                self.next_kaggle_key = None
                self.next_kaggle_secret_id = None
                return
                
            # Đăng ký thời điểm bắt đầu để tính timeout cho backup
            self.backup_start_time = time.time()
            self.backup_ready = False
            
            # Chạy loop ngầm kiểm tra URL của backup
            def check_backup_url():
                poll_url = f"https://ntfy.sh/omnivoice_server_link_{self.next_kaggle_secret_id}/raw?poll=1"
                while self.next_kaggle_key == target_key:
                    if time.time() - self.backup_start_time > 300:
                        self.log("[Kaggle-Backup] Hết thời gian chờ server dự phòng (5 phút). Hủy kích hoạt dự phòng.", "ERROR")
                        self.disconnect_current_vpn()
                        self.next_kaggle_key = None
                        self.next_kaggle_secret_id = None
                        return
                    try:
                        res = requests.get(poll_url, timeout=5)
                        if res.status_code == 200 and res.text:
                            links = re.findall(r"https://\S+\.gradio\.live", res.text)
                            if links:
                                link = links[-1].strip()
                                self.log(f"[Kaggle-Backup] Server dự phòng đã sẵn sàng tại link: {link}")
                                self.backup_ready_url = link
                                self.backup_ready = True
                                self.disconnect_current_vpn()
                                break
                    except Exception as e:
                        self.log(f"[Kaggle-Backup] Lỗi khi check ntfy.sh: {e}", "DEBUG")
                    time.sleep(5)
            threading.Thread(target=check_backup_url, daemon=True).start()

        threading.Thread(target=worker, daemon=True).start()

    def stop_specific_kaggle_server(self, target_key):
        self.log(f"[Kaggle] Đang gửi lệnh tắt server cũ của API key...")
        
        # Gửi tín hiệu dừng nhanh qua ntfy.sh
        try:
            requests.post(f"https://ntfy.sh/omnivoice_server_control_{self.kaggle_secret_id}", data="SHUTDOWN", timeout=5)
        except Exception:
            pass
            
        def worker():
            # Đổi IP bằng VPN để gửi lệnh xóa
            self.connect_random_vpn()
            
            kaggle_dir = os.path.expanduser("~/.kaggle")
            os.makedirs(kaggle_dir, exist_ok=True)
            access_token_path = os.path.join(kaggle_dir, "access_token")
            try:
                with open(access_token_path, "w", encoding="utf-8") as f:
                    f.write(target_key)
            except Exception:
                pass
            os.environ["KAGGLE_API_TOKEN"] = target_key
            
            # Lấy username
            username = "unknown"
            try:
                from kaggle.api.kaggle_api_extended import KaggleApi
                api = KaggleApi()
                api.authenticate()
                username = api.config_values.get('username') or "unknown"
            except Exception:
                pass
                
            # Xóa notebook cũ của API key cũ qua Python API trực tiếp (no_confirm=True)
            if username and username != "unknown":
                try:
                    from kaggle.api.kaggle_api_extended import KaggleApi
                    api = KaggleApi()
                    api.authenticate()
                    api.kernels_delete(kernel=f"{username}/omnivoice-server-api", no_confirm=True)
                    self.log(f"[Kaggle] Đã gửi lệnh delete xóa notebook cũ của API key cũ thành công.")
                except Exception as e:
                    self.log(f"[Kaggle] Kết quả xóa notebook cũ thất bại: {e}", "DEBUG")
            
            # Ngắt VPN
            self.disconnect_current_vpn()
                
        threading.Thread(target=worker, daemon=True).start()

    def monitor_kaggle_usage(self):
        try:
            self.check_and_reset_kaggle_quota()
            if getattr(self, 'kaggle_key_active_status', False) and self.active_kaggle_key:
                # Tính thời gian chạy tích lũy của key hoạt động chính
                session_duration = (time.time() - self.kaggle_session_start_time) / 3600.0
                total_hours = self.active_key_initial_hours + session_duration
                
                # Cập nhật vào dictionary
                key_data = self.kaggle_api_keys_data.setdefault(self.active_kaggle_key, {"total_hours": 0.0})
                key_data["total_hours"] = total_hours
                self.save_config()
                
                # Điều kiện xoay API 1: tổng thời gian của API key tích lũy
                # Đạt 29.0 giờ: bật backup server
                if total_hours >= 29.0 and total_hours < 29.5:
                    if not self.next_kaggle_key:
                        raw_keys = self.kaggle_key_var.get().strip()
                        keys_list = [k.strip() for k in raw_keys.split(",") if k.strip()]
                        for k in keys_list:
                            if k != self.active_kaggle_key and self.kaggle_api_keys_data.get(k, {}).get("total_hours", 0.0) < 29.5:
                                self.next_kaggle_key = k
                                self.next_kaggle_secret_id = f"omni_{uuid.uuid4().hex[:8]}"
                                self.start_backup_kaggle_server(k)
                                break
                                
                # Đạt 29.5 giờ: chuyển link và tắt server cũ
                elif total_hours >= 29.5:
                    if self.next_kaggle_key and getattr(self, 'backup_ready', False):
                        next_url = self.backup_ready_url
                        self.api_server_url = next_url
                        self.api_server_url_var.set(next_url)
                        
                        self.stop_specific_kaggle_server(self.active_kaggle_key)
                        
                        self.active_kaggle_key = self.next_kaggle_key
                        self.kaggle_secret_id = self.next_kaggle_secret_id
                        self.kaggle_session_start_time = time.time()
                        self.active_key_initial_hours = self.kaggle_api_keys_data.get(self.active_kaggle_key, {}).get("total_hours", 0.0)
                        
                        self.next_kaggle_key = None
                        self.next_kaggle_secret_id = None
                        self.backup_ready = False
                        
                        self.root.after(0, lambda url=next_url: self.lbl_kaggle_status.configure(text=f"🟢 Đang chạy (Xoay key): {url}", foreground="#00E676"))
                        self.log(f"[Kaggle] Đã đạt 29.5 giờ tích lũy. Tự động xoay API sang key mới và chuyển hướng link: {next_url}")
                        self.save_config()
                
                # Điều kiện xoay API 2: Phiên chạy liên tục (session)
                # Đạt 11.0 giờ: bật backup server
                if session_duration >= 11.0 and session_duration < 11.5:
                    if not self.next_kaggle_key:
                        raw_keys = self.txt_kaggle_key.get("1.0", tk.END).strip() if hasattr(self, 'txt_kaggle_key') else getattr(self, 'kaggle_key', '')
                        import re
                        keys_list = [k.strip() for k in re.split(r'[,\n\r]+', raw_keys) if k.strip()]
                        for k in keys_list:
                            if k != self.active_kaggle_key and self.kaggle_api_keys_data.get(k, {}).get("total_hours", 0.0) < 29.5:
                                self.next_kaggle_key = k
                                self.next_kaggle_secret_id = f"omni_{uuid.uuid4().hex[:8]}"
                                self.start_backup_kaggle_server(k)
                                break
                                
                # Đạt 11.5 giờ: chuyển link và tắt server cũ
                elif session_duration >= 11.5:
                    if self.next_kaggle_key and getattr(self, 'backup_ready', False):
                        next_url = self.backup_ready_url
                        self.api_server_url = next_url
                        self.api_server_url_var.set(next_url)
                        
                        self.stop_specific_kaggle_server(self.active_kaggle_key)
                        
                        self.active_kaggle_key = self.next_kaggle_key
                        self.kaggle_secret_id = self.next_kaggle_secret_id
                        self.kaggle_session_start_time = time.time()
                        self.active_key_initial_hours = self.kaggle_api_keys_data.get(self.active_kaggle_key, {}).get("total_hours", 0.0)
                        
                        self.next_kaggle_key = None
                        self.next_kaggle_secret_id = None
                        self.backup_ready = False
                        
                        self.root.after(0, lambda url=next_url: self.lbl_kaggle_status.configure(text=f"🟢 Đang chạy (Xoay session): {url}", foreground="#00E676"))
                        self.log(f"[Kaggle] Phiên chạy liên tục đạt 11.5 giờ. Tự động xoay API và chuyển hướng link: {next_url}")
                        self.save_config()
                        
        except Exception as e:
            self.log(f"[Kaggle] Lỗi trong tiến trình giám sát monitor_kaggle_usage: {e}", "ERROR")
            
        self.root.after(30000, self.monitor_kaggle_usage)

    def open_output_folder(self):
        try:
            # Mở thư mục chứa file đầu ra bằng File Explorer trên Windows
            os.startfile(output_dir)
            self.log(f"Đã mở thư mục outputs: {output_dir}")
        except Exception as e:
            self.log(f"Lỗi mở thư mục: {e}", "ERROR")

    # =====================================================================
    # FLUX & COMFYUI TÍCH HỢP
    # =====================================================================
    def build_flux_tab(self):
        # Container chính
        container = ttk.Frame(self.tab_flux, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        
        # PanedWindow chia 2 cột trái phải
        pane = tk.PanedWindow(container, orient=tk.HORIZONTAL, bg="#E9ECEF", bd=0, sashwidth=4)
        pane.pack(fill=tk.BOTH, expand=True)
        
        left_col = ttk.Frame(pane, padding=(0, 0, 5, 0))
        right_col = ttk.Frame(pane, padding=(5, 0, 0, 0))
        
        pane.add(left_col, minsize=460)
        pane.add(right_col, minsize=400)
        
        # --- CỘT TRÁI: CẤU HÌNH ---
        # 1. Cấu hình Connection
        card_conn = ttk.LabelFrame(left_col, text=" 🔗 Kết nối ComfyUI Server ", padding=10)
        card_conn.pack(fill=tk.X, pady=(0, 10))
        
        f_conn_url = ttk.Frame(card_conn)
        f_conn_url.pack(fill=tk.X, pady=2)
        ttk.Label(f_conn_url, text="Địa chỉ Server URL:").pack(side=tk.LEFT, padx=(0, 5))
        self.ent_flux_url = ttk.Entry(f_conn_url, textvariable=self.flux_server_url_var, width=30)
        self.ent_flux_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        btn_detect = ttk.Button(f_conn_url, text="🔌 Kết nối", command=self.connect_flux_server, width=10)
        btn_detect.pack(side=tk.RIGHT)
        
        self.lbl_flux_conn_status = ttk.Label(card_conn, text="Trạng thái: Chưa kiểm tra kết nối", foreground="#6C757D", font=("Segoe UI", 9, "italic"))
        self.lbl_flux_conn_status.pack(anchor=tk.W, pady=(5, 0))
        
        # 1.5 Lựa chọn Mô hình AI
        card_model = ttk.LabelFrame(left_col, text=" 🤖 Lựa chọn Mô hình AI (AI Engine) ", padding=10)
        card_model.pack(fill=tk.X, pady=(0, 10))
        
        f_model_combo = ttk.Frame(card_model)
        f_model_combo.pack(fill=tk.X, pady=2)
        ttk.Label(f_model_combo, text="Dòng AI Model:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.model_options = [
            "Flux.1 Schnell (Flux Redux)",
            "SDXL InstantID (Giữ nét mặt 99% - Tốt nhất)",
            "SD 1.5 IP-Adapter (Siêu nhẹ & Nhanh)"
        ]
        
        self.flux_model_choice_var = tk.StringVar(value=self.model_options[0])
        self.combo_flux_model = ttk.Combobox(f_model_combo, textvariable=self.flux_model_choice_var, values=self.model_options, state="readonly", width=34)
        self.combo_flux_model.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.combo_flux_model.bind("<<ComboboxSelected>>", self.on_flux_model_choice_changed)
        
        self.lbl_model_desc_var = tk.StringVar(value="✨ Mô hình Flux thế hệ mới nhất cho chi tiết điện ảnh, ánh sáng tuyệt đẹp. Sử dụng Flux Redux để tham chiếu phong cách & nhân vật.")
        self.lbl_model_desc = ttk.Label(card_model, textvariable=self.lbl_model_desc_var, foreground="#495057", font=("Segoe UI", 8, "italic"), wraplength=380, justify=tk.LEFT)
        self.lbl_model_desc.pack(anchor=tk.W, pady=(5, 0))
        
        # 2. Nhập Prompt
        card_prompt = ttk.LabelFrame(left_col, text=" 📝 Miêu tả hình ảnh (Prompt) ", padding=10)
        card_prompt.pack(fill=tk.X, pady=(0, 10))
        
        self.txt_flux_prompt = tk.Text(card_prompt, height=6, bg="#FFFFFF", fg="#212529", insertbackground="black", font=("Segoe UI", 10), wrap=tk.WORD)
        self.txt_flux_prompt.pack(fill=tk.X, pady=2)
        self.txt_flux_prompt.insert(tk.END, "A cinematic shot of a futuristic city with flying cars, neon lights, high detail, 8k resolution, photorealistic")
        
        f_batch = ttk.Frame(card_prompt)
        f_batch.pack(fill=tk.X, pady=(5, 0))
        
        self.flux_batch_mode_var = tk.BooleanVar(value=False)
        self.chk_flux_batch = ttk.Checkbutton(f_batch, text="Chạy hàng loạt (mỗi dòng 1 prompt)", variable=self.flux_batch_mode_var)
        self.chk_flux_batch.pack(side=tk.LEFT)
        
        btn_import_prompt = ttk.Button(f_batch, text="📁 Nhập file .txt", width=12, command=self.import_flux_prompts)
        btn_import_prompt.pack(side=tk.RIGHT)
        
        # 3. Cấu hình thông số ảnh
        card_settings = ttk.LabelFrame(left_col, text=" ⚙️ Cấu hình thông số ảnh ", padding=10)
        card_settings.pack(fill=tk.X, pady=(0, 10))
        
        f_res = ttk.Frame(card_settings)
        f_res.pack(fill=tk.X, pady=4)
        ttk.Label(f_res, text="Tỷ lệ khung hình:").pack(side=tk.LEFT, padx=(0, 5))
        
        aspects = [
            "1:1 (Square) - 1024x1024",
            "16:9 (Landscape) - 1344x768",
            "9:16 (Portrait) - 768x1344",
            "4:3 (Photo) - 1024x768",
            "3:4 (Tall) - 768x1024"
        ]
        self.flux_aspect_ratio_var = tk.StringVar(value=aspects[0])
        self.combo_aspect = ttk.Combobox(f_res, textvariable=self.flux_aspect_ratio_var, values=aspects, state="readonly", width=30)
        self.combo_aspect.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.combo_aspect.bind("<<ComboboxSelected>>", self.on_flux_aspect_ratio_changed)
        
        f_wh = ttk.Frame(card_settings)
        f_wh.pack(fill=tk.X, pady=4)
        ttk.Label(f_wh, text="Chiều rộng (Width):").pack(side=tk.LEFT)
        self.flux_width_var = tk.StringVar(value="1024")
        self.lbl_flux_width = ttk.Label(f_wh, textvariable=self.flux_width_var, font=("Segoe UI", 9, "bold"))
        self.lbl_flux_width.pack(side=tk.LEFT, padx=(5, 20))
        
        ttk.Label(f_wh, text="Chiều cao (Height):").pack(side=tk.LEFT)
        self.flux_height_var = tk.StringVar(value="1024")
        self.lbl_flux_height = ttk.Label(f_wh, textvariable=self.flux_height_var, font=("Segoe UI", 9, "bold"))
        self.lbl_flux_height.pack(side=tk.LEFT, padx=5)
        
        f_steps = ttk.Frame(card_settings)
        f_steps.pack(fill=tk.X, pady=4)
        
        ttk.Label(f_steps, text="Số bước (Steps):").pack(side=tk.LEFT, padx=(0, 5))
        self.flux_steps_var = tk.StringVar(value="4")
        self.spn_flux_steps = ttk.Spinbox(f_steps, from_=1, to=50, increment=1, textvariable=self.flux_steps_var, width=8)
        self.spn_flux_steps.pack(side=tk.LEFT, padx=(0, 20))
        
        ttk.Label(f_steps, text="CFG Scale:").pack(side=tk.LEFT, padx=(0, 5))
        self.flux_cfg_var = tk.StringVar(value="1.0")
        self.spn_flux_cfg = ttk.Spinbox(f_steps, from_=1.0, to=20.0, increment=0.5, textvariable=self.flux_cfg_var, width=8)
        self.spn_flux_cfg.pack(side=tk.LEFT)
        
        f_seed = ttk.Frame(card_settings)
        f_seed.pack(fill=tk.X, pady=4)
        ttk.Label(f_seed, text="Seed (-1 để ngẫu nhiên):").pack(side=tk.LEFT, padx=(0, 5))
        self.flux_seed_var = tk.StringVar(value="-1")
        self.ent_flux_seed = ttk.Entry(f_seed, textvariable=self.flux_seed_var, width=15)
        self.ent_flux_seed.pack(side=tk.LEFT, padx=(0, 10))
        
        # 4. Ảnh tham chiếu (Flux Redux)
        card_ref = ttk.LabelFrame(left_col, text=" 🖼️ Ảnh tham chiếu nhân vật (Flux Redux) ", padding=10)
        card_ref.pack(fill=tk.X, pady=(0, 10))
        
        f_ref_file = ttk.Frame(card_ref)
        f_ref_file.pack(fill=tk.X, pady=2)
        
        self.flux_ref_image_var = tk.StringVar(value="Không sử dụng ảnh tham chiếu")
        self.lbl_flux_ref = ttk.Label(f_ref_file, textvariable=self.flux_ref_image_var, foreground="#6C757D", font=("Segoe UI", 9, "italic"), width=25, anchor=tk.W)
        self.lbl_flux_ref.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        btn_choose_ref = ttk.Button(f_ref_file, text="Chọn ảnh", command=self.choose_flux_ref_image, width=10)
        btn_choose_ref.pack(side=tk.RIGHT, padx=2)
        
        btn_clear_ref = ttk.Button(f_ref_file, text="Xóa", command=self.clear_flux_ref_image, width=6)
        btn_clear_ref.pack(side=tk.RIGHT)
        
        f_denoise = ttk.Frame(card_ref)
        f_denoise.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(f_denoise, text="Sức mạnh tham chiếu (Strength):").pack(side=tk.LEFT, padx=(0, 5))
        self.flux_denoise_var = tk.StringVar(value="0.25")
        self.spn_flux_denoise = ttk.Spinbox(f_denoise, from_=0.05, to=1.0, increment=0.05, textvariable=self.flux_denoise_var, width=8)
        self.spn_flux_denoise.pack(side=tk.LEFT)
        ttk.Label(f_denoise, text="(0.1: bám sát Prompt 90%, 0.5: cân bằng 50/50)", foreground="#6C757D", font=("Segoe UI", 8, "italic")).pack(side=tk.LEFT, padx=10)

        # Nút tạo ảnh và Dừng
        f_gen_actions = ttk.Frame(left_col)
        f_gen_actions.pack(fill=tk.X, pady=(5, 0))
        
        self.btn_flux_generate = ttk.Button(f_gen_actions, text="🎨 BẮT ĐẦU TẠO ẢNH AI", style="Accent.TButton", command=self.start_flux_generation)
        self.btn_flux_generate.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 5))
        
        self.btn_flux_stop = ttk.Button(f_gen_actions, text="🛑 DỪNG LẠI", style="Secondary.TButton", command=self.trigger_stop_flux_generation, state="disabled", width=12)
        self.btn_flux_stop.pack(side=tk.RIGHT, ipady=8)
        
        # --- CỘT PHẢI: XEM TRƯỚC ---
        card_preview = ttk.LabelFrame(right_col, text=" 🖼️ Xem trước & Tiến trình ", padding=10)
        card_preview.pack(fill=tk.BOTH, expand=True)
        
        # Trạng thái
        f_progress = ttk.Frame(card_preview)
        f_progress.pack(fill=tk.X, pady=(0, 5))
        self.flux_status_var = tk.StringVar(value="Sẵn sàng")
        self.lbl_flux_status = ttk.Label(f_progress, textvariable=self.flux_status_var, font=("Segoe UI", 10, "bold"), foreground="#00E676")
        self.lbl_flux_status.pack(side=tk.LEFT)
        
        # Thanh tiến trình
        self.flux_progress_var = tk.DoubleVar(value=0.0)
        self.bar_flux_progress = ttk.Progressbar(card_preview, variable=self.flux_progress_var, maximum=100, mode="determinate")
        self.bar_flux_progress.pack(fill=tk.X, pady=(0, 10))
        
        # Khung hiển thị ảnh
        self.lbl_flux_preview = ttk.Label(card_preview, text="Chưa có ảnh nào được tạo", background="#E9ECEF", anchor=tk.CENTER, relief="sunken")
        self.lbl_flux_preview.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Nút hành động
        f_actions = ttk.Frame(card_preview)
        f_actions.pack(fill=tk.X)
        self.btn_flux_save = ttk.Button(f_actions, text="💾 Lưu ảnh về máy", state="disabled", command=self.save_flux_image)
        self.btn_flux_save.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.btn_flux_folder = ttk.Button(f_actions, text="📂 Mở thư mục ảnh", command=self.open_flux_output_folder)
        self.btn_flux_folder.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))

    def on_flux_aspect_ratio_changed(self, event=None):
        val = self.flux_aspect_ratio_var.get()
        if "1024x1024" in val:
            self.flux_width_var.set("1024")
            self.flux_height_var.set("1024")
        elif "1344x768" in val:
            self.flux_width_var.set("1344")
            self.flux_height_var.set("768")
        elif "768x1344" in val:
            self.flux_width_var.set("768")
            self.flux_height_var.set("1344")
        elif "1024x768" in val:
            self.flux_width_var.set("1024")
            self.flux_height_var.set("768")
        elif "768x1024" in val:
            self.flux_width_var.set("768")
            self.flux_height_var.set("1024")

    def connect_flux_server(self):
        url = self.flux_server_url_var.get().strip()
        
        if ("127.0.0.1" in url or not url) and "Cloud API" in self.run_mode_var.get():
            self.lbl_flux_conn_status.configure(text="Đang quét tìm link Kaggle Server từ ntfy.sh...", foreground="#20C997")
            self.root.update_idletasks()
            try:
                secret_id = self.kaggle_secret_id
                if not secret_id:
                    secret_id = self.kaggle_secret_id_entry.get().strip() if hasattr(self, 'kaggle_secret_id_entry') else ""
                
                if secret_id:
                    poll_url = f"https://ntfy.sh/omnivoice_flux_link_{secret_id}/raw?poll=1"
                    res = requests.get(poll_url, timeout=3)
                    if res.status_code == 200 and res.text.strip():
                        detected_url = res.text.strip()
                        self.flux_server_url_var.set(detected_url)
                        url = detected_url
                        self.log(f"[Flux] Đã phát hiện link server Kaggle: {url}")
            except Exception as e:
                self.log(f"[Flux] Lỗi khi tự động dò tìm link server: {e}", "WARNING")
        
        if not url:
            self.lbl_flux_conn_status.configure(text="Trạng thái: Vui lòng nhập địa chỉ Server URL!", foreground="#DC3545")
            return
            
        if not url.startswith("http"):
            url = "http://" + url
            self.flux_server_url_var.set(url)
            
        def check_worker():
            try:
                res = requests.get(f"{url}/system_info", timeout=5)
                if res.status_code == 200:
                    self.root.after(0, lambda: self.lbl_flux_conn_status.configure(text="🟢 Đã kết nối thành công tới ComfyUI Server!", foreground="#00E676"))
                    self.root.after(0, self.save_config)
                else:
                    res2 = requests.get(f"{url}/queue", timeout=5)
                    if res2.status_code == 200:
                        self.root.after(0, lambda: self.lbl_flux_conn_status.configure(text="🟢 Đã kết nối thành công tới ComfyUI Server!", foreground="#00E676"))
                        self.root.after(0, self.save_config)
                    else:
                        self.root.after(0, lambda: self.lbl_flux_conn_status.configure(text=f"🔴 Lỗi kết nối (Mã lỗi: {res.status_code})", foreground="#DC3545"))
            except Exception as e:
                self.root.after(0, lambda: self.lbl_flux_conn_status.configure(text=f"🔴 Lỗi kết nối: {str(e)[:45]}...", foreground="#DC3545"))
                
        threading.Thread(target=check_worker, daemon=True).start()

    def choose_flux_ref_image(self):
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            title="Chọn ảnh tham chiếu",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.webp"), ("All files", "*.*")]
        )
        if file_path:
            self.flux_ref_image_path = file_path
            self.flux_ref_image_var.set(os.path.basename(file_path))
            self.log(f"[Flux] Đã chọn ảnh tham chiếu: {file_path}")
            
    def clear_flux_ref_image(self):
        self.flux_ref_image_path = ""
        self.flux_ref_image_var.set("Không sử dụng ảnh tham chiếu")
        self.log("[Flux] Đã xóa ảnh tham chiếu.")

    def on_flux_model_choice_changed(self, event=None):
        choice = self.flux_model_choice_var.get()
        if "Flux.1" in choice:
            self.lbl_model_desc_var.set("✨ Mô hình Flux thế hệ mới nhất cho chi tiết điện ảnh, ánh sáng tuyệt đẹp. Sử dụng Flux Redux để tham chiếu phong cách & nhân vật.")
            self.flux_steps_var.set("4")
            self.flux_cfg_var.set("1.0")
            self.log("[AI Engine] Đã chọn mô hình: Flux.1 Schnell (Steps: 4, CFG: 1.0)")
        elif "InstantID" in choice:
            self.lbl_model_desc_var.set("🎯 Dùng công nghệ InstantID (quét khuôn mặt InsightFace) giữ đúng 99% gương mặt nhân vật từ ảnh tham chiếu sang các dáng đứng & bối cảnh mới.")
            self.flux_steps_var.set("8")
            self.flux_cfg_var.set("1.5")
            self.log("[AI Engine] Đã chọn mô hình: SDXL InstantID (Steps: 8, CFG: 1.5)")
        elif "IP-Adapter" in choice:
            self.lbl_model_desc_var.set("⚡ SD 1.5 kết hợp IP-Adapter sinh ảnh cực nhanh (vài giây/ảnh). Rất phù hợp cho tạo ảnh truyện tranh, minh họa số lượng lớn.")
            self.flux_steps_var.set("20")
            self.flux_cfg_var.set("7.0")
            self.log("[AI Engine] Đã chọn mô hình: SD 1.5 IP-Adapter (Steps: 20, CFG: 7.0)")

    def trigger_stop_flux_generation(self):
        self.flux_stop_generation = True
        self.log("[Flux] Người dùng đã nhấn nút Dừng. Đang hủy tiến trình...")
        self.flux_status_var.set("Đang dừng...")
        self.btn_flux_stop.configure(state="disabled")
        
        def send_stop():
            url = self.flux_server_url_var.get().strip()
            if url:
                if not url.startswith("http"):
                    url = "http://" + url
                try:
                    import requests
                    requests.post(f"{url}/interrupt", timeout=5)
                    requests.post(f"{url}/queue", json={"clear": True}, timeout=5)
                    self.log("[Flux] Đã gửi lệnh Dừng (Interrupt) & Xóa hàng đợi thành công.")
                except Exception as e:
                    self.log(f"[Flux] Lỗi khi gửi lệnh dừng đến server: {e}", "WARNING")
        
        threading.Thread(target=send_stop, daemon=True).start()

    def import_flux_prompts(self):
        from tkinter import filedialog, messagebox
        file_path = filedialog.askopenfilename(
            title="Chọn file chứa danh sách prompt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    self.txt_flux_prompt.delete("1.0", tk.END)
                    self.txt_flux_prompt.insert(tk.END, content)
                    self.flux_batch_mode_var.set(True)
                    self.log(f"[Flux] Đã nhập danh sách prompt từ file: {os.path.basename(file_path)}")
                else:
                    messagebox.showwarning("Cảnh báo", "File txt này trống!")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể đọc file: {e}")

    def start_flux_generation(self):
        threading.Thread(target=self.flux_generation_worker, daemon=True).start()

    def flux_generation_worker(self):
        import uuid
        import json
        import random
        import requests
        import io
        import os
        from PIL import Image, ImageTk
        import websocket
        
        self.flux_stop_generation = False
        self.root.after(0, lambda: self.btn_flux_generate.configure(state="disabled"))
        self.root.after(0, lambda: self.btn_flux_save.configure(state="disabled"))
        self.root.after(0, lambda: self.btn_flux_stop.configure(state="normal"))
        
        url = self.flux_server_url_var.get().strip()
        if not url:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập hoặc kiểm tra kết nối Server URL trước!")
            self.root.after(0, lambda: self.btn_flux_generate.configure(state="normal"))
            self.root.after(0, lambda: self.btn_flux_stop.configure(state="disabled"))
            return
            
        if not url.startswith("http"):
            url = "http://" + url
            self.root.after(0, lambda u=url: self.flux_server_url_var.set(u))
            
        ws_url = url.replace("http://", "ws://").replace("https://", "wss://")
        
        raw_text = self.txt_flux_prompt.get("1.0", tk.END).strip()
        is_batch = self.flux_batch_mode_var.get()
        
        if is_batch:
            prompts = [line.strip() for line in raw_text.split("\n") if line.strip()]
        else:
            prompts = [raw_text] if raw_text else []
            
        if not prompts:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập hoặc chọn file prompt miêu tả ảnh!")
            self.root.after(0, lambda: self.btn_flux_generate.configure(state="normal"))
            self.root.after(0, lambda: self.btn_flux_stop.configure(state="disabled"))
            return
            
        try:
            width = int(self.flux_width_var.get())
            height = int(self.flux_height_var.get())
            steps = int(self.flux_steps_var.get())
            cfg = float(self.flux_cfg_var.get())
            seed_val = int(self.flux_seed_var.get())
            denoise_val = float(self.flux_denoise_var.get())
        except Exception as e:
            messagebox.showerror("Lỗi", f"Thông số nhập vào không hợp lệ: {e}")
            self.root.after(0, lambda: self.btn_flux_generate.configure(state="normal"))
            self.root.after(0, lambda: self.btn_flux_stop.configure(state="disabled"))
            return

        # Kiểm tra ảnh tham chiếu
        ref_path = getattr(self, 'flux_ref_image_path', '')
        has_ref = os.path.exists(ref_path) if ref_path else False
        uploaded_name = None
        
        if has_ref:
            self.log(f"[Flux] Phát hiện ảnh tham chiếu: {ref_path}. Đang upload lên ComfyUI Server...")
            self.root.after(0, lambda: self.flux_status_var.set("Đang upload ảnh..."))
            
            upload_success = False
            last_err = ""
            for attempt in range(1, 6):
                if getattr(self, "flux_stop_generation", False):
                    break
                try:
                    with open(ref_path, "rb") as f:
                        files = {"image": f}
                        res_upload = requests.post(f"{url}/upload/image", files=files, timeout=20)
                    if res_upload.status_code == 200:
                        uploaded_name = res_upload.json()["name"]
                        self.log(f"[Flux] Upload ảnh tham chiếu thành công: {uploaded_name}")
                        upload_success = True
                        break
                    else:
                        last_err = f"Lỗi HTTP {res_upload.status_code}"
                except Exception as e:
                    last_err = str(e)
                    
                if attempt < 5:
                    self.log(f"[Flux] Server bận hoặc đang khởi tạo ({last_err}), thử lại {attempt+1}/5 sau 3s...", "WARNING")
                    time.sleep(3)
                    
            if not upload_success:
                self.log(f"[Flux] Lỗi upload ảnh tham chiếu sau 5 lần thử: {last_err}", "ERROR")
                messagebox.showerror("Lỗi kết nối Server", f"Server ComfyUI đang bận khởi tạo mô hình hoặc ngắt kết nối tạm thời.\n\nChi tiết: {last_err}\n\nVui lòng chờ khoảng 10-15 giây để Server nạp xong Model rồi bấm Bắt đầu lại!")
                self.root.after(0, lambda: self.flux_status_var.set("Lỗi upload ảnh!"))
                self.root.after(0, lambda: self.btn_flux_generate.configure(state="normal"))
                self.root.after(0, lambda: self.btn_flux_stop.configure(state="disabled"))
                return

        total_prompts = len(prompts)
        self.log(f"[Flux] Bắt đầu tiến trình sinh ảnh cho {total_prompts} prompt...")
        
        for idx, current_prompt in enumerate(prompts):
            if getattr(self, "flux_stop_generation", False):
                self.log("[Flux] Tiến trình bị dừng theo yêu cầu của người dùng.", "WARNING")
                break
                
            self.log(f"[Flux] [{idx+1}/{total_prompts}] Đang xử lý prompt: '{current_prompt[:60]}...'")
            self.root.after(0, lambda: self.flux_status_var.set(f"Đang tạo {idx+1}/{total_prompts}..."))
            self.root.after(0, lambda: self.flux_progress_var.set(0.0))
            
            # Chọn seed cho từng prompt
            if seed_val == -1:
                seed = random.randint(1, 1125899906842624)
            else:
                seed = seed_val if not is_batch else seed_val + idx
                
            selected_engine = self.flux_model_choice_var.get() if hasattr(self, 'flux_model_choice_var') else "Flux.1"
            if "InstantID" in selected_engine:
                ckpt_name = "sdxl_lightning_8step.safetensors"
            elif "IP-Adapter" in selected_engine:
                ckpt_name = "v1-5-pruned-emaonly.safetensors"
            else:
                ckpt_name = "flux1-schnell-fp8.safetensors"

            if has_ref:
                if "Flux.1" in selected_engine:
                    to_strength = max(0.0, min(1.0, 1.0 - denoise_val))
                    workflow = {
                        "3": {
                            "inputs": {
                                "seed": seed,
                                "steps": steps,
                                "cfg": cfg,
                                "sampler_name": "euler",
                                "scheduler": "simple",
                                "denoise": 1.0,
                                "model": ["4", 0],
                                "positive": ["16", 0],
                                "negative": ["7", 0],
                                "latent_image": ["5", 0]
                            },
                            "class_type": "KSampler"
                        },
                        "4": {
                            "inputs": {
                                "ckpt_name": ckpt_name
                            },
                            "class_type": "CheckpointLoaderSimple"
                        },
                        "5": {
                            "inputs": {
                                "width": width,
                                "height": height,
                                "batch_size": 1
                            },
                            "class_type": "EmptyLatentImage"
                        },
                        "6": {
                            "inputs": {
                                "text": current_prompt,
                                "clip": ["4", 1]
                            },
                            "class_type": "CLIPTextEncode"
                        },
                        "7": {
                            "inputs": {
                                "text": "",
                                "clip": ["4", 1]
                            },
                            "class_type": "CLIPTextEncode"
                        },
                        "8": {
                            "inputs": {
                                "samples": ["3", 0],
                                "vae": ["4", 2]
                            },
                            "class_type": "VAEDecode"
                        },
                        "9": {
                            "inputs": {
                                "filename_prefix": "Flux_OmniVoice",
                                "images": ["8", 0]
                            },
                            "class_type": "SaveImage"
                        },
                        "11": {
                            "inputs": {
                                "image": uploaded_name,
                                "upload": "image"
                            },
                            "class_type": "LoadImage"
                        },
                        "12": {
                            "inputs": {
                                "clip_name": "sigclip_vision_patch14_384.safetensors"
                            },
                            "class_type": "CLIPVisionLoader"
                        },
                        "13": {
                            "inputs": {
                                "clip_vision": ["12", 0],
                                "image": ["11", 0],
                                "crop": "center"
                            },
                            "class_type": "CLIPVisionEncode"
                        },
                        "14": {
                            "inputs": {
                                "style_model_name": "flux1-redux-dev.safetensors"
                            },
                            "class_type": "StyleModelLoader"
                        },
                        "15": {
                            "inputs": {
                                "strength": 1.0,
                                "strength_type": "multiply",
                                "conditioning": ["6", 0],
                                "style_model": ["14", 0],
                                "clip_vision_output": ["13", 0]
                            },
                            "class_type": "StyleModelApply"
                        },
                        "16": {
                            "inputs": {
                                "conditioning_to": ["6", 0],
                                "conditioning_from": ["15", 0],
                                "conditioning_to_strength": to_strength
                            },
                            "class_type": "ConditioningAverage"
                        }
                    }
                else:
                    # Workflow cho SDXL InstantID & SD 1.5
                    sd_denoise = denoise_val if denoise_val > 0.0 else 0.55
                    workflow = {
                        "3": {
                            "inputs": {
                                "seed": seed,
                                "steps": steps,
                                "cfg": cfg,
                                "sampler_name": "euler",
                                "scheduler": "normal",
                                "denoise": sd_denoise,
                                "model": ["4", 0],
                                "positive": ["6", 0],
                                "negative": ["7", 0],
                                "latent_image": ["10", 0]
                            },
                            "class_type": "KSampler"
                        },
                        "4": {
                            "inputs": {
                                "ckpt_name": ckpt_name
                            },
                            "class_type": "CheckpointLoaderSimple"
                        },
                        "6": {
                            "inputs": {
                                "text": current_prompt,
                                "clip": ["4", 1]
                            },
                            "class_type": "CLIPTextEncode"
                        },
                        "7": {
                            "inputs": {
                                "text": "blurry, ugly, distorted, low quality, bad anatomy, deformed",
                                "clip": ["4", 1]
                            },
                            "class_type": "CLIPTextEncode"
                        },
                        "8": {
                            "inputs": {
                                "samples": ["3", 0],
                                "vae": ["4", 2]
                            },
                            "class_type": "VAEDecode"
                        },
                        "9": {
                            "inputs": {
                                "filename_prefix": "AI_OmniVoice",
                                "images": ["8", 0]
                            },
                            "class_type": "SaveImage"
                        },
                        "11": {
                            "inputs": {
                                "image": uploaded_name,
                                "upload": "image"
                            },
                            "class_type": "LoadImage"
                        },
                        "10": {
                            "inputs": {
                                "pixels": ["11", 0],
                                "vae": ["4", 2]
                            },
                            "class_type": "VAEEncode"
                        }
                    }
            else:
                workflow = {
                    "3": {
                        "inputs": {
                            "seed": seed,
                            "steps": steps,
                            "cfg": cfg,
                            "sampler_name": "euler",
                            "scheduler": "simple",
                            "denoise": 1.0,
                            "model": ["4", 0],
                            "positive": ["6", 0],
                            "negative": ["7", 0],
                            "latent_image": ["5", 0]
                        },
                        "class_type": "KSampler"
                    },
                    "4": {
                        "inputs": {
                            "ckpt_name": ckpt_name
                        },
                        "class_type": "CheckpointLoaderSimple"
                    },
                    "5": {
                        "inputs": {
                            "width": width,
                            "height": height,
                            "batch_size": 1
                        },
                        "class_type": "EmptyLatentImage"
                    },
                    "6": {
                        "inputs": {
                            "text": current_prompt,
                            "clip": ["4", 1]
                        },
                        "class_type": "CLIPTextEncode"
                    },
                    "7": {
                        "inputs": {
                            "text": "",
                            "clip": ["4", 1]
                        },
                        "class_type": "CLIPTextEncode"
                    },
                    "8": {
                        "inputs": {
                            "samples": ["3", 0],
                            "vae": ["4", 2]
                        },
                        "class_type": "VAEDecode"
                    },
                    "9": {
                        "inputs": {
                            "filename_prefix": "Flux_OmniVoice",
                            "images": ["8", 0]
                        },
                        "class_type": "SaveImage"
                    }
                }
            
            ws = None
            try:
                client_id = uuid.uuid4().hex
                ws = websocket.WebSocket()
                ws.connect(f"{ws_url}/ws?clientId={client_id}", timeout=120)
                
                self.root.after(0, lambda: self.flux_status_var.set(f"[{idx+1}/{total_prompts}] Đang gửi prompt..."))
                self.root.after(0, lambda: self.flux_progress_var.set(10.0))
                
                payload = {
                    "prompt": workflow,
                    "client_id": client_id
                }
                res = requests.post(f"{url}/prompt", json=payload, timeout=10)
                if res.status_code != 200:
                    raise Exception(f"Server trả về lỗi: {res.status_code} - {res.text}")
                    
                prompt_id = res.json()["prompt_id"]
                self.log(f"[Flux] Đã đẩy prompt [{idx+1}/{total_prompts}] thành công. ID: {prompt_id}")
                self.root.after(0, lambda: self.flux_status_var.set(f"[{idx+1}/{total_prompts}] Đang xếp hàng..."))
                self.root.after(0, lambda: self.flux_progress_var.set(20.0))
                
                finished = False
                while not finished:
                    if getattr(self, "flux_stop_generation", False):
                        self.log("[Flux] Hủy bỏ giữa chừng khi đang chạy nhận dữ liệu...", "WARNING")
                        break
                    try:
                        message = ws.recv()
                        if isinstance(message, str):
                            data = json.loads(message)
                            if data["type"] == "progress":
                                v = data["data"]["value"]
                                m = data["data"]["max"]
                                pct = 20.0 + (v / m) * 70.0
                                self.root.after(0, lambda p=pct: self.flux_progress_var.set(p))
                                self.root.after(0, lambda step=v, total=m: self.flux_status_var.set(f"Prompt {idx+1}/{total_prompts}: Bước {step}/{total}..."))
                            elif data["type"] == "executing":
                                node = data["data"]["node"]
                                if node is None and data["data"]["prompt_id"] == prompt_id:
                                    finished = True
                        elif isinstance(message, bytes):
                            if len(message) > 8:
                                try:
                                    image_data = message[8:]
                                    preview_img = Image.open(io.BytesIO(image_data))
                                    self.root.after(0, lambda img=preview_img: self.update_flux_preview(img))
                                except Exception:
                                    pass
                    except websocket.WebSocketConnectionClosedException:
                        self.log(f"[Flux] Kết nối WebSocket bị đóng khi đang xử lý prompt {idx+1}.", "WARNING")
                        break
                    except Exception as we:
                        self.log(f"[Flux] Lỗi nhận dữ liệu WebSocket ở prompt {idx+1}: {we}", "WARNING")
                        break
                        
                self.root.after(0, lambda: self.flux_status_var.set(f"[{idx+1}/{total_prompts}] Đang tải ảnh..."))
                self.root.after(0, lambda: self.flux_progress_var.set(90.0))
                
                time.sleep(1)
                
                res_history = requests.get(f"{url}/history/{prompt_id}", timeout=10)
                if res_history.status_code == 200:
                    history_data = res_history.json().get(prompt_id, {})
                    outputs = history_data.get("outputs", {})
                    node_output = outputs.get("9", {})
                    images_info = node_output.get("images", [])
                    
                    if images_info:
                        filename = images_info[0]["filename"]
                        subfolder = images_info[0].get("subfolder", "")
                        
                        img_res = requests.get(f"{url}/view?filename={filename}&subfolder={subfolder}&type=output", timeout=15)
                        if img_res.status_code == 200:
                            final_img = Image.open(io.BytesIO(img_res.content))
                            self.flux_last_image = final_img
                            self.root.after(0, lambda img=final_img: self.update_flux_preview(img))
                            self.root.after(0, lambda: self.btn_flux_save.configure(state="normal"))
                            self.root.after(0, lambda: self.flux_status_var.set(f"Hoàn thành {idx+1}/{total_prompts}!"))
                            self.root.after(0, lambda: self.flux_progress_var.set(100.0))
                            self.log(f"[Flux] [{idx+1}/{total_prompts}] Đã tạo và nhận ảnh thành công!")
                            
                            flux_output_dir = os.path.join(output_dir, "flux_images")
                            os.makedirs(flux_output_dir, exist_ok=True)
                            save_name = f"flux_{time.strftime('%Y%m%d_%H%M%S')}_{idx+1}.png"
                            save_path = os.path.join(flux_output_dir, save_name)
                            final_img.save(save_path)
                            self.log(f"[Flux] Tự động lưu ảnh vào: {save_path}")
                        else:
                            raise Exception("Không thể tải ảnh chất lượng cao từ server qua endpoint /view")
                    else:
                        raise Exception("Không tìm thấy kết quả ảnh trong lịch sử của server")
                else:
                    raise Exception("Không thể truy cập API history của server")
                    
            except Exception as e:
                self.log(f"[Flux] Lỗi sinh ảnh tại prompt {idx+1}: {e}", "ERROR")
                self.root.after(0, lambda: self.flux_status_var.set(f"Lỗi ở prompt {idx+1}!"))
                self.root.after(0, lambda: self.flux_progress_var.set(0.0))
            finally:
                if ws:
                    try:
                        ws.close()
                    except Exception:
                        pass
                        
        self.root.after(0, lambda: self.btn_flux_generate.configure(state="normal"))
        self.root.after(0, lambda: self.btn_flux_stop.configure(state="disabled"))
        if getattr(self, "flux_stop_generation", False):
            self.root.after(0, lambda: self.flux_status_var.set("Đã dừng!"))
            self.root.after(0, lambda: self.flux_progress_var.set(0.0))
        else:
            self.root.after(0, lambda: self.flux_status_var.set("Hoàn thành tất cả!"))
            self.root.after(0, lambda: self.flux_progress_var.set(100.0))

    def update_flux_preview(self, pil_image):
        from PIL import ImageTk
        
        max_w = 400
        max_h = 400
        
        orig_w, orig_h = pil_image.size
        ratio = min(max_w / orig_w, max_h / orig_h)
        new_w = int(orig_w * ratio)
        new_h = int(orig_h * ratio)
        
        resized_img = pil_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        self.flux_preview_photo = ImageTk.PhotoImage(resized_img)
        self.lbl_flux_preview.configure(image=self.flux_preview_photo, text="")

    def save_flux_image(self):
        if not hasattr(self, 'flux_last_image') or self.flux_last_image is None:
            messagebox.showwarning("Cảnh báo", "Chưa có ảnh nào được tạo để lưu!")
            return
            
        from tkinter import filedialog
        file_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Files", "*.png"), ("JPEG Files", "*.jpg"), ("All Files", "*.*")],
            title="Lưu ảnh Flux"
        )
        if file_path:
            try:
                self.flux_last_image.save(file_path)
                messagebox.showinfo("Thành công", f"Đã lưu ảnh thành công tại:\n{file_path}")
                self.log(f"[Flux] Đã lưu ảnh thủ công tại: {file_path}")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể lưu file: {e}")

    def open_flux_output_folder(self):
        flux_output_dir = os.path.join(output_dir, "flux_images")
        os.makedirs(flux_output_dir, exist_ok=True)
        try:
            os.startfile(flux_output_dir)
            self.log(f"Đã mở thư mục ảnh: {flux_output_dir}")
        except Exception as e:
            self.log(f"Lỗi mở thư mục: {e}", "ERROR")

    def open_output_folder(self):
        try:
            # Mở thư mục chứa file đầu ra bằng File Explorer trên Windows
            os.startfile(output_dir)
            self.log(f"Đã mở thư mục outputs: {output_dir}")
        except Exception as e:
            self.log(f"Lỗi mở thư mục: {e}", "ERROR")

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    # Đăng ký đóng tiến trình phát âm thanh khi tắt ứng dụng
    def on_closing():
        global current_play_process
        if current_play_process:
            try:
                current_play_process.terminate()
            except Exception:
                pass
        try:
            app.disconnect_current_vpn()
        except Exception:
            pass
        root.destroy()
        sys.exit(0)

    root = tk.Tk()
    app = OmniVoiceGUI(root)
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
