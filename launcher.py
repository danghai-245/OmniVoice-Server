#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time
import threading
import logging
import subprocess
import json

# =====================================================================
# 1. Cấu hình biến môi trường Cache lưu hoàn toàn ở ổ E (thư mục dự án)
# =====================================================================
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

# Ghi log ra console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# =====================================================================
# 2.1 Lớp chuyển hướng stdout/stderr sang Log Widget
# =====================================================================
class RedirectText:
    def __init__(self, text_widget, log_file_path=None):
        self.text_widget = text_widget
        self.log_file_path = log_file_path

    def write(self, string):
        if not string:
            return
        
        def append():
            try:
                self.text_widget.configure(state='normal')
                self.text_widget.insert('end', string)
                self.text_widget.configure(state='disabled')
                self.text_widget.see('end')
            except Exception:
                pass
        
        try:
            self.text_widget.after(0, append)
        except Exception:
            pass
            
        if self.log_file_path:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(string)
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
        self.root.title("OmniVoice Studio v0.1.5 (Local Tool)")
        self.root.geometry("1080x750")
        self.root.configure(background="#121214")
        
        # Đặt kích thước tối thiểu
        self.root.minsize(1024, 700)
        
        # Setup Style
        self.setup_styles()
        
        # Giao diện chính chia làm 2 phần: Notebook ở trên, Log Panel ở dưới
        self.main_pane = tk.PanedWindow(self.root, orient=tk.VERTICAL, bg="#E9ECEF", bd=0, sashwidth=4)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Phần trên: Tabs điều khiển
        self.notebook = ttk.Notebook(self.main_pane)
        self.main_pane.add(self.notebook, minsize=480)
        
        # Tạo các tab
        self.tab_settings = ttk.Frame(self.notebook)
        self.tab_clone = ttk.Frame(self.notebook)
        self.tab_design = ttk.Frame(self.notebook)
        self.tab_engine = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_settings, text=" Cài đặt & Tải Model ")
        self.notebook.add(self.tab_clone, text=" Voice Clone (Nhái Giọng) ")
        self.notebook.add(self.tab_design, text=" Voice Design (Thiết Kế Giọng) ")
        self.notebook.add(self.tab_engine, text=" Cỗ máy tạo âm thanh ")
        
        # Phần dưới: Log Panel
        self.create_log_panel()
        
        # Khởi tạo các biến cấu hình & nạp config
        self.gemini_key_var = tk.StringVar()
        self.run_mode_var = tk.StringVar(value="Local")
        self.api_server_url_var = tk.StringVar(value="http://127.0.0.1:8000")
        
        self.load_config()
        self.gemini_key_var.set(self.gemini_api_key)
        self.run_mode_var.set(self.run_mode)
        self.api_server_url_var.set(self.api_server_url)
        self.chunk_len_var = tk.IntVar(value=500)
        
        # Xây dựng nội dung từng tab
        self.build_settings_tab()
        self.on_run_mode_changed()
        self.build_clone_tab()
        self.build_design_tab()
        self.build_engine_tab()
        
        # Đăng ký callback download
        global download_progress_callback
        download_progress_callback = self.update_download_progress_ui
        
        # Biến lưu trữ đường dẫn file âm thanh tham chiếu
        self.ref_audio_path = tk.StringVar(value="")
        self.saved_voices_dir = saved_voices_dir
        
        # Khởi tạo kiểm tra trạng thái model
        self.check_models_status_async()
        
        # Nạp danh sách giọng đọc đã lưu
        self.load_saved_voices()
        
        # Log khởi động thành công
        self.log("Đã khởi chạy OmniVoice Studio. Tất cả dữ liệu lưu tại ổ E.")


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
        self.run_mode = "Local"
        self.api_server_url = "http://127.0.0.1:8000"
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.gemini_api_key = data.get("gemini_api_key", "")
                    self.run_mode = data.get("run_mode", "Local")
                    self.api_server_url = data.get("api_server_url", "http://127.0.0.1:8000")
            except Exception as e:
                pass
                
    def save_config(self):
        config_path = os.path.join(current_dir, "config.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "gemini_api_key": self.gemini_api_key,
                    "run_mode": self.run_mode,
                    "api_server_url": self.api_server_url
                }, f, indent=4, ensure_ascii=False)
            self.log("Đã lưu tệp config.json thành công!")
        except Exception as e:
            self.log(f"Lỗi khi lưu file config.json: {e}", "ERROR")

    def save_all_settings(self):
        self.gemini_api_key = self.gemini_key_var.get().strip()
        self.run_mode = self.run_mode_var.get()
        self.api_server_url = self.api_server_url_var.get().strip()
        self.save_config()
        messagebox.showinfo("Thành công", "Đã lưu tất cả cấu hình thành công!")

    def on_run_mode_changed(self, event=None):
        mode = self.run_mode_var.get()
        if "Cloud API" in mode:
            self.btn_load_model.configure(state="disabled")
            self.lbl_load_status.configure(text="Chế độ Cloud: Mô hình chạy từ xa, không cần nạp cục bộ.", foreground="#00E676")
        else:
            global loaded_model
            if loaded_model is None:
                self.btn_load_model.configure(state="normal")
                self.lbl_load_status.configure(text="Mô hình: Chưa được nạp vào bộ nhớ.", foreground="#A0A0AA")
            else:
                self.btn_load_model.configure(state="disabled")
                self.lbl_load_status.configure(text="Mô hình: Đã sẵn sàng trên GPU/CPU.", foreground="#00E676")

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
                
                model = genai.GenerativeModel("gemini-1.5-flash")
                
                prompt = (
                    "Bạn là một biên tập viên kịch bản chuyên nghiệp cho giọng đọc AI.\n"
                    "Nhiệm vụ của bạn là đọc kỹ toàn bộ văn bản đầu vào dưới đây và chèn thêm các nhãn biểu cảm phù hợp vào đúng vị trí nhấn nhá để giọng đọc AI diễn cảm và tự nhiên hơn.\n\n"
                    "Các nhãn biểu cảm được hỗ trợ (chỉ sử dụng chính xác các nhãn này):\n"
                    "- [laughter] : dùng khi có tiếng cười, sự vui vẻ, châm biếm nhẹ\n"
                    "- [sigh] : dùng khi thở dài, mệt mỏi, buồn chán, suy tư\n"
                    "- [gasp] : dùng khi ngạc nhiên, thở dốc, sửng sốt, giật mình\n"
                    "- [ask] : dùng để nhấn giọng hỏi, nghi vấn ở cuối câu hỏi hoặc câu lấp lửng\n"
                    "- [disapproval] : dùng khi bày tỏ sự bất bình, thất vọng, không hài lòng\n\n"
                    "Yêu cầu nghiêm ngặt:\n"
                    "1. KHÔNG thêm bớt, chỉnh sửa hoặc thay đổi bất kỳ từ ngữ nào trong văn bản gốc. Chỉ chèn nhãn biểu cảm vào vị trí phù hợp (khoảng 3-5 câu chèn 1 nhãn, không chèn quá dày đặc làm nát văn bản).\n"
                    "2. KHÔNG thêm bất kỳ câu giải thích, giới thiệu nào trước và sau văn bản kết quả.\n"
                    "3. Trả về duy nhất văn bản sau khi đã chèn các nhãn biểu cảm.\n\n"
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
                self.root.after(0, lambda: messagebox.showerror("Lỗi", f"Lỗi khi gọi API Gemini:\n{err}"))
                
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
        log_frame = ttk.Frame(self.main_pane)
        self.main_pane.add(log_frame, minsize=140)
        
        # Tiêu đề Log
        title_label = ttk.Label(log_frame, text="Nhật ký hoạt động (App Logs)", font=("Segoe UI", 9, "bold"), foreground="#20C997")
        title_label.pack(anchor=tk.W, pady=(5, 2))
        
        # Khung Text hiển thị log
        self.log_text = tk.Text(log_frame, bg="#F8F9FA", fg="#495057", insertbackground="black",
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
    # Tab 1: Cài đặt & Tải Model
    # =====================================================================
    def build_settings_tab(self):
        # Thiết kế 2 cột: Cột trái cấu hình thiết bị & Trạng thái tải; Cột phải tiến trình tải & nạp bộ nhớ
        container = ttk.Frame(self.tab_settings)
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # --- Cột trái: Cấu hình chung & Trạng thái ---
        left_frame = ttk.LabelFrame(container, text=" Cấu hình & Trạng thái Model ", padding=15)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # 1. Chọn Thiết bị chạy (Device)
        ttk.Label(left_frame, text="Thiết bị tính toán (Device) [Chỉ dùng cho Local]:").pack(anchor=tk.W, pady=(5, 5))
        
        self.device_var = tk.StringVar(value="Auto")
        devices = ["Auto", "CUDA (NVIDIA GPU)", "CPU"]
        self.device_combo = ttk.Combobox(left_frame, textvariable=self.device_var, values=devices, state="readonly", width=35)
        self.device_combo.pack(anchor=tk.W, pady=(0, 10))
        
        # 1.1 Chọn chế độ chạy (Run Mode)
        ttk.Label(left_frame, text="Chế độ hoạt động (Run Mode):").pack(anchor=tk.W, pady=(5, 5))
        run_modes = ["Local (Chạy GPU cục bộ)", "Cloud API (Chạy trên Colab/Kaggle)"]
        self.run_mode_combo = ttk.Combobox(left_frame, textvariable=self.run_mode_var, values=run_modes, state="readonly", width=35)
        self.run_mode_combo.pack(anchor=tk.W, pady=(0, 10))
        self.run_mode_combo.bind("<<ComboboxSelected>>", self.on_run_mode_changed)
        
        # 1.2 Ô nhập URL Server Cloud API
        ttk.Label(left_frame, text="Địa chỉ Cloud API Server:").pack(anchor=tk.W, pady=(5, 2))
        self.api_url_entry = ttk.Entry(left_frame, textvariable=self.api_server_url_var, width=40)
        self.api_url_entry.pack(anchor=tk.W, pady=(0, 10))
        
        # 1.3 Google AI Studio API Key (Gemini)
        ttk.Label(left_frame, text="Google AI Studio API Key (Gemini):").pack(anchor=tk.W, pady=(5, 2))
        f_gemini = ttk.Frame(left_frame)
        f_gemini.pack(fill=tk.X, pady=(0, 10))
        
        self.gemini_key_entry = ttk.Entry(f_gemini, textvariable=self.gemini_key_var, show="*")
        self.gemini_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # 1.4 Nút Lưu tất cả cấu hình
        btn_save_settings = ttk.Button(left_frame, text="💾 Lưu cấu hình & cài đặt", style="Accent.TButton", command=self.save_all_settings)
        btn_save_settings.pack(anchor=tk.W, pady=(5, 15))
        
        # 2. Danh sách Model và Trạng thái
        ttk.Label(left_frame, text="Trạng thái các Model trong thư mục cache ổ E:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(5, 5))
        
        # Model 1: OmniVoice
        self.status_omnivoice_val = tk.StringVar(value="Đang kiểm tra...")
        f1 = ttk.Frame(left_frame)
        f1.pack(fill=tk.X, pady=5)
        ttk.Label(f1, text="• OmniVoice Model (2.6GB):", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.lbl_status_omni = ttk.Label(f1, textvariable=self.status_omnivoice_val, foreground="#FFB300")
        self.lbl_status_omni.pack(side=tk.LEFT, padx=10)
        
        # Model 2: Higgs Tokenizer
        self.status_tokenizer_val = tk.StringVar(value="Đang kiểm tra...")
        f2 = ttk.Frame(left_frame)
        f2.pack(fill=tk.X, pady=5)
        ttk.Label(f2, text="• Audio Tokenizer (1.4GB):", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.lbl_status_tok = ttk.Label(f2, textvariable=self.status_tokenizer_val, foreground="#FFB300")
        self.lbl_status_tok.pack(side=tk.LEFT, padx=10)
        
        # Model 3: Whisper ASR
        self.status_asr_val = tk.StringVar(value="Đang kiểm tra...")
        f3 = ttk.Frame(left_frame)
        f3.pack(fill=tk.X, pady=5)
        ttk.Label(f3, text="• Whisper ASR Model (1.6GB):", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.lbl_status_asr = ttk.Label(f3, textvariable=self.status_asr_val, foreground="#FFB300")
        self.lbl_status_asr.pack(side=tk.LEFT, padx=10)
        
        # Nút kiểm tra lại trạng thái
        btn_refresh = ttk.Button(left_frame, text="Làm mới trạng thái", command=self.check_models_status_async)
        btn_refresh.pack(anchor=tk.W, pady=(15, 0))

        # --- Cột phải: Thao tác tải / nạp Model ---
        right_frame = ttk.LabelFrame(container, text=" Thao tác tải và Nạp mô hình ", padding=15)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        # Nút Tải Model
        self.btn_download = ttk.Button(right_frame, text="Tải Model về ổ E", command=self.start_download_models)
        self.btn_download.pack(fill=tk.X, pady=(5, 10))
        
        # Nút Nạp Model
        self.btn_load_model = ttk.Button(right_frame, text="Nạp mô hình vào RAM/VRAM", style="Accent.TButton", command=self.start_load_model)
        self.btn_load_model.pack(fill=tk.X, pady=(0, 20))
        
        # Hiển thị Trạng thái Nạp Model
        self.lbl_load_status = ttk.Label(right_frame, text="Mô hình: Chưa được nạp vào bộ nhớ.", font=("Segoe UI", 10, "italic"), foreground="#A0A0AA")
        self.lbl_load_status.pack(anchor=tk.W, pady=5)
        
        # Thanh tiến trình nạp mô hình
        self.load_progress_val = tk.DoubleVar(value=0.0)
        self.load_progress_bar = ttk.Progressbar(right_frame, variable=self.load_progress_val, maximum=100, mode="determinate", style="Horizontal.TProgressbar")
        self.load_progress_bar.pack(fill=tk.X, pady=(2, 10))
        
        # Vùng hiển thị Tiến trình tải (Progress Bar & Status)
        self.download_info_frame = ttk.Frame(right_frame)
        self.download_info_frame.pack(fill=tk.BOTH, expand=True, pady=(20, 0))
        
        self.lbl_download_filename = ttk.Label(self.download_info_frame, text="Sẵn sàng tải xuống...", font=("Segoe UI", 9))
        self.lbl_download_filename.pack(anchor=tk.W, pady=(0, 5))
        
        self.download_progress_val = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(self.download_info_frame, variable=self.download_progress_val, maximum=100, mode="determinate", style="Horizontal.TProgressbar")
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))
        
        self.lbl_download_pct = ttk.Label(self.download_info_frame, text="0.0% (0.0 MB / 0.0 MB)", font=("Segoe UI", 9, "bold"), foreground="#00ADB5")
        self.lbl_download_pct.pack(anchor=tk.E)

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
        
        self.txt_engine_input = tk.Text(left_col, height=7, bg="#FFFFFF", fg="#212529", insertbackground="black", font=("Segoe UI", 10), wrap=tk.WORD)
        self.txt_engine_input.pack(fill=tk.X, pady=(0, 5))
        
        # Nút biểu cảm nhấn nhá
        f_express = ttk.Frame(left_col)
        f_express.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(f_express, text="Nhấn nhá biểu cảm:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
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
                             command=lambda t=tag: self.insert_expression_tag(self.txt_engine_input, t))
            btn.pack(side=tk.LEFT, padx=2)
            
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
        f_chunk_actions.pack(fill=tk.X, pady=(0, 10))
        
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
        
        columns = ("stt", "content", "status", "file")
        self.tree_chunks = ttk.Treeview(f_tree, columns=columns, show="headings", height=8)
        self.tree_chunks.heading("stt", text="STT")
        self.tree_chunks.heading("content", text="Nội dung đoạn")
        self.tree_chunks.heading("status", text="Trạng thái")
        self.tree_chunks.heading("file", text="Đường dẫn file tạm")
        
        self.tree_chunks.column("stt", width=45, minwidth=40, anchor=tk.CENTER)
        self.tree_chunks.column("content", width=320, minwidth=250, anchor=tk.W)
        self.tree_chunks.column("status", width=95, minwidth=80, anchor=tk.CENTER)
        self.tree_chunks.column("file", width=120, minwidth=100, anchor=tk.W)
        
        vsb = ttk.Scrollbar(f_tree, orient="vertical", command=self.tree_chunks.yview)
        self.tree_chunks.configure(yscrollcommand=vsb.set)
        
        self.tree_chunks.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Double click to play
        self.tree_chunks.bind("<Double-1>", lambda event: self.play_selected_chunk())
        
        # Các nút thao tác trên treeview
        f_actions = ttk.Frame(left_col, padding=5)
        f_actions.pack(fill=tk.X, pady=(5, 0))
        
        self.btn_engine_gen_sel = ttk.Button(f_actions, text="🎙️ Tạo đoạn đã chọn", command=self.generate_selected_chunk)
        self.btn_engine_gen_sel.pack(side=tk.LEFT, padx=5)
        self.btn_engine_gen_all = ttk.Button(f_actions, text="🎙️ Tạo tất cả các đoạn", style="Accent.TButton", command=self.generate_all_chunks)
        self.btn_engine_gen_all.pack(side=tk.LEFT, padx=5)
        self.btn_engine_play_sel = ttk.Button(f_actions, text="▶️ Phát đoạn đã chọn", command=self.play_selected_chunk)
        self.btn_engine_play_sel.pack(side=tk.LEFT, padx=5)
        self.btn_engine_stop = ttk.Button(f_actions, text="⏹️ Dừng phát", style="Stop.TButton", command=self.stop_audio_playback)
        self.btn_engine_stop.pack(side=tk.LEFT, padx=5)
        
        # --- CỘT PHẢI: Cấu hình giọng & Xuất file ---
        # 1. Chọn giọng đọc tham chiếu (Voice Clone)
        card_ref = ttk.LabelFrame(right_col, text=" 👤 Giọng đọc tham chiếu (Voice Clone) ", padding=12)
        card_ref.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(card_ref, text="Chọn giọng đã lưu:").pack(anchor=tk.W, pady=(0, 2))
        self.engine_saved_voices_combo = ttk.Combobox(card_ref, state="readonly")
        self.engine_saved_voices_combo.pack(fill=tk.X, pady=(0, 5))
        self.engine_saved_voices_combo.bind("<<ComboboxSelected>>", self.on_engine_voice_selected)
        
        self.engine_ref_audio = tk.StringVar(value="")
        self.engine_ref_text = tk.StringVar(value="")
        
        self.lbl_engine_voice_info = ttk.Label(card_ref, text="Chưa chọn giọng tham chiếu.", font=("Segoe UI", 9, "italic"), foreground="#A0A0AA")
        self.lbl_engine_voice_info.pack(anchor=tk.W, pady=2)
        
        # 2. Đặc tính giọng nói (Voice Design)
        card_config = ttk.LabelFrame(right_col, text=" 🎛️ Tinh chỉnh phát âm & Đặc tính giọng ", padding=12)
        card_config.pack(fill=tk.X, pady=(0, 15))
        
        # Ngôn ngữ
        ttk.Label(card_config, text="Ngôn ngữ đọc (Language):").pack(anchor=tk.W, pady=(0, 2))
        self.engine_lang_var = tk.StringVar(value="Auto")
        self.engine_lang_combo = ttk.Combobox(card_config, textvariable=self.engine_lang_var, state="readonly")
        self.engine_lang_combo['values'] = ["Auto", "English", "Vietnamese", "Chinese", "Korean", "Japanese", "French", "German", "Spanish", "Russian"]
        self.engine_lang_combo.pack(fill=tk.X, pady=(0, 8))
        
        # Tốc độ
        ttk.Label(card_config, text="Tốc độ đọc (Speed):").pack(anchor=tk.W, pady=(0, 2))
        self.engine_speed_var = tk.DoubleVar(value=1.0)
        self.engine_speed_slider = ttk.Scale(card_config, from_=0.5, to=1.5, variable=self.engine_speed_var, orient=tk.HORIZONTAL)
        self.engine_speed_slider.pack(fill=tk.X, pady=(0, 2))
        self.lbl_engine_speed_val = ttk.Label(card_config, text="1.00x", font=("Segoe UI", 9, "bold"), foreground="#00ADB5")
        self.lbl_engine_speed_val.pack(anchor=tk.E, pady=(0, 8))
        self.engine_speed_var.trace_add("write", lambda *args: self.lbl_engine_speed_val.configure(text=f"{self.engine_speed_var.get():.2f}x"))
        
        # Cao độ (Pitch)
        ttk.Label(card_config, text="Cao độ (Pitch):").pack(anchor=tk.W, pady=(0, 2))
        self.engine_pitch_var = tk.StringVar(value="Auto")
        self.engine_pitch_combo = ttk.Combobox(card_config, textvariable=self.engine_pitch_var, state="readonly")
        self.engine_pitch_combo['values'] = [
            "Auto", 
            "Very low pitch / Cực trầm", 
            "Low pitch / Giọng trầm", 
            "Moderate pitch / Giọng vừa", 
            "High pitch / Giọng cao", 
            "Very high pitch / Cực cao"
        ]
        self.engine_pitch_combo.pack(fill=tk.X, pady=(0, 8))
        
        # Đặc tính / Accent (Instruct)
        ttk.Label(card_config, text="Đặc tính / Accent (Instruct):").pack(anchor=tk.W, pady=(0, 2))
        self.engine_style_var = tk.StringVar(value="Auto")
        self.engine_style_combo = ttk.Combobox(card_config, textvariable=self.engine_style_var, state="readonly")
        self.engine_style_combo['values'] = [
            "Auto", 
            "Male / Giọng nam", 
            "Female / Giọng nữ", 
            "Whisper / Thì thầm", 
            "Child / Trẻ em", 
            "Teenager / Thiếu niên", 
            "Young adult / Thanh niên", 
            "Middle-aged / Trung niên", 
            "Elderly / Người già", 
            "American accent / Giọng Mỹ", 
            "British accent / Giọng Anh", 
            "Australian accent / Giọng Úc", 
            "Indian accent / Giọng Ấn Độ"
        ]
        self.engine_style_combo.pack(fill=tk.X, pady=(0, 8))
        
        # Steps
        ttk.Label(card_config, text="Số bước khử nhiễu (Steps):").pack(anchor=tk.W, pady=(0, 2))
        self.engine_steps_var = tk.IntVar(value=32)
        self.engine_steps_slider = ttk.Scale(card_config, from_=4, to=64, variable=self.engine_steps_var, orient=tk.HORIZONTAL)
        self.engine_steps_slider.pack(fill=tk.X, pady=(0, 2))
        self.lbl_engine_steps_val = ttk.Label(card_config, text="32 bước", font=("Segoe UI", 9, "bold"), foreground="#00ADB5")
        self.lbl_engine_steps_val.pack(anchor=tk.E, pady=(0, 5))
        self.engine_steps_var.trace_add("write", lambda *args: self.lbl_engine_steps_val.configure(text=f"{int(self.engine_steps_var.get())} bước"))
        
        # 3. Gộp & Xuất bản
        card_export = ttk.LabelFrame(right_col, text=" 📦 Gộp & Xuất bản tệp hoàn chỉnh ", padding=12)
        card_export.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(card_export, text="Đường dẫn lưu file hoàn chỉnh:").pack(anchor=tk.W, pady=(0, 2))
        self.engine_dest_path = tk.StringVar(value="")
        
        f_dest = ttk.Frame(card_export)
        f_dest.pack(fill=tk.X, pady=(0, 10))
        self.ent_engine_dest = ttk.Entry(f_dest, textvariable=self.engine_dest_path)
        self.ent_engine_dest.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(f_dest, text="📂 Chọn", command=self.select_engine_export_path).pack(side=tk.RIGHT)
        
        self.btn_engine_merge = ttk.Button(card_export, text="📦 GỘP CÁC ĐOẠN & XUẤT FILE", style="Accent.TButton", command=self.merge_all_chunks)
        self.btn_engine_merge.pack(fill=tk.X, ipady=3)
        
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
            self.lbl_status_omni.configure(foreground="#00E676")
        except Exception:
            self.status_omnivoice_val.set("Chưa tải")
            self.lbl_status_omni.configure(foreground="#FF3366")
            
        # 2. Check Higgs Tokenizer
        try:
            snapshot_download(repo_id=MODEL_TOKENIZER, local_files_only=True)
            self.status_tokenizer_val.set("Đã tải xong")
            self.lbl_status_tok.configure(foreground="#00E676")
        except Exception:
            self.status_tokenizer_val.set("Chưa tải")
            self.lbl_status_tok.configure(foreground="#FF3366")
            
        # 3. Check Whisper ASR
        try:
            snapshot_download(repo_id=MODEL_ASR, local_files_only=True)
            self.status_asr_val.set("Đã tải xong")
            self.lbl_status_asr.configure(foreground="#00E676")
        except Exception:
            self.status_asr_val.set("Chưa tải (Tùy chọn)")
            self.lbl_status_asr.configure(foreground="#FFB300")
            
        # Tự động cập nhật thanh tiến độ lên 100% khi tất cả model đã tải xong
        if (self.status_omnivoice_val.get() == "Đã tải xong" and 
            self.status_tokenizer_val.get() == "Đã tải xong" and 
            self.status_asr_val.get() == "Đã tải xong"):
            self.root.after(0, lambda: self.lbl_download_filename.configure(text="Tất cả các model đã sẵn sàng trên đĩa E!"))
            self.root.after(0, lambda: self.download_progress_val.set(100.0))
            self.root.after(0, lambda: self.lbl_download_pct.configure(text="100% hoàn thành"))

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

    def load_saved_voices(self):
        if not os.path.exists(self.saved_voices_dir):
            os.makedirs(self.saved_voices_dir, exist_ok=True)
        supported_exts = (".wav", ".mp3", ".m4a", ".flac", ".ogg")
        files = [f for f in os.listdir(self.saved_voices_dir) if f.lower().endswith(supported_exts)]
        voices = [os.path.splitext(f)[0] for f in files]
        voices.sort()
        
        self.saved_voices_combo['values'] = ["-- Chọn giọng đọc đã lưu --"] + voices
        self.saved_voices_combo.set("-- Chọn giọng đọc đã lưu --")
        
        if hasattr(self, 'engine_saved_voices_combo'):
            self.engine_saved_voices_combo['values'] = ["-- Chọn giọng đọc đã lưu --"] + voices
            self.engine_saved_voices_combo.set("-- Chọn giọng đọc đã lưu --")

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
            item_id = self.tree_chunks.insert("", tk.END, values=(i, chunk, "Chưa tạo", ""))
            self.chunks_data.append({
                'item_id': item_id,
                'index': i,
                'text': chunk,
                'status': 'Chưa tạo',
                'file_path': None
            })
            
        self.log(f"Đã chia văn bản thành {len(chunks)} đoạn thành công.")

    def on_engine_voice_selected(self, event):
        name = self.engine_saved_voices_combo.get()
        if name == "-- Chọn giọng đọc đã lưu --":
            self.engine_ref_audio.set("")
            self.engine_ref_text.set("")
            self.lbl_engine_voice_info.configure(text="Chưa chọn giọng tham chiếu.", foreground="#A0A0AA")
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
            self.engine_ref_audio.set(matched_file)
            
            txt_path = os.path.join(self.saved_voices_dir, f"{name}.txt")
            ref_text = ""
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, "r", encoding="utf-8") as f:
                        ref_text = f.read().strip()
                except Exception:
                    pass
            self.engine_ref_text.set(ref_text)
            
            info_txt = f"Giọng: {name} | File mẫu: {os.path.basename(matched_file)}"
            if ref_text:
                info_txt += f" | Text: \"{ref_text[:20]}...\""
            self.lbl_engine_voice_info.configure(text=info_txt, foreground="#28A745")
            self.log(f"Đã chọn giọng lưu trữ cho Engine: {name}")

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
            if not ref_text:
                self.log(f"Đang tự động nhận dạng văn bản cho giọng mẫu: {os.path.basename(ref_audio)} (ASR)...")
                try:
                    if loaded_model._asr_pipe is None:
                        loaded_model.load_asr_model()
                    ref_text = loaded_model.transcribe(ref_audio)
                    self.log(f"Đã nhận dạng thành công: \"{ref_text}\"")
                    # Lưu lại file txt để tăng tốc cho lần sau
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(ref_text)
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

    def _call_cloud_api(self, text, language, ref_audio, ref_text, instruct_str, speed, num_step, progress_cb=None):
        from gradio_client import Client, handle_file
        import shutil
        
        server_url = self.api_server_url_var.get().strip()
        if server_url.endswith("/"):
            server_url = server_url[:-1]
            
        try:
            if progress_cb:
                progress_cb(10, 100)
                
            self.log(f"Đang kết nối tới Cloud Server: {server_url}")
            client = Client(server_url, timeout=180)
            
            if progress_cb:
                progress_cb(30, 100)
                
            ref_file_param = None
            if ref_audio and os.path.exists(ref_audio):
                ref_file_param = handle_file(ref_audio)
                
            self.log(f"Đang gửi yêu cầu sinh giọng nói tới Cloud Server...")
            
            result = client.predict(
                text=text,
                language=language or "Auto",
                ref_audio_path=ref_file_param,
                ref_text=ref_text or "",
                instruct=instruct_str or "Auto",
                speed=float(speed),
                num_step=int(num_step),
                api_name="/generate"
            )
            
            if progress_cb:
                progress_cb(90, 100)
                
            if not result or not os.path.exists(result):
                raise Exception("Server trả về kết quả rỗng hoặc không tìm thấy file.")
                
            temp_dir = os.path.join(output_dir, "temp_chunks")
            os.makedirs(temp_dir, exist_ok=True)
            filename = f"chunk_{time.strftime('%Y%m%d_%H%M%S')}_cloud.wav"
            filepath = os.path.join(temp_dir, filename)
            
            shutil.copy(result, filepath)
            
            if progress_cb:
                progress_cb(100, 100)
                
            return filepath
            
        except Exception as e:
            raise Exception(f"Lỗi kết nối hoặc xử lý qua Gradio Cloud: {e}")

    def generate_chunk_worker(self, chunk_info, raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo):
        global loaded_model, model_generating
        import soundfile as sf
        
        lang = self.engine_lang_var.get()
        language = lang if lang != "Auto" else None
        speed = float(self.engine_speed_var.get())
        num_step = int(self.engine_steps_var.get())
        
        # Giải quyết các tham số tham chiếu và phong cách an toàn trong luồng phụ
        ref_audio, ref_text, instruct_str = self._resolve_engine_parameters(
            raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo
        )
        
        self.log(f"Đang sinh đoạn {chunk_info['index']}...")
        
        temp_dir = os.path.join(output_dir, "temp_chunks")
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            def progress_cb(step, total_steps):
                pct = int(step / total_steps * 100)
                self.root.after(0, lambda: self.tree_chunks.item(
                    chunk_info['item_id'], 
                    values=(chunk_info['index'], chunk_info['text'], f"Đang xử lý ({pct}%)", "")
                ))

            if "Cloud API" in self.run_mode_var.get():
                filepath = self._call_cloud_api(
                    text=chunk_info['text'],
                    language=language,
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                    instruct_str=instruct_str,
                    speed=speed,
                    num_step=num_step,
                    progress_cb=progress_cb
                )
            else:
                audio_data = loaded_model.generate(
                    text=chunk_info['text'],
                    language=language,
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                    instruct=instruct_str,
                    speed=speed,
                    num_step=num_step,
                    progress_callback=progress_cb
                )
                filename = f"chunk_{time.strftime('%Y%m%d_%H%M%S')}_{chunk_info['index']}.wav"
                filepath = os.path.join(temp_dir, filename)
                sf.write(filepath, audio_data[0], loaded_model.sampling_rate)
            
            chunk_info['status'] = "Hoàn thành"
            chunk_info['file_path'] = filepath
            
            self.root.after(0, lambda: self.tree_chunks.item(
                chunk_info['item_id'], 
                values=(chunk_info['index'], chunk_info['text'], "Hoàn thành", filepath)
            ))
            self.log(f"Đã sinh xong đoạn {chunk_info['index']} -> {filename}")
            
        except Exception as e:
            chunk_info['status'] = "Lỗi"
            self.root.after(0, lambda: self.tree_chunks.item(
                chunk_info['item_id'], 
                values=(chunk_info['index'], chunk_info['text'], "Lỗi", "")
            ))
            self.log(f"Lỗi khi sinh đoạn {chunk_info['index']}: {e}", "ERROR")
            
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
        
        lang = self.engine_lang_var.get()
        language = lang if lang != "Auto" else None
        speed = float(self.engine_speed_var.get())
        num_step = int(self.engine_steps_var.get())
        
        # Giải quyết các tham số tham chiếu và phong cách an toàn trong luồng phụ
        ref_audio, ref_text, instruct_str = self._resolve_engine_parameters(
            raw_ref_audio, raw_ref_text, raw_pitch, raw_style, raw_voice_combo
        )
        
        temp_dir = os.path.join(output_dir, "temp_chunks")
        os.makedirs(temp_dir, exist_ok=True)
        
        success_count = 0
        for chunk in self.chunks_data:
            chunk['status'] = "Đang xử lý..."
            self.root.after(0, lambda c=chunk: self.tree_chunks.item(c['item_id'], values=(c['index'], c['text'], "Đang xử lý...", "")))
            
            try:
                def make_progress_cb(ch):
                    return lambda step, total_steps: self.root.after(0, lambda: self.tree_chunks.item(
                        ch['item_id'], 
                        values=(ch['index'], ch['text'], f"Đang xử lý ({int(step / total_steps * 100)}%)", "")
                    ))

                if "Cloud API" in self.run_mode_var.get():
                    filepath = self._call_cloud_api(
                        text=chunk['text'],
                        language=language,
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        instruct_str=instruct_str,
                        speed=speed,
                        num_step=num_step,
                        progress_cb=make_progress_cb(chunk)
                    )
                else:
                    audio_data = loaded_model.generate(
                        text=chunk['text'],
                        language=language,
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        instruct=instruct_str,
                        speed=speed,
                        num_step=num_step,
                        progress_callback=make_progress_cb(chunk)
                    )
                    filename = f"chunk_{time.strftime('%Y%m%d_%H%M%S')}_{chunk['index']}.wav"
                    filepath = os.path.join(temp_dir, filename)
                    sf.write(filepath, audio_data[0], loaded_model.sampling_rate)
                
                chunk['status'] = "Hoàn thành"
                chunk['file_path'] = filepath
                
                self.root.after(0, lambda c=chunk, path=filepath: self.tree_chunks.item(
                    c['item_id'], 
                    values=(c['index'], c['text'], "Hoàn thành", path)
                ))
                success_count += 1
                
            except Exception as e:
                chunk['status'] = "Lỗi"
                self.root.after(0, lambda c=chunk: self.tree_chunks.item(
                    c['item_id'], 
                    values=(c['index'], c['text'], "Lỗi", "")
                ))
                self.log(f"Lỗi khi sinh đoạn {chunk['index']}: {e}", "ERROR")
                
        model_generating = False
        self.log(f"Hoàn thành quá trình sinh tuần tự: {success_count}/{len(self.chunks_data)} đoạn thành công.")

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
                
        self.log("Bắt đầu gộp các đoạn âm thanh thành file duy nhất...")
        
        import soundfile as sf
        import numpy as np
        
        try:
            data_list = []
            sr = None
            for f in temp_files:
                data, samplerate = sf.read(f)
                if sr is None:
                    sr = samplerate
                data_list.append(data)
                
            if data_list:
                combined = np.concatenate(data_list, axis=0)
                sf.write(dest_path, combined, sr)
                
                self.log(f"Đã gộp thành công file hoàn chỉnh tại: {dest_path}")
                messagebox.showinfo("Thành công", f"Đã gộp và xuất file thành công tại:\n{dest_path}")
                
                self.log("Đang dọn dẹp các tệp nhỏ tạm thời...")
                for f in temp_files:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
                
                for chunk in self.chunks_data:
                    if chunk['file_path'] in temp_files:
                        chunk['file_path'] = None
                        self.tree_chunks.item(chunk['item_id'], values=(chunk['index'], chunk['text'], chunk['status'], "Đã dọn dẹp"))
                        
                self.log("Đã dọn dẹp xong toàn bộ tệp tạm.")
                
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
                stderr=subprocess.DEVNULL
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
        root.destroy()
        sys.exit(0)


    root = tk.Tk()
    app = OmniVoiceGUI(root)
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
