# HƯỚNG DẪN CÀI ĐẶT GOOGLE COLAB & SỬ DỤNG OMNIVOICE CLOUD API

Tài liệu này hướng dẫn chi tiết từng bước cách thiết lập và sử dụng kiến trúc **Client-Server (Cloud GPU)** giúp bạn chạy mô hình sinh giọng nói OmniVoice trên card đồ họa Tesla T4 miễn phí của Google Colab, giúp máy tính cá nhân của bạn (card GTX 1060 3GB) hoàn toàn được giải phóng RAM/VRAM và tăng tốc độ sinh giọng nói lên gấp nhiều lần.

---

## 📋 TÓM TẮT QUY TRÌNH
1. **Nén thư mục dự án thành file `.zip`** và tải lên Google Drive của bạn.
2. **Khởi chạy Server trên Google Colab** bằng file Notebook có sẵn.
3. **Lấy link kết nối công khai** (Gradio URL).
4. **Cấu hình trên Tool cục bộ** để bắt đầu sinh giọng nói.

---

## 🛠️ CHI TIẾT CÁC BƯỚC THỰC HIỆN

### BƯỚC 1: Đưa mã nguồn dự án lên Cloud (Chọn 1 trong 3 cách dưới đây)

#### PHƯƠNG ÁN A: Sử dụng Google Drive (Nén ZIP)
1. Trên máy tính của bạn, truy cập vào thư mục dự án: `E:\Tool Youtube\OmniVoice-0.1.5\OmniVoice-0.1.5`.
2. Chọn toàn bộ file bên trong (không cần nén thư mục ảo `.venv` và `dist`) -> Nén thành file `OmniVoice-0.1.5.zip`.
3. Tải file `OmniVoice-0.1.5.zip` này lên thư mục gốc Google Drive của bạn (`My Drive`).

#### PHƯƠNG ÁN B: Sử dụng GitHub Repository (Khuyên dùng cho lập trình viên/Đồng bộ nhanh nhất)
Cách này giúp bạn đồng bộ code tức thì mỗi khi có thay đổi trên máy tính mà không cần mất công nén zip hay upload lại lên Drive/Kaggle:
1. Tạo một tài khoản [GitHub](https://github.com/) (nếu chưa có).
2. Tạo một Repository mới trên GitHub (Ví dụ đặt tên là: `OmniVoice-Server`).
   * Bạn có thể chọn chế độ **Public** (Công khai) hoặc **Private** (Riêng tư).
3. Đẩy (push) toàn bộ mã nguồn của thư mục `OmniVoice-0.1.5` cục bộ lên GitHub Repo vừa tạo (Hãy tạo file `.gitignore` để bỏ qua thư mục `.venv`, `build`, và `dist`).
4. Copy đường dẫn liên kết clone của Repository (dạng `https://github.com/username/OmniVoice-Server.git`).
   * *Nếu dùng Repo Private, bạn cần tạo Personal Access Token (PAT) trên GitHub và sửa link clone thành: `https://<TOKEN>@github.com/username/OmniVoice-Server.git` để có quyền clone trên Colab/Kaggle.*

#### PHƯƠNG ÁN C: Tạo Kaggle Dataset (Riêng cho Kaggle)
1. Nén thư mục dự án thành file `OmniVoice-0.1.5.zip`.
2. Vào Kaggle -> **Create** -> **New Dataset** -> Tải file zip lên và tạo.

---

### BƯỚC 2A: Khởi chạy Server trên Google Colab
1. Truy cập vào trang [Google Colab](https://colab.research.google.com/).
2. Nhấp vào nút **Tải lên** (Upload) và chọn file Notebook mẫu nằm trong dự án của bạn:
   `E:\Tool Youtube\OmniVoice-0.1.5\OmniVoice-0.1.5\server_api\OmniVoice_Colab_Server.ipynb`
3. Sau khi tải lên thành công, hãy kiểm tra loại môi trường chạy (Runtime):
   * Góc trên bên phải giao diện Colab, bấm vào nút mũi tên cạnh biểu tượng RAM/Disk -> Chọn **Thay đổi loại thời gian chạy** (Change runtime type).
   * Đảm bảo cấu hình là **T4 GPU** (được cung cấp miễn phí). Bấm **Lưu**.
4. Chạy ô mã lệnh đầu tiên (**Cell 1: Mount Google Drive**):
   * Nhấp nút Play ở bên trái ô mã lệnh.
   * Colab sẽ hiển thị yêu cầu kết nối với Google Drive của bạn -> Chọn **Kết nối với Google Drive** và cấp quyền truy cập.
5. Chạy ô mã lệnh thứ hai (**Cell 2: Giải nén & Khởi động API Server**):
   * Nhấp nút Play.
   * Quá trình này sẽ tự động giải nén file `OmniVoice-0.1.5.zip` từ Drive của bạn vào môi trường của Colab, tự động cài đặt các thư viện Python cần thiết, và bắt đầu khởi chạy máy chủ.
   * **Thời gian chuẩn bị**: Mất khoảng 1 - 2 phút ở lần chạy đầu tiên.

---

### BƯỚC 2B: Khởi chạy Server trên Kaggle Notebooks (Có 2 cách đưa Code lên)
Kaggle Notebooks cung cấp 30 giờ GPU/tuần và có thể chạy liên tục lên tới 12 tiếng. 

#### CÁCH 1: Upload code thành "Kaggle Dataset" (Khuyên dùng - Nhanh & Ổn định nhất)
Cách này giúp mount thẳng file zip code của bạn từ hệ thống lưu trữ của Kaggle vào Notebook cực nhanh và ổn định mà không cần internet tải xuống:
1. Nén toàn bộ thư mục dự án `OmniVoice-0.1.5` trên máy tính của bạn thành file `.zip` (ví dụ đặt tên là `OmniVoice-0.1.5.zip`).
2. Vào trang [Kaggle.com](https://www.kaggle.com/) -> Chọn **Create** -> **New Dataset**.
3. Đặt tên cho Dataset (ví dụ: `omnivoice-source`) -> Kéo thả file `OmniVoice-0.1.5.zip` vào -> Bấm **Create**.
4. Quay lại trang chủ Kaggle -> Chọn **Create** -> **New Notebook**.
5. Nhấp vào menu **File** -> **Upload notebook** -> Chọn file notebook mẫu dành riêng cho Kaggle trong thư mục dự án của bạn:
   `E:\Tool Youtube\OmniVoice-0.1.5\OmniVoice-0.1.5\server_api\OmniVoice_Kaggle_Server.ipynb`
6. Nhìn sang cột menu bên phải màn hình Notebook -> Tìm phần **Data** -> Chọn **Add Input** (hoặc **Add Data**):
   * Chọn tab **Your Datasets** -> Tìm kiếm tên dataset của bạn (ví dụ: `omnivoice-source`).
   * Bấm nút **+** (Add) cạnh tên Dataset để mount nó vào Notebook.
7. Cấu hình phần cứng ở cột bên phải (Settings):
   * Mục **Accelerator**: Chọn **GPU T4 x2** hoặc **GPU P100**.
   * Mục **Internet**: Bật **Internet ON**.
8. Bấm chạy lần lượt **Cell 1** (sao chép giải nén từ Dataset) và **Cell 3** (khởi chạy Server).

#### CÁCH 2: Tải file zip từ Google Drive về Kaggle qua gdown (Lựa chọn thay thế)
1. Mở Google Drive, click chuột phải vào file `OmniVoice-0.1.5.zip` -> Chọn **Chia sẻ** (Share) -> Đổi quyền truy cập sang **Bất kỳ ai có liên kết đều có thể xem** (Anyone with the link can view).
2. Copy đường dẫn liên kết, ví dụ: `https://drive.google.com/file/d/1A2B3C4D5E6F/view?usp=sharing`. Lấy mã ID của file là: **`1A2B3C4D5E6F`**.
3. Tạo New Notebook trên Kaggle, upload file notebook **`OmniVoice_Kaggle_Server.ipynb`** lên.
4. Bật **GPU** và **Internet ON** ở cột menu bên phải.
5. Tại **CÁCH 2** của Notebook trên Kaggle:
   * Thay thế giá trị của biến `FILE_ID` bằng ID file của bạn (ví dụ: `FILE_ID = "1A2B3C4D5E6F"`).
   * Bấm chạy cell tải gdown và giải nén.
6. Chạy **Cell 3** để khởi động Server Gradio Tunnel.

---

### BƯỚC 3: Lấy Link kết nối công khai (Gradio Share URL)
Sau khi Cell 2 chạy xong và nạp xong mô hình OmniVoice lên GPU, bạn hãy nhìn xuống phần hiển thị kết quả (Console Output) của ô mã lệnh đó:
1. Tìm dòng chữ có chứa thông tin như sau:
   `Running on public URL: https://xxxxxx.gradio.live`
2. **Copy toàn bộ đường link này** (chú ý: đây là đường link động và sẽ thay đổi mỗi khi bạn khởi động lại Colab).

---

### BƯỚC 4: Cấu hình và Sử dụng Tool trên Máy tính cục bộ
1. Mở thư mục chứa file chạy của Tool trên máy tính: `E:\Tool Youtube\OmniVoice-0.1.5\OmniVoice-0.1.5\dist\OmniVoiceStudio`.
2. Mở file thực thi **`OmniVoiceStudio.exe`** (hoặc chạy qua file kích hoạt `Khoi_Dong_OmniVoiceStudio.vbs`).
3. Chuyển sang tab **"Cài đặt & Tải Model"**:
   * Tại mục **Chế độ hoạt động (Run Mode)**: Chọn `Cloud API (Chạy trên Colab/Kaggle)`.
     *(Ngay lập tức, bạn sẽ thấy nút "Nạp mô hình vào RAM/VRAM" bị vô hiệu hóa cùng dòng trạng thái chuyển sang màu xanh thông báo "Chế độ Cloud: Mô hình chạy từ xa, không cần nạp cục bộ").*
   * Tại mục **Địa chỉ Cloud API Server**: Dán đường link `https://xxxxxx.gradio.live` đã copy ở Bước 3 vào.
   * Bấm nút **💾 Lưu cấu hình & cài đặt**.
4. Quay lại tab **"Cỗ máy tạo âm thanh" (Engine)** hoặc các tab sinh giọng:
   * Nhập nội dung văn bản của bạn.
   * Chọn giọng đọc mẫu mà bạn đã clone hoặc để mặc định.
   * Bấm **Chia đoạn văn bản** rồi bấm **Tạo tất cả các đoạn** hoặc **Tạo đoạn đang chọn**.
   * Hệ thống sẽ tự động tải file giọng mẫu lên Colab, xử lý sinh âm thanh trên GPU Tesla T4 siêu tốc và trả file nhạc `.wav` hoàn chỉnh về máy tính của bạn trong tích tắc mà card đồ họa GTX 1060 của bạn không bị tăng nhiệt độ hay tốn VRAM!

---

## 🔄 HƯỚNG DẪN XOAY VÒNG TÀI KHOẢN KHI HẾT HẠN GPU MIỄN PHÍ

Google Colab cấp cho mỗi tài khoản Gmail khoảng **12 giờ chạy GPU miễn phí mỗi ngày**. Nếu bạn dùng nhiều tài khoản để treo tool liên tục 24/7, hãy làm theo mẹo cực kỳ đơn giản sau:

1. **Chuẩn bị nhiều tài khoản Gmail phụ**. Tải file `OmniVoice-0.1.5.zip` lên Google Drive của tất cả các tài khoản này (hoặc chia sẻ quyền truy cập tệp tin từ Drive chính sang các Drive phụ để đỡ phải tải lên nhiều lần).
2. Khi tài khoản Colab thứ nhất hết quota (báo lỗi giới hạn GPU):
   * Bấm nút dừng hoặc tắt tab Colab cũ đi.
   * Đăng nhập Colab bằng tài khoản Gmail thứ hai.
   * Mở file Notebook và chạy tương tự các Bước 2, Bước 3 để nhận một đường link `https://yyyyyy.gradio.live` mới.
   * Dán link mới này vào ứng dụng `OmniVoiceStudio.exe` trên máy tính của bạn, bấm **Lưu cấu hình** là có thể tiếp tục sử dụng ngay lập tức mà không cần khởi động lại phần mềm trên máy tính!
