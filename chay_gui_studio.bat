@echo off
title Khoi dong OmniVoice Studio GUI
chcp 65001 > nul

echo ==================================================
echo   Đang cấu hình các thư mục lưu trữ cache trên ổ E...
echo ==================================================

rem Tắt tính năng tạo symlink của Hugging Face trên Windows để tránh lỗi WinError 1314
set HF_HUB_DISABLE_SYMLINKS=1

rem Điều hướng toàn bộ cache tải model nặng về ổ E (cùng thư mục dự án)
set HF_HOME=%~dp0cache\huggingface
set TORCH_HOME=%~dp0cache\torch
set UV_CACHE_DIR=%~dp0cache\uv

rem Chuyển hướng các tệp tạm (Temp) phát sinh khi xử lý file âm thanh
mkdir "%~dp0cache\temp" 2>nul
set TEMP=%~dp0cache\temp
set TMP=%~dp0cache\temp

rem Chuyển hướng cache biên dịch CUDA của NVIDIA
set CUDA_CACHE_PATH=%~dp0cache\cuda

echo [INFO] Thư mục lưu trữ Model AI đã được chuyển sang: %HF_HOME%
echo [INFO] Thư mục tệp tạm (Temp) đã được chuyển sang: %TEMP%
echo.

rem Kiểm tra sự tồn tại của môi trường ảo
if not exist ".venv\Scripts\pythonw.exe" (
    echo [LỖI] Không tìm thấy thư mục môi trường ảo .venv hoặc pythonw.exe.
    echo Vui lòng đảm bảo bạn đang chạy file này ở đúng thư mục dự án OmniVoice.
    pause
    exit /b
)

echo Đang khởi chạy OmniVoice Studio GUI (không cửa sổ CMD)...
echo.
start "" ".venv\Scripts\pythonw.exe" launcher.py
