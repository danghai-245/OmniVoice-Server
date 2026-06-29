# HƯỚNG DẪN CÀI ĐẶT & SỬ DỤNG OMNIVOICE CLOUD API QUA GITHUB

Tài liệu này hướng dẫn chi tiết từng bước cách thiết lập và sử dụng kiến trúc **Client-Server (Cloud GPU)** giúp bạn chạy mô hình sinh giọng nói OmniVoice trên card đồ họa GPU miễn phí của Google Colab và Kaggle Notebooks. 

Phương pháp đồng bộ qua **GitHub Repository** giúp bạn kết nối mã nguồn một cách nhanh chóng, đồng bộ tức thì mỗi khi cập nhật tool mà không cần mất công nén zip hay tải lên thủ công.

---

## 📋 TÓM TẮT QUY TRÌNH
1. **Đẩy mã nguồn lên GitHub** (Chỉ cần làm một lần duy nhất).
2. **Khởi chạy Server trên Google Colab / Kaggle** qua Notebook mẫu.
3. **Lấy link kết nối công khai** (Gradio Live URL).
4. **Cấu hình trên Tool cục bộ** để bắt đầu tạo giọng nói.

---

## 🛠️ CHI TIẾT CÁC BƯỚC THỰC HIỆN

### BƯỚC 1: Đưa mã nguồn lên GitHub
1. Tạo một tài khoản [GitHub](https://github.com/) (nếu chưa có).
2. Tạo một Repository mới trên GitHub (Ví dụ đặt tên là: `OmniVoice-Server`).
   * Bạn có thể chọn chế độ **Public** (Công khai) hoặc **Private** (Riêng tư).
3. Đẩy (push) toàn bộ mã nguồn của thư mục `OmniVoice-0.1.5` cục bộ của bạn lên GitHub Repo vừa tạo.
   * *Mẹo: Hãy sử dụng file `.gitignore` để bỏ qua các thư mục nặng không cần thiết như `.venv`, `build`, và `dist`.*
4. Copy đường dẫn clone của Repository (ví dụ: `https://github.com/username/OmniVoice-Server.git`).
   * *Nếu chọn Repo Private, bạn cần tạo Personal Access Token (PAT) trên GitHub và sửa link clone thành: `https://<TOKEN>@github.com/username/OmniVoice-Server.git` để cấp quyền truy cập cho Colab/Kaggle.*

---

### BƯỚC 2A: Khởi chạy Server trên Google Colab
1. Truy cập vào trang [Google Colab](https://colab.research.google.com/).
2. Nhấp vào nút **Tải lên** (Upload) và chọn file Notebook mẫu dành riêng cho Colab nằm trong dự án của bạn:
   `E:\Tool Youtube\OmniVoice-0.1.5\OmniVoice-0.1.5\server_api\OmniVoice_Colab_Server.ipynb`
3. Đảm bảo cấu hình môi trường là **T4 GPU** (Góc trên bên phải Colab -> Bấm mũi tên cạnh RAM/Disk -> Chọn **Thay đổi loại thời gian chạy** -> Chọn **T4 GPU** -> **Lưu**).
4. Tại ô mã lệnh **Bước 1: Clone mã nguồn từ GitHub**:
   * Thay thế giá trị biến `GITHUB_REPO_URL` bằng link GitHub của bạn.
   * Bấm nút Play để tiến hành clone mã nguồn về Colab.
5. Tại ô mã lệnh **Bước 2: Khởi chạy API Server**:
   * Bấm nút Play để tự động cài đặt thư viện cần thiết, tải mô hình và bắt đầu chạy máy chủ API.

---

### BƯỚC 2B: Khởi chạy Server trên Kaggle Notebooks
Kaggle cung cấp tới 30 giờ GPU miễn phí mỗi tuần và có thể chạy liên tục lên tới 12 tiếng:
1. Truy cập trang [Kaggle.com](https://www.kaggle.com/) -> Đăng nhập tài khoản.
2. Bấm **Create** -> **New Notebook**.
3. Nhấp vào menu **File** -> **Upload notebook** -> Chọn file notebook mẫu dành riêng cho Kaggle trong thư mục dự án của bạn:
   `E:\Tool Youtube\OmniVoice-0.1.5\OmniVoice-0.1.5\server_api\OmniVoice_Kaggle_Server.ipynb`
4. Cấu hình phần cứng ở cột menu bên phải (Settings):
   * Mục **Accelerator**: Chọn **GPU T4 x2** hoặc **GPU P100**.
   * Mục **Internet**: Bật **Internet ON** (Bắt buộc).
5. Tại ô mã lệnh **Bước 1: Clone mã nguồn từ GitHub**:
   * Thay đổi đường dẫn `GITHUB_REPO_URL` thành link GitHub của bạn.
   * Bấm nút Play ở bên trái ô để clone code về Kaggle.
6. Chạy tiếp ô mã lệnh **Bước 2: Khởi chạy API Server** để cài đặt môi trường và khởi động máy chủ.

---

### BƯỚC 3: Lấy Link kết nối công khai (Gradio Share URL)
Sau khi Server khởi chạy và nạp xong mô hình lên GPU, bạn hãy nhìn xuống phần hiển thị kết quả (Console Output) của ô mã lệnh khởi chạy:
1. Tìm dòng chữ có chứa thông tin như sau:
   `Running on public URL: https://xxxxxx.gradio.live`
2. **Copy toàn bộ đường link này** (chú ý: đây là đường link động và sẽ thay đổi mỗi khi bạn khởi động lại Server).

---

### BƯỚC 4: Cấu hình và Sử dụng Tool trên Máy tính
1. Mở thư mục chứa file chạy của Tool trên máy tính: `E:\Tool Youtube\OmniVoice-0.1.5\OmniVoice-0.1.5\dist\OmniVoiceStudio`.
2. Mở phần mềm **`OmniVoiceStudio.exe`**.
3. Chuyển sang tab **"Cài đặt & Tải Model"**:
   * Tại mục **Chế độ hoạt động (Run Mode)**: Chọn `Cloud API (Chạy trên Colab/Kaggle)`.
   * Tại mục **Địa chỉ Cloud API Server**: Dán đường link Gradio đã copy ở Bước 3 vào.
   * Bấm nút **💾 Lưu cấu hình & cài đặt**.
4. Quay lại tab **"Cỗ máy tạo âm thanh" (Engine)** hoặc các tab sinh giọng khác, bấm **Chia đoạn văn bản** rồi chọn **Tạo tất cả các đoạn** để tận hưởng tốc độ sinh giọng nói siêu tốc trên GPU Cloud.

---

## 🔄 HƯỚNG DẪN XOAY VÒNG TÀI KHOẢN KHI HẾT HẠN GPU MIỄN PHÍ
Khi tài khoản Colab/Kaggle hiện tại hết quota GPU miễn phí trong ngày, bạn có thể dễ dàng xoay vòng tài khoản:
1. Đăng nhập Colab hoặc Kaggle bằng một tài khoản Gmail phụ khác.
2. Mở file notebook tương ứng (`OmniVoice_Colab_Server.ipynb` hoặc `OmniVoice_Kaggle_Server.ipynb`).
3. Điền link GitHub của bạn và bấm chạy để nhận một đường link kết nối mới (dạng `https://yyyyyy.gradio.live`).
4. Dán link mới này vào tab **"Cài đặt & Tải Model"** trên tool cục bộ của bạn, bấm **Lưu cấu hình** là có thể tiếp tục sử dụng ngay lập tức mà không cần tải lại source code thủ công.

---

## 🌐 HƯỚNG DẪN CẤU HÌNH NGROK ĐỂ SỬ DỤNG DOMAIN CỐ ĐỊNH (STATIC URL)

Để tránh việc phải copy-paste lại địa chỉ URL mới mỗi khi khởi động lại máy chủ Colab/Kaggle, bạn có thể cấu hình ngrok kết hợp với một tên miền cố định miễn phí (ví dụ: `xxxx.ngrok-free.app`).

### Các bước chuẩn bị tên miền cố định trên ngrok:
1. Đăng ký hoặc đăng nhập tài khoản [ngrok.com](https://ngrok.com/).
2. Vào mục **Your Authtoken** trên trang quản trị ngrok và sao chép mã Token cá nhân của bạn.
3. Vào mục **Domains** -> Chọn **Create Domain** (ngrok cung cấp miễn phí 1 tên miền cố định dạng `xxxx.ngrok-free.app` cho mỗi tài khoản). Sao chép tên miền này.

### Cách chạy trên Colab / Kaggle với ngrok:
1. Tại ô mã lệnh **Bước 2: Khởi chạy API Server** trên giao diện Notebook Colab/Kaggle:
   * Dán mã Token vào ô `NGROK_TOKEN`.
   * Dán tên miền cố định vào ô `NGROK_DOMAIN`.
2. Tiến hành chạy ô mã lệnh. Máy chủ sẽ tự động cài đặt gói hỗ trợ `pyngrok`, thiết lập kết nối an toàn và hiển thị địa chỉ cố định của bạn.
3. Cấu hình địa chỉ cố định này (ví dụ: `https://xxxx.ngrok-free.app`) một lần duy nhất vào ô **Địa chỉ Cloud API Server** trên giao diện Tool GUI cục bộ. Từ các lần sau, bạn chỉ cần bật Server trên Colab/Kaggle lên là Tool có thể kết nối ngay lập tức mà không cần thay đổi địa chỉ kết nối nữa!
