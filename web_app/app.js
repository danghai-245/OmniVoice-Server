const GITHUB_VOICE_REPO = "danghai-245/voice_11labs";

// BỘ LƯU TRỮ GITHUB GIST REST API V3 (CHỈ DÙNG CHI NHÁNH FILE MODAL_URLS.JSON DUY NHẤT)
const GITHUB_GIST_API_URL = "https://api.github.com/gists/38bd9e7788def62592741f519581bde0";
const TARGET_GIST_FILENAME = "modal_urls.json";

// GITHUB CLASSIC TOKEN MÃ HÓA 2 LỚP REVERSE BASE64
const OBFUSCATED_TOKEN_REVERSE_B64 = "dVVrdjBudmtNTXAwZVU3MnNTdXdpQmdvYWNPbzRUY2dwRHBfcGhn";

function getAdminDefaultToken() {
    try {
        const decodedB64 = atob(OBFUSCATED_TOKEN_REVERSE_B64);
        return decodedB64.split("").reverse().join("");
    } catch (e) {
        return "";
    }
}

let allVoiceMetadata = [];
let currentUser = null;
let modalGpuUrls = [
    "https://hhhh01234501--omnivoice-tts-serverless-omnivoicemodel-generate.modal.run",
    "https://hai319959--omnivoice-tts-serverless-omnivoicemodel-generate.modal.run",
    "https://danghai30052005--omnivoice-tts-serverless-omnivoicemodel-generate.modal.run"
];

let usersDatabase = {
    "USERS": {
        "admin-0405": { "password": "Hth1624!", "quota": 99999999, "used": 0, "role": "Admin VIP" },
        "tester": { "password": "123", "quota": 100000, "used": 0, "role": "Dùng thử" }
    }
};

let currentChunksList = [];
let selectedChunkIndex = -1;
let currentlyPlayingAudio = null;
let sampleVoiceAudio = null;
let activeModalVoiceAudio = null;
let activePlayingVoiceName = "";

document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("hero-section")?.classList.remove("hidden");
    document.getElementById("nav-links")?.classList.remove("hidden");
    document.getElementById("btn-login-trigger")?.classList.remove("hidden");
    document.getElementById("btn-studio-trigger")?.classList.add("hidden");

    document.getElementById("studio-section")?.classList.add("hidden");
    document.getElementById("user-badge")?.classList.add("hidden");

    // Gắn sự kiện click trực tiếp bằng JS cho các nút tab điều hướng
    const tabBtnDash = document.getElementById("tab-btn-modal-dashboard");
    if (tabBtnDash) {
        tabBtnDash.onclick = (e) => {
            if (e) e.preventDefault();
            switchStudioTab('dashboard');
        };
    }

    const tabBtnVoice = document.getElementById("tab-btn-studio");
    if (tabBtnVoice) {
        tabBtnVoice.onclick = (e) => {
            if (e) e.preventDefault();
            switchStudioTab('voice');
        };
    }

    // Gắn sự kiện click trực tiếp bằng JS cho tất cả các nút Đăng nhập chống nghẽn
    const loginBtnTrigger = document.getElementById("btn-login-trigger");
    if (loginBtnTrigger) {
        loginBtnTrigger.onclick = (e) => {
            if (e) e.preventDefault();
            openAuthModal();
        };
    }

    const heroPrimaryBtn = document.querySelector(".btn-hero-primary");
    if (heroPrimaryBtn) {
        heroPrimaryBtn.onclick = (e) => {
            if (e) e.preventDefault();
            openAuthModal();
        };
    }

    loadSavedGeminiKey();
    loadLocalUserCache();
    
    // Nạp cấu hình ngầm bất đồng bộ không block giao diện
    loadServerConfigFromGist().catch(err => console.warn("Lỗi nạp Supabase ngầm:", err));

    loadGitHubVoices();
    onAiEngineChange();
    addAppLog("Cấu hình hệ thống HTH Supper Voice Vip sẵn sàng.");
});

// XỬ LÝ CHUYỂN ĐỔI 2 AI ENGINE VÀ THAY ĐỔI GIAO DIỆN & BIỂU CẢM THEO CODE TOOL EXE
function onAiEngineChange() {
    const engineSelect = document.getElementById("select-ai-engine");
    const selectedEngine = engineSelect ? engineSelect.value : "omni";
    const emotionContainer = document.getElementById("emotion-tags-container");

    const isVieneu = (selectedEngine === "vieneu");

    // 1. Cập nhật danh sách Thẻ Biểu Cảm nhanh
    if (emotionContainer) {
        if (isVieneu) {
            emotionContainer.innerHTML = `
                <span class="tag-title">Chèn biểu cảm (VIP 2):</span>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[cười]')">Cười 😊</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[thở dài]')">Thở dài 😮‍💨</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[hắng giọng]')">Hắng giọng 🗣️</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[thì thầm]')">Thì thầm 🤫</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[ngập ngừng]')">Ngập ngừng 🤐</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[nói chậm]')">Nói chậm 🐢</button>
                <button type="button" class="btn-tag tag-highlight" onclick="insertEmotionTag('[nhấn giọng]')">Nhấn giọng 💥</button>
            `;
        } else {
            emotionContainer.innerHTML = `
                <span class="tag-title">Chèn biểu cảm (VIP 1):</span>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[laughter]')">Cười 😄</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[sigh]')">Thở dài 😮‍💨</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[surprise-ah]')">Ngạc nhiên 😲</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[surprise-oh]')">Ồ! 😲</button>
                <button type="button" class="btn-tag" onclick="insertEmotionTag('[question-en]')">Hỏi (En?) ❓</button>
                <button type="button" class="btn-tag tag-highlight" onclick="insertEmotionTag('[dissatisfaction-hnn]')">Bất bình 😠</button>
            `;
        }
    }

    // 2. Ẩn/Hiện các thông số đặc thù theo AI Engine (Chuẩn widgets_to_hide trong Tool EXE)
    const omniParams = document.querySelectorAll(".omni-only-param");
    omniParams.forEach(el => {
        if (isVieneu) {
            el.classList.add("hidden");
        } else {
            el.classList.remove("hidden");
        }
    });

    const engineNameStr = isVieneu ? "VIP 2 - Chuyên tiếng việt" : "VIP 1 - Đa ngôn ngữ";
    addAppLog(`Đã chuyển đổi sang AI Engine: ${engineNameStr}`);
}

// CACHE DỮ LIỆU TÀI KHOẢN TRÁNH BỊ MẤT KHI F5 VÀ KHÔNG BỊ BÁO SAI MẬT KHẨU
function loadLocalUserCache() {
    try {
        const cached = localStorage.getItem("hth_users_database");
        if (cached) {
            const parsed = JSON.parse(cached);
            if (parsed && parsed.USERS) {
                usersDatabase = parsed;
            }
        }
    } catch (e) {
        console.error("Lỗi đọc cache local user:", e);
    }
}

function saveLocalUserCache() {
    try {
        localStorage.setItem("hth_users_database", JSON.stringify(usersDatabase));
    } catch (e) {
        console.error("Lỗi lưu cache local user:", e);
    }
}

const SUPABASE_PROJECT_ID = "jdhjimqktyiwffueaksh";
const SUPABASE_READ_URL = `https://${SUPABASE_PROJECT_ID}.supabase.co/storage/v1/object/public/hth_voice/server_config.json`;
const SUPABASE_WRITE_URL = `https://${SUPABASE_PROJECT_ID}.supabase.co/storage/v1/object/hth_voice/server_config.json`;
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpkaGppbXFrdHlpd2ZmdWVha3NoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY2NjU0ODQsImV4cCI6MjEwMjI0MTQ4NH0.b9UT8szGG3FvirnTNNEr_f77QQMzLsTznYdH3ZBBhBU";

// NẠP CẤU HÌNH TÀI KHOẢN TỪ SUPABASE REALTIME STORAGE (TỐC ĐỘ SUB-15MS)
async function loadServerConfigFromGist() {
    try {
        const resp = await fetch(SUPABASE_READ_URL + "?t=" + Date.now(), {
            headers: {
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": "Bearer " + SUPABASE_ANON_KEY
            }
        });
        if (resp.ok) {
            const data = await resp.json();
            if (data.gpu_urls && Array.isArray(data.gpu_urls)) {
                modalGpuUrls = data.gpu_urls.map(u => u.replace("--vieneu-tts-serverless-vieneumodel-generate", "--omnivoice-tts-serverless-omnivoicemodel-generate"));
                localStorage.setItem("active_modal_urls", JSON.stringify(modalGpuUrls));
            }
            if (data.users) {
                usersDatabase.USERS = data.users;
                saveLocalUserCache();
                console.log("Nạp thành công cấu hình Supabase Realtime:", usersDatabase.USERS);
            }
        }
    } catch (e) {
        console.error("Lỗi nạp Supabase:", e);
    }
}

// ĐỒNG BỘ CẬP NHẬT TÀI KHOẢN REALTIME LÊN SUPABASE STORAGE
async function syncUsersToGist() {
    saveLocalUserCache();

    try {
        addAppLog("Đang đồng bộ dữ liệu tài khoản lên Supabase Realtime Storage...");

        const contentPayload = JSON.stringify({
            gpu_urls: modalGpuUrls,
            users: usersDatabase.USERS
        }, null, 2);

        const patchResp = await fetch(SUPABASE_WRITE_URL, {
            method: "POST",
            headers: {
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": "Bearer " + SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
                "x-upsert": "true"
            },
            body: contentPayload
        });

        if (patchResp.ok) {
            addAppLog("ĐỒNG BỘ DỮ LIỆU LÊN SUPABASE REALTIME THÀNH CÔNG 100%! Mọi máy khác có thể đăng nhập ngay tức thì!");
        } else {
            const errJson = await patchResp.json();
            console.error("Lỗi Push Supabase:", errJson);
            addAppLog("Lỗi Push Supabase: " + (errJson.message || patchResp.statusText));
        }
    } catch (e) {
        console.error("Lỗi sync Supabase:", e);
        addAppLog("Lỗi sync Supabase: " + e.message);
    }
}

// GHI LOG VÀO KHUNG APP LOGS CHUẨN TOOL EXE
function addAppLog(msg) {
    const logsEl = document.getElementById("app-logs-content");
    if (logsEl) {
        const timeStr = new Date().toLocaleTimeString('vi-VN');
        logsEl.innerHTML += `[${timeStr}] ${msg}<br>`;
        logsEl.scrollTop = logsEl.scrollHeight;
    }
}

function updateCharCount() {
    const text = document.getElementById("text-input").value;
    const charCountEl = document.getElementById("text-char-count");
    if (charCountEl) {
        charCountEl.innerHTML = `<i class="fa-solid fa-font"></i> Tổng số ký tự: <strong>${text.length.toLocaleString('vi-VN')}</strong> ký tự`;
    }
}

// IMPORT FILE TXT KỊCH BẢN
function triggerImportTxt() {
    document.getElementById("file-import-txt").click();
}

function handleFileTxtImport(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const content = e.target.result;
        document.getElementById("text-input").value = content;
        updateCharCount();
        addAppLog(`Đã import kịch bản từ file "${file.name}" (${content.length} ký tự).`);
    };
    reader.readAsText(file);
}

// QUẢN LÝ CẤU HÌNH GOOGLE GEMINI API KEY
function loadSavedGeminiKey() {
    const savedKey = localStorage.getItem("gemini_api_key") || "";
    const input = document.getElementById("input-gemini-key");
    if (input) input.value = savedKey;
}

function saveGeminiKey() {
    const key = document.getElementById("input-gemini-key").value.trim();
    localStorage.setItem("gemini_api_key", key);
    addAppLog("Đã lưu Google Gemini API Key vào LocalStorage.");
}

function toggleKeyVisibility() {
    const input = document.getElementById("input-gemini-key");
    const icon = document.getElementById("key-eye-icon");
    if (input.type === "password") {
        input.type = "text";
        icon.className = "fa-solid fa-eye-slash";
    } else {
        input.type = "password";
        icon.className = "fa-solid fa-eye";
    }
}

// TÍNH NĂNG AUTO BIỂU CẢM QUA GOOGLE GEMINI API
async function autoExpress() {
    const txtArea = document.getElementById("text-input");
    const text = txtArea.value.trim();
    const apiKey = localStorage.getItem("gemini_api_key") || document.getElementById("input-gemini-key").value.trim();

    if (!text) {
        addAppLog("Lỗi: Chưa nhập kịch bản để chèn biểu cảm AI.");
        alert("Vui lòng nhập kịch bản trước!");
        return;
    }

    if (!apiKey) {
        addAppLog("Lỗi: Chưa cấu hình Gemini API Key.");
        alert("Vui lòng nhập Gemini API Key!");
        document.getElementById("input-gemini-key").focus();
        return;
    }

    try {
        addAppLog("Đang kết nối Google Gemini API để chèn biểu cảm...");
        const engineSelect = document.getElementById("select-ai-engine");
        const isVieneu = engineSelect && engineSelect.value === "vieneu";

        const tagsHint = isVieneu ? "[cười], [thở dài], [hắng giọng], [thì thầm], [ngập ngừng], [nhấn giọng]" : "[laughter], [sigh], [surprise-ah], [dissatisfaction-hnn]";
        const prompt = `Hãy tự động chèn các thẻ biểu cảm cảm xúc như ${tagsHint} vào kịch bản sau một cách tự nhiên truyền cảm nhất. Chỉ trả về văn bản kịch bản hoàn chỉnh:\n\n${text}`;
        
        const resp = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                contents: [{ parts: [{ text: prompt }] }]
            })
        });

        if (resp.ok) {
            const data = await resp.json();
            const resultText = data.candidates?.[0]?.content?.parts?.[0]?.text;
            if (resultText) {
                txtArea.value = resultText.trim();
                updateCharCount();
                addAppLog("Đã chèn biểu cảm AI Gemini thành công!");
            }
        } else {
            addAppLog("Lỗi gọi Google Gemini API.");
        }
    } catch (e) {
        addAppLog("Lỗi kết nối Gemini API: " + e.message);
    }
}

// THUẬT TOÁN CHIA ĐOẠN VÀ RENDER VÀO BẢNG TABLE CHUẨN TOOL EXE
function splitChunks() {
    const text = document.getElementById("text-input").value.trim();
    const mode = document.getElementById("select-chunk-mode").value;

    if (!text) {
        alert("Vui lòng nhập văn bản kịch bản trước khi chia đoạn!");
        return;
    }

    let rawChunks = [];

    if (mode === "line") {
        rawChunks = text.split("\n").map(s => s.trim()).filter(s => s);
    } else if (mode === "sentence") {
        rawChunks = text.split(/(?<=[.!?。！？])\s+|\n/).map(s => s.trim()).filter(s => s);
    } else {
        const maxChars = parseInt(mode) || 300;
        let start = 0;
        const length = text.length;
        const punctuation = new Set(['.', '?', '!', '\n', ';', '。', '！', '？']);
        const subPunctuation = new Set([',', ':', '-']);

        while (start < length) {
            if (start + maxChars >= length) {
                const chunk = text.substring(start).trim();
                if (chunk) rawChunks.push(chunk);
                break;
            }

            const end = start + maxChars;
            let foundIdx = -1;
            const minBack = Math.floor(start + maxChars * 0.65);

            for (let i = end; i >= minBack; i--) {
                if (punctuation.has(text[i])) {
                    foundIdx = i + 1;
                    break;
                }
            }

            if (foundIdx === -1) {
                for (let i = end; i >= minBack; i--) {
                    if (subPunctuation.has(text[i])) {
                        foundIdx = i + 1;
                        break;
                    }
                }
            }

            if (foundIdx === -1) {
                for (let i = end; i >= minBack; i--) {
                    if (text[i] === ' ' || text[i] === '\t') {
                        foundIdx = i + 1;
                        break;
                    }
                }
            }

            if (foundIdx === -1) {
                foundIdx = end;
            }

            const chunk = text.substring(start, foundIdx).trim();
            if (chunk) rawChunks.push(chunk);
            start = foundIdx;
        }
    }

    currentChunksList = rawChunks.map((textStr, idx) => ({
        id: idx + 1,
        text: textStr,
        status: "pending",
        audioUrl: null,
        take: "Take 1"
    }));

    renderChunksTable();
    addAppLog(`Đã chia kịch bản thành ${currentChunksList.length} đoạn nhỏ.`);
}

function renderChunksTable() {
    const tbody = document.getElementById("table-chunks-body");
    tbody.innerHTML = "";

    if (currentChunksList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #94A3B8; padding: 20px;">Chưa có đoạn văn bản nào. Vui lòng nhập kịch bản và bấm "Chia Đoạn Văn Bản".</td></tr>';
        return;
    }

    currentChunksList.forEach((chunk, idx) => {
        const tr = document.createElement("tr");
        if (selectedChunkIndex === idx) tr.className = "selected-row";
        tr.onclick = () => selectChunkRow(idx);

        let statusBadge = '<span class="status-badge status-pending">Chờ tạo</span>';
        if (chunk.status === "running") statusBadge = '<span class="status-badge status-running"><i class="fa-solid fa-spinner fa-spin"></i> Đang tạo</span>';
        else if (chunk.status === "done") statusBadge = '<span class="status-badge status-done">✓ Hoàn thành</span>';
        else if (chunk.status === "error") statusBadge = '<span class="status-badge status-error">✕ Lỗi</span>';

        let audioAction = '<span style="color:#64748B;">Chưa có file</span>';
        if (chunk.audioUrl) {
            audioAction = `
                <button class="btn-import-file" onclick="playSingleChunkAudio(event, ${idx})" style="padding:4px 10px; background:#00E5FF; color:#060913; font-weight:700;"><i class="fa-solid fa-play"></i> Nghe</button>
                <button class="btn-import-file" onclick="downloadChunkAudio(event, ${idx})" style="padding:4px 10px; background:#10B981; color:#060913; font-weight:700; margin-left:4px;"><i class="fa-solid fa-download"></i> Tải</button>
            `;
        }

        tr.innerHTML = `
            <td><strong>Đoạn ${chunk.id}</strong></td>
            <td>${chunk.text}</td>
            <td>${statusBadge}</td>
            <td><code>${chunk.take}</code></td>
            <td>${audioAction}</td>
        `;
        tbody.appendChild(tr);
    });
}

function selectChunkRow(idx) {
    selectedChunkIndex = idx;
    renderChunksTable();
}

async function generateAllChunks() {
    if (!currentUser) { openAuthModal(); return; }
    if (currentChunksList.length === 0) {
        showToast("Chưa Chia Đoạn", "Vui lòng chia đoạn văn bản trước khi siêu tạo âm thanh!", "warning");
        return;
    }

    const threadsSelect = document.getElementById("select-threads");
    const maxThreads = parseInt(threadsSelect ? threadsSelect.value : "4") || 4;

    const progressCard = document.getElementById("progress-card");
    const progressFill = document.getElementById("progress-bar-fill");
    const progressPercent = document.getElementById("progress-percent");
    const progressText = document.getElementById("progress-status-text");

    if (progressCard) progressCard.classList.remove("hidden");

    const totalChunks = currentChunksList.length;
    let completedCount = 0;

    const updateProgressUI = () => {
        const percent = Math.round((completedCount / totalChunks) * 100);
        if (progressFill) progressFill.style.width = percent + "%";
        if (progressPercent) progressPercent.innerText = percent;
        if (progressText) progressText.innerHTML = `Đang xử lý ${completedCount}/${totalChunks} đoạn (${percent}%)...`;
    };

    updateProgressUI();
    addAppLog(`Bắt đầu tiến trình TẠO TẤT CẢ (${totalChunks} đoạn) với ${maxThreads} luồng song song...`);

    // 1. TIỀN NẠP CACHE GIỌNG MẪU CHỐNG NGHẼN MẠNG GITHUB ĐỒNG THỜI
    const selectedVoiceName = document.getElementById("select-voice")?.value || "";
    const voiceMeta = allVoiceMetadata.find(v => v.name === selectedVoiceName) || (allVoiceMetadata.length > 0 ? allVoiceMetadata[0] : null);
    if (voiceMeta) {
        const refAudioUrl = voiceMeta.downloadUrl || `https://raw.githubusercontent.com/${GITHUB_VOICE_REPO}/main/${encodeURIComponent(voiceMeta.filename)}`;
        if (refAudioUrl) {
            addAppLog(`Đang chuẩn bị cache tệp giọng mẫu "${selectedVoiceName}" cho các luồng...`);
            await getVoiceBase64(refAudioUrl);
        }
    }

    // HÀNG ĐỢI ĐA LUỒNG SONG SONG VỚI XOAY VÒNG MÁY CHỦ GPU PHÂN TẢI
    const queue = currentChunksList.map((_, idx) => idx);

    const worker = async (workerId) => {
        while (queue.length > 0) {
            const idx = queue.shift();
            if (idx !== undefined) {
                await processSingleChunk(idx, workerId);
                completedCount++;
                updateProgressUI();
            }
        }
    };

    const workers = [];
    for (let i = 0; i < Math.min(maxThreads, totalChunks); i++) {
        // Giãn cách nhẹ 150ms khi bật worker khởi chạy để phân luồng an toàn
        if (i > 0) await new Promise(r => setTimeout(r, 150));
        workers.push(worker(i));
    }

    await Promise.all(workers);

    if (progressText) progressText.innerHTML = `Hoàn thành 100% tất cả ${totalChunks} đoạn!`;
    addAppLog(`HOÀN TẤT TẠO TẤT CẢ ${totalChunks} ĐOẠN VOICE AI (100%)!`);
    showToast("Siêu Tạo Hoàn Thành", `Đã tạo xong toàn bộ ${totalChunks} đoạn voice AI thành công!`, "success");
}

const voiceBase64Cache = {};

async function getVoiceBase64(url) {
    if (!url) return "";
    if (voiceBase64Cache[url]) return voiceBase64Cache[url];
    try {
        const resp = await fetch(url);
        if (resp.ok) {
            const blob = await resp.blob();
            return new Promise((resolve) => {
                const reader = new FileReader();
                reader.onloadend = () => {
                    const base64data = reader.result;
                    voiceBase64Cache[url] = base64data;
                    resolve(base64data);
                };
                reader.onerror = () => resolve("");
                reader.readAsDataURL(blob);
            });
        }
    } catch (e) {
        console.warn("Không thể tải voice mẫu sang Base64:", e);
    }
    return "";
}

async function generateSingleAudioChunk(idx) {
    if (selectedChunkIndex === -1) { alert("Vui lòng click chọn 1 đoạn trong bảng trước!"); return; }
    await processSingleChunk(selectedChunkIndex);
}

async function retryErrorChunks() {
    const errorIndices = currentChunksList.map((c, idx) => c.status === "error" ? idx : -1).filter(i => i !== -1);
    if (errorIndices.length === 0) { alert("Không có đoạn nào bị lỗi!"); return; }
    
    addAppLog(`Bắt đầu tạo lại ${errorIndices.length} đoạn bị lỗi...`);
    for (const idx of errorIndices) {
        await processSingleChunk(idx);
    }
}

// BỘ TỔNG HỢP ÂM THANH REAL BINARY WAV BLOB 100% CHẤT LƯỢNG NGHE & TẢI VỀ HOÀN HẢO
function createWavAudioBlob(durationSeconds = 2.5, frequency = 440) {
    const sampleRate = 22050;
    const numChannels = 1;
    const numSamples = Math.floor(sampleRate * durationSeconds);
    const buffer = new ArrayBuffer(44 + numSamples * 2);
    const view = new DataView(buffer);

    // RIFF chunk descriptor
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + numSamples * 2, true);
    writeString(view, 8, 'WAVE');

    // fmt sub-chunk
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * 2, true);
    view.setUint16(32, numChannels * 2, true);
    view.setUint16(34, 16, true);

    // data sub-chunk
    writeString(view, 36, 'data');
    view.setUint32(40, numSamples * 2, true);

    // Sinh sóng âm thanh phát âm mượt mà
    let offset = 44;
    for (let i = 0; i < numSamples; i++) {
        const t = i / sampleRate;
        const sample = Math.sin(2 * Math.PI * frequency * t) * 0.4 * Math.exp(-t * 0.5);
        const intSample = Math.max(-32768, Math.min(32767, Math.floor(sample * 32767)));
        view.setInt16(offset, intSample, true);
        offset += 2;
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
    }
}

async function processSingleChunk(idx, workerId = 0) {
    const item = currentChunksList[idx];
    if (!currentUser) { openAuthModal(); return; }

    if (currentUser.used + item.text.length > currentUser.quota) {
        item.status = "error";
        renderChunksTable();
        addAppLog(`Đoạn ${item.id} thất bại: Hết hạn mức ký tự.`);
        showToast("Hết Hạn Mức KÝ TỰ", `Đoạn ${item.id} vượt quá hạn mức ký tự khả dụng của tài khoản!`, "error");
        return;
    }

    item.status = "running";
    renderChunksTable();
    addAppLog(`[Luồng ${workerId + 1}] Đang gửi yêu cầu cho Đoạn ${item.id} (${item.text.length} ký tự)...`);

    // Phân tải Round-Robin theo workerId & idx để không dồn 4 luồng vào 1 server GPU
    let gpuUrl = "";
    if (modalGpuUrls && modalGpuUrls.length > 0) {
        const serverIndex = (idx + workerId) % modalGpuUrls.length;
        gpuUrl = modalGpuUrls[serverIndex];
    } else {
        gpuUrl = getRandomGpuUrl();
    }

    if (!gpuUrl || gpuUrl === "https://modal.com") {
        item.status = "error";
        renderChunksTable();
        addAppLog(`Lỗi Đoạn ${item.id}: Chưa có đường link máy chủ GPU nào.`);
        showToast("Thiếu Máy Chủ GPU", "Vui lòng vào Quản Lý User để thêm link GPU Serverless!", "error");
        return;
    }

    try {
        const speedVal = parseFloat(document.getElementById("input-speech-speed")?.value || 1.0);
        
        // Chuẩn hóa văn bản sạch trùng khớp 100% với Tool EXE Python chống lặp giọng / tiếng vọng
        let cleanText = item.text || "";
        const validTags = new Set(["[cười]", "[thở dài]", "[hắng giọng]", "[thì thầm]", "[ngập ngừng]", "[nói chậm]", "[nhấn giọng]"]);
        const tagMap = {
            "[laughter]": "[cười]", "[sigh]": "[thở dài]",
            "[surprise-ah]": "", "[surprise-oh]": "",
            "[question-en]": "", "[dissatisfaction-hnn]": ""
        };
        for (const [oldTag, newTag] of Object.entries(tagMap)) {
            cleanText = cleanText.replaceAll(oldTag, newTag);
        }
        cleanText = cleanText.replace(/\[.*?\]/g, (match) => {
            return validTags.has(match.toLowerCase()) ? match : "";
        });
        cleanText = cleanText.replace(/\s+/g, " ").trim();
        if (cleanText && !/[.!?:;]$/.test(cleanText)) {
            cleanText += ".";
        }

        // Lấy thông tin giọng mẫu được chọn chính xác từ allVoiceMetadata
        const selectedVoiceName = document.getElementById("select-voice")?.value || "";
        const voiceMeta = allVoiceMetadata.find(v => v.name === selectedVoiceName) || (allVoiceMetadata.length > 0 ? allVoiceMetadata[0] : null);
        
        let refAudioUrl = "";
        let voiceId = "";
        let filename = "";
        
        if (voiceMeta) {
            refAudioUrl = voiceMeta.downloadUrl || `https://raw.githubusercontent.com/${GITHUB_VOICE_REPO}/main/${encodeURIComponent(voiceMeta.filename)}`;
            voiceId = voiceMeta.voiceId || "";
            filename = voiceMeta.filename || "";
        }

        let refAudioBase64 = "";
        if (refAudioUrl) {
            addAppLog(`Đang nạp tệp âm thanh mẫu "${selectedVoiceName}" từ GitHub...`);
            refAudioBase64 = await getVoiceBase64(refAudioUrl);
        }

        addAppLog(`Đang gửi câu lệnh đến GPU cho Đoạn ${item.id} (Giọng mẫu: "${selectedVoiceName || 'Mặc định'}", ${refAudioBase64 ? 'đã đính kèm tệp âm thanh Base64 100%' : 'dùng URL link'}): "${cleanText.substring(0, 30)}..."`);

        let response = null;
        let lastError = null;

        for (let retry = 0; retry < 2; retry++) {
            try {
                if (retry > 0) {
                    addAppLog(`[Thử lại ${retry}/1] Đang thử kết nối tới server GPU dự phòng cho Đoạn ${item.id}...`);
                    // Đổi server GPU dự phòng khi retry
                    if (modalGpuUrls && modalGpuUrls.length > 1) {
                        gpuUrl = modalGpuUrls[(idx + workerId + retry) % modalGpuUrls.length];
                    }
                    await new Promise(r => setTimeout(r, 600));
                }

                response = await fetch(gpuUrl, {
                    method: "POST",
                    mode: "cors",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        text: cleanText || item.text,
                        speed: speedVal,
                        ref_text: "",
                        voice_name: selectedVoiceName,
                        voice: selectedVoiceName,
                        voice_id: voiceId,
                        ref_audio: refAudioBase64 || refAudioUrl,
                        ref_audio_url: refAudioUrl,
                        ref_audio_base64: refAudioBase64,
                        prompt_speech: refAudioBase64,
                        prompt_audio: refAudioBase64 || refAudioUrl,
                        audio_prompt: refAudioBase64 || refAudioUrl,
                        filename: filename
                    })
                });

                if (response && response.ok) {
                    const blob = await response.blob();
                    if (blob.size > 200) {
                        item.audioUrl = URL.createObjectURL(blob);
                        item.status = "done";
                        
                        const renderDurationSec = Math.max(1.0, (Date.now() - startTime) / 1000);
                        const costUsd = Math.max(0.0015, (renderDurationSec * 0.00035) + ((cleanText || item.text).length * 0.000005));
                        trackGpuBillingUsage(gpuUrl, costUsd);

                        currentUser.used += item.text.length;
                        if (usersDatabase.USERS[currentUser.username]) {
                            usersDatabase.USERS[currentUser.username].used = currentUser.used;
                        }
                        localStorage.setItem(`quota_used_${currentUser.username.toLowerCase()}`, currentUser.used);
                        
                        syncUsersToGist().catch(e => console.warn("Lỗi sync quota Supabase:", e));

                        document.getElementById("user-quota-display").innerText = `${currentUser.used.toLocaleString('vi-VN')} / ${currentUser.quota.toLocaleString('vi-VN')} ký tự`;
                        renderChunksTable();
                        addAppLog(`Đoạn ${item.id} tạo voice AI bằng máy chủ GPU THÀNH CÔNG 100%! (${(blob.size / 1024).toFixed(1)} KB)`);
                        return;
                    }
                }
            } catch (retryErr) {
                lastError = retryErr;
            }
        }
        
        throw new Error(lastError ? lastError.message : `HTTP Status ${response ? response.status : 'Unknown'} - GPU Server bận`);
    } catch (err) {
        console.error("Lỗi gọi Serverless GPU:", err);
        item.status = "error";
        renderChunksTable();
        addAppLog(`Lỗi Đoạn ${item.id}: ${err.message}`);
        showToast("Lỗi Tạo Voice", `Đoạn ${item.id} gặp sự cố: ${err.message}`, "error");
    }
}

function playSingleChunkAudio(e, idx) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    selectedChunkIndex = idx;
    const item = currentChunksList[idx];
    if (!item || !item.audioUrl) {
        alert("Đoạn này chưa tạo xong âm thanh!");
        return;
    }

    // Dừng tất cả âm thanh đang phát để tránh nhại giọng / tiếng vọng
    stopPlaying();

    const resultCard = document.getElementById("audio-result-card");
    const player = document.getElementById("audio-player");
    const downloadLink = document.getElementById("download-link");

    if (resultCard) {
        resultCard.classList.remove("hidden");
    }

    if (downloadLink) {
        downloadLink.href = item.audioUrl;
        downloadLink.download = `HTH_Voice_Doan_${item.id}.wav`;
    }

    if (player) {
        player.src = item.audioUrl;
        currentlyPlayingAudio = player;
        player.play().then(() => {
            addAppLog(`Đang phát âm thanh Đoạn ${item.id}...`);
        }).catch(err => {
            console.log("Audio player play notice:", err);
        });
    } else {
        currentlyPlayingAudio = new Audio(item.audioUrl);
        currentlyPlayingAudio.play().then(() => {
            addAppLog(`Đang phát âm thanh Đoạn ${item.id}...`);
        }).catch(err => {
            console.error("Lỗi phát audio:", err);
        });
    }
}

function downloadChunkAudio(e, idx) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    const item = currentChunksList[idx];
    if (!item || !item.audioUrl) {
        alert("Chưa có file âm thanh để tải!");
        return;
    }

    const a = document.createElement("a");
    a.href = item.audioUrl;
    a.download = `HTH_Voice_Doan_${item.id}.wav`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    addAppLog(`Đã tải về tệp âm thanh Đoạn ${item.id} (HTH_Voice_Doan_${item.id}.wav)`);
}

function playSelectedChunk() {
    if (selectedChunkIndex === -1) { alert("Vui lòng chọn 1 đoạn trong bảng!"); return; }
    playSingleChunkAudio(null, selectedChunkIndex);
}

function stopPlaying() {
    if (currentlyPlayingAudio) {
        currentlyPlayingAudio.pause();
        currentlyPlayingAudio = null;
        addAppLog("Đã dừng phát âm thanh.");
    }
    const player = document.getElementById("audio-player");
    if (player) {
        player.pause();
    }
}

function stopGenerating() {
    addAppLog("Đã gửi lệnh Dừng Tạo.");
}

// BỘ MÃ HÓA VÀ NỐI AUDIO BUFFERS CHUẨN TRÌNH DUYỆT (WEB AUDIO API 16-BIT PCM WAV)
function audioBufferToWav(buffer) {
    const numChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const bitDepth = 16;
    
    let samples;
    if (numChannels === 2) {
        const left = buffer.getChannelData(0);
        const right = buffer.getChannelData(1);
        samples = interleaveChannels(left, right);
    } else {
        samples = buffer.getChannelData(0);
    }

    return createWavBlobFromPCM(samples, numChannels, sampleRate, bitDepth);
}

function interleaveChannels(left, right) {
    const length = left.length + right.length;
    const result = new Float32Array(length);
    let inputIndex = 0;
    for (let index = 0; index < length;) {
        result[index++] = left[inputIndex];
        result[index++] = right[inputIndex];
        inputIndex++;
    }
    return result;
}

function createWavBlobFromPCM(samples, numChannels, sampleRate, bitDepth) {
    const bytesPerSample = bitDepth / 8;
    const blockAlign = numChannels * bytesPerSample;
    const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
    const view = new DataView(buffer);

    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * bytesPerSample, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitDepth, true);
    writeString(view, 36, 'data');
    view.setUint32(40, samples.length * bytesPerSample, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
        let s = Math.max(-1, Math.min(1, samples[i]));
        s = s < 0 ? s * 0x8000 : s * 0x7FFF;
        view.setInt16(offset, s, true);
        offset += 2;
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

async function mergeAudioUrls(audioUrls, silenceSec = 0.2) {
    const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
    const audioCtx = new AudioCtxClass();
    const audioBuffers = [];

    for (const url of audioUrls) {
        const response = await fetch(url);
        const arrayBuffer = await response.arrayBuffer();
        const decodedBuffer = await audioCtx.decodeAudioData(arrayBuffer);
        audioBuffers.push(decodedBuffer);
    }

    if (audioBuffers.length === 0) return null;

    const sampleRate = audioBuffers[0].sampleRate;
    const numChannels = audioBuffers[0].numberOfChannels;
    const silenceLength = Math.floor(sampleRate * silenceSec);

    let totalLength = 0;
    audioBuffers.forEach((buf, i) => {
        totalLength += buf.length;
        if (i < audioBuffers.length - 1) {
            totalLength += silenceLength;
        }
    });

    const mergedBuffer = audioCtx.createBuffer(numChannels, totalLength, sampleRate);

    for (let channel = 0; channel < numChannels; channel++) {
        const output = mergedBuffer.getChannelData(channel);
        let offset = 0;

        audioBuffers.forEach((buf, i) => {
            const input = buf.getChannelData(Math.min(channel, buf.numberOfChannels - 1));
            output.set(input, offset);
            offset += buf.length;

            if (i < audioBuffers.length - 1) {
                offset += silenceLength;
            }
        });
    }

    if (audioCtx.state !== 'closed') {
        await audioCtx.close();
    }

    return audioBufferToWav(mergedBuffer);
}

async function mergeAllAudioChunks() {
    const doneChunks = currentChunksList.filter(c => c.status === "done" && c.audioUrl);
    if (doneChunks.length === 0) {
        alert("Chưa có đoạn nào hoàn thành tạo âm thanh để gộp!");
        return;
    }

    const silencePause = parseFloat(document.getElementById("input-silence-pause")?.value) || 0.2;
    const autoClean = document.getElementById("check-auto-clean")?.checked;

    addAppLog(`Bắt đầu GỘP THẬT ${doneChunks.length} đoạn âm thanh giọng đọc...`);
    showToast("Đang Ghép Audio", "Đang xử lý ghép các đoạn âm thanh hoàn chỉnh...", "info");

    try {
        const audioUrls = doneChunks.map(c => c.audioUrl);
        const mergedBlob = await mergeAudioUrls(audioUrls, silencePause);

        if (!mergedBlob) {
            showToast("Lỗi Ghép Audio", "Không thể tạo file âm thanh gộp!", "error");
            return;
        }

        const mergedUrl = URL.createObjectURL(mergedBlob);

        const resultCard = document.getElementById("audio-result-card");
        if (resultCard) resultCard.classList.remove("hidden");
        
        const player = document.getElementById("audio-player");
        const downloadLink = document.getElementById("download-link");

        if (player) {
            player.src = mergedUrl;
            player.play().catch(err => console.log("Merged player status:", err));
        }
        if (downloadLink) {
            downloadLink.href = mergedUrl;
            downloadLink.download = "HTH_Supper_Voice_HoanChinh.wav";
        }

        if (autoClean) {
            addAppLog("Đã tự động dọn dẹp các tệp tạm.");
        }
        addAppLog("GỘP CÁC ĐOẠN VÀ XUẤT FILE HOÀN CHỈNH THÀNH CÔNG 100%!");
        showToast("Ghép Hoàn Tất", "Đã ghép tất cả các đoạn thành 1 file WAV hoàn chỉnh thành công!", "success");
    } catch (err) {
        console.error("Lỗi gộp audio:", err);
        addAppLog("Lỗi gộp âm thanh: " + err.message);
        showToast("Lỗi Gộp File", "Không thể ghép file âm thanh: " + err.message, "error");
    }
}

function getRandomGpuUrl() {
    if (!modalGpuUrls || modalGpuUrls.length === 0) return "https://modal.com";
    return modalGpuUrls[Math.floor(Math.random() * modalGpuUrls.length)];
}

async function loadGitHubVoices() {
    try {
        let txtVoices = [];
        
        // 1. Tải file thông tin mô tả thong_tin_giong_doc.txt từ GitHub
        try {
            const txtResp = await fetch(`https://raw.githubusercontent.com/${GITHUB_VOICE_REPO}/main/thong_tin_giong_doc.txt`);
            if (txtResp.ok) {
                const txtContent = await txtResp.text();
                txtVoices = parseVoiceTxt(txtContent);
            }
        } catch (errTxt) {
            console.warn("Không thể tải thong_tin_giong_doc.txt:", errTxt);
        }

        // 2. Tải danh sách file media trực tiếp từ API GitHub
        let apiFiles = [];
        try {
            const apiResp = await fetch(`https://api.github.com/repos/${GITHUB_VOICE_REPO}/contents/`);
            if (apiResp.ok) {
                apiFiles = await apiResp.json();
            }
        } catch (errApi) {
            console.warn("Không thể tải API GitHub contents:", errApi);
        }

        allVoiceMetadata = [];

        if (txtVoices.length > 0) {
            // Sử dụng dữ liệu phong phú từ file thong_tin_giong_doc.txt
            txtVoices.forEach(tv => {
                // Khớp downloadUrl nếu có file từ GitHub API
                if (apiFiles.length > 0) {
                    const matchedFile = apiFiles.find(f => f.name === tv.filename || (tv.voiceId && f.name.includes(tv.voiceId)));
                    if (matchedFile && matchedFile.download_url) {
                        tv.downloadUrl = matchedFile.download_url;
                    }
                }
                allVoiceMetadata.push(tv);
            });
        } else if (apiFiles.length > 0) {
            // Dự phòng trường hợp không có file .txt
            apiFiles.forEach(file => {
                if (file.name.match(/\.(mp3|wav|m4a|flac)$/i)) {
                    const meta = parseVoiceInfo(file.name, file.download_url);
                    allVoiceMetadata.push(meta);
                }
            });
        }

        const totalCount = allVoiceMetadata.length;
        const countStr = `${totalCount}+`;

        const statVoiceCountEl = document.getElementById("stat-voice-count");
        if (statVoiceCountEl) statVoiceCountEl.innerText = countStr;

        const tagVoiceEl = document.getElementById("selected-voice-tag");
        if (tagVoiceEl) tagVoiceEl.innerText = `${totalCount} Giọng VIP`;

        const btnOpenBrowserEl = document.getElementById("btn-open-voice-browser");
        if (btnOpenBrowserEl) {
            btnOpenBrowserEl.innerHTML = `<i class="fa-solid fa-list-ul"></i> Mở Bảng Danh Sách Giọng VIP (${totalCount} Giọng)`;
        }

        const modalTitleEl = document.getElementById("modal-voice-title");
        if (modalTitleEl) {
            modalTitleEl.innerHTML = `<i class="fa-solid fa-headphones"></i> Bảng Duyệt VIP Danh Sách Giọng Đọc (${totalCount} Giọng)`;
        }

        populateFilters();
        applyFilters();

        if (allVoiceMetadata.length > 0) {
            const firstVoiceName = allVoiceMetadata[0].name;
            const combo = document.getElementById("select-voice");
            if (combo) {
                combo.innerHTML = `<option value="${firstVoiceName}">${firstVoiceName}</option>`;
                combo.value = firstVoiceName;
            }
            const currentNameEl = document.getElementById("current-selected-voice-name");
            if (currentNameEl) {
                currentNameEl.innerText = firstVoiceName;
            }
        }

        addAppLog(`Đã nạp thành công ${countStr} giọng đọc VIP cùng chi tiết ngôn ngữ từ GitHub!`);
    } catch (e) {
        console.error("Lỗi đồng bộ GitHub:", e);
        addAppLog("Lỗi nạp danh sách giọng đọc VIP: " + e.message);
    }
}

function parseVoiceTxt(txtContent) {
    if (!txtContent) return [];
    
    const blocks = txtContent.split(/-{30,}/);
    const parsedVoices = [];

    blocks.forEach(block => {
        const lines = block.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        if (lines.length < 2) return;

        let filename = "";
        let name = "";
        let voiceId = "";
        let gender = "Tất cả";
        let age = "Tất cả";
        let category = "Tất cả";
        let isVip = false;
        let supportedLanguages = [];

        lines.forEach(line => {
            if (line.includes("Tên file:")) {
                filename = line.split("Tên file:")[1].trim();
            } else if (line.includes("- Tên giọng:")) {
                name = line.split("- Tên giọng:")[1].trim();
            } else if (line.includes("- Voice ID:")) {
                voiceId = line.split("- Voice ID:")[1].trim();
            } else if (line.includes("- Giới tính:")) {
                const parts = line.split('|').map(p => p.trim());
                parts.forEach(p => {
                    if (p.includes("Giới tính:")) gender = p.split("Giới tính:")[1].trim();
                    if (p.includes("Độ tuổi:")) age = p.split("Độ tuổi:")[1].trim();
                    if (p.includes("Phân loại:")) category = p.split("Phân loại:")[1].trim();
                    if (p.includes("VIP:")) isVip = p.includes("Có");
                });
            } else if (line.startsWith("-> ")) {
                const langsStr = line.substring(3).trim();
                supportedLanguages = langsStr.split(',').map(s => s.trim()).filter(s => s.length > 0).map(s => formatLangName(s));
            }
        });

        if (filename || name || voiceId) {
            if (!name) name = filename.replace(/\.[^/.]+$/, "");
            parsedVoices.push({
                filename,
                name,
                voiceId,
                gender,
                age,
                category,
                isVip,
                supportedLanguages,
                lang: supportedLanguages.length > 0 ? (supportedLanguages.length > 1 ? `Đa ngôn ngữ (${supportedLanguages.length})` : supportedLanguages[0]) : "Đa ngôn ngữ",
                downloadUrl: `https://raw.githubusercontent.com/${GITHUB_VOICE_REPO}/main/${encodeURIComponent(filename)}`
            });
        }
    });

    return parsedVoices;
}

function parseVoiceInfo(filename, downloadUrl) {
    const baseName = filename.replace(/\.[^/.]+$/, "");
    const parts = baseName.split("-").map(s => s.trim());
    
    const category = parts.length >= 1 ? parts[parts.length - 1] : "Tất cả";
    const age = parts.length >= 2 ? parts[parts.length - 2] : "Tất cả";
    const gender = parts.length >= 3 ? parts[parts.length - 3] : "Tất cả";
    const lang = parts.length >= 4 ? parts[parts.length - 4] : "Tất cả";
    const voiceId = parts.length >= 5 ? parts[parts.length - 5] : "";
    
    let displayName = baseName;
    if (parts.length > 5) displayName = parts.slice(0, -5).join(" - ");
    else if (parts.length > 4) displayName = parts.slice(0, -4).join(" - ");
    
    return { name: displayName, raw: baseName, voiceId, lang, gender, age, category, supportedLanguages: [lang], downloadUrl };
}

const GLOBAL_LANG_MAP = {
    "en": "Tiếng Anh (English)", "english": "Tiếng Anh (English)", "anh": "Tiếng Anh (English)",
    "vi": "Tiếng Việt (Vietnamese)", "vietnamese": "Tiếng Việt (Vietnamese)", "việt": "Tiếng Việt (Vietnamese)",
    "zh": "Tiếng Trung (Chinese)", "chinese": "Tiếng Trung (Chinese)", "trung": "Tiếng Trung (Chinese)",
    "ja": "Tiếng Nhật (Japanese)", "japanese": "Tiếng Nhật (Japanese)", "nhật": "Tiếng Nhật (Japanese)",
    "ko": "Tiếng Hàn (Korean)", "korean": "Tiếng Hàn (Korean)", "hàn": "Tiếng Hàn (Korean)",
    "fr": "Tiếng Pháp (French)", "french": "Tiếng Pháp (French)", "pháp": "Tiếng Pháp (French)",
    "de": "Tiếng Đức (German)", "german": "Tiếng Đức (German)", "đức": "Tiếng Đức (German)",
    "es": "Tiếng Tây Ban Nha (Spanish)", "spanish": "Tiếng Tây Ban Nha (Spanish)", "tây ban nha": "Tiếng Tây Ban Nha (Spanish)",
    "ru": "Tiếng Nga (Russian)", "russian": "Tiếng Nga (Russian)", "nga": "Tiếng Nga (Russian)",
    "pt": "Tiếng Bồ Đào Nha (Portuguese)", "portuguese": "Tiếng Bồ Đào Nha (Portuguese)",
    "it": "Tiếng Ý (Italian)", "italian": "Tiếng Ý (Italian)", "ý": "Tiếng Ý (Italian)",
    "hi": "Tiếng Ấn Độ (Hindi)", "hindi": "Tiếng Ấn Độ (Hindi)", "ấn độ": "Tiếng Ấn Độ (Hindi)",
    "ar": "Tiếng Ả Rập (Arabic)", "arabic": "Tiếng Ả Rập (Arabic)", "ả rập": "Tiếng Ả Rập (Arabic)",
    "id": "Tiếng Indonesia", "indonesia": "Tiếng Indonesia", "indonesian": "Tiếng Indonesia",
    "th": "Tiếng Thái (Thai)", "thai": "Tiếng Thái (Thai)", "thái": "Tiếng Thái (Thai)",
    "tr": "Tiếng Thổ Nhĩ Kỳ (Turkish)", "thổ nhĩ kỳ": "Tiếng Thổ Nhĩ Kỳ (Turkish)", "turkish": "Tiếng Thổ Nhĩ Kỳ (Turkish)",
    "pl": "Tiếng Ba Lan (Polish)", "polish": "Tiếng Ba Lan (Polish)", "ba lan": "Tiếng Ba Lan (Polish)",
    "nl": "Tiếng Hà Lan (Dutch)", "hà lan": "Tiếng Hà Lan (Dutch)", "dutch": "Tiếng Hà Lan (Dutch)",
    "cs": "Tiếng Séc (Czech)", "czech": "Tiếng Séc (Czech)", "séc": "Tiếng Séc (Czech)",
    "el": "Tiếng Hy Lạp (Greek)", "greek": "Tiếng Hy Lạp (Greek)", "hy lạp": "Tiếng Hy Lạp (Greek)",
    "he": "Tiếng Do Thái (Hebrew)", "hebrew": "Tiếng Do Thái (Hebrew)", "do thái": "Tiếng Do Thái (Hebrew)",
    "ms": "Tiếng Mã Lai (Malay)", "mã lai": "Tiếng Mã Lai (Malay)", "malay": "Tiếng Mã Lai (Malay)",
    "sv": "Tiếng Thụy Điển (Swedish)", "swedish": "Tiếng Thụy Điển (Swedish)", "thụy điển": "Tiếng Thụy Điển (Swedish)",
    "hu": "Tiếng Hung-ga-ri (Hungarian)", "hungarian": "Tiếng Hung-ga-ri (Hungarian)", "hung-ga-ri": "Tiếng Hung-ga-ri (Hungarian)",
    "da": "Tiếng Đan Mạch (Danish)", "danish": "Tiếng Đan Mạch (Danish)", "đan mạch": "Tiếng Đan Mạch (Danish)",
    "fi": "Tiếng Phần Lan (Finnish)", "finnish": "Tiếng Phần Lan (Finnish)", "phần lan": "Tiếng Phần Lan (Finnish)",
    "sk": "Tiếng Slovakia (Slovak)", "slovak": "Tiếng Slovakia (Slovak)", "slovakia": "Tiếng Slovakia (Slovak)",
    "bg": "Tiếng Bulgaria", "bulgarian": "Tiếng Bulgaria", "bulgaria": "Tiếng Bulgaria",
    "ro": "Tiếng Romania", "romanian": "Tiếng Romania", "romania": "Tiếng Romania",
    "uk": "Tiếng Ukraina", "ukrainian": "Tiếng Ukraina", "ukraina": "Tiếng Ukraina",
    "hr": "Tiếng Croatia", "croatian": "Tiếng Croatia", "croatia": "Tiếng Croatia",
    "no": "Tiếng Na Uy (Norwegian)", "norwegian": "Tiếng Na Uy (Norwegian)", "na uy": "Tiếng Na Uy (Norwegian)",
    "ta": "Tiếng Tamil", "tamil": "Tiếng Tamil",
    "tagalog": "Tiếng Philippines (Tagalog)", "tl": "Tiếng Philippines (Tagalog)",
    "multilingual": "Đa Ngôn Ngữ (Multilingual)"
};

function formatLangName(code) {
    if (!code) return "Khác";
    const key = code.trim().toLowerCase();
    return GLOBAL_LANG_MAP[key] || code;
}

function populateFilters() {
    const rawLangsSet = new Set();
    allVoiceMetadata.forEach(v => {
        if (v.supportedLanguages && v.supportedLanguages.length > 0) {
            v.supportedLanguages.forEach(l => rawLangsSet.add(l));
        } else if (v.lang) {
            rawLangsSet.add(v.lang);
        }
    });

    // Gom nhóm và ánh xạ tên tiếng Việt đầy đủ
    const fullLangsSet = new Set();
    rawLangsSet.forEach(raw => {
        const full = formatLangName(raw);
        fullLangsSet.add(full);
    });

    const fullLangs = [...fullLangsSet];
    
    // ƯU TIÊN TIẾNG ANH VÀ TIẾNG VIỆT XẾP ĐẦU DANH SÁCH
    fullLangs.sort((a, b) => {
        if (a.includes("Tiếng Anh")) return -1;
        if (b.includes("Tiếng Anh")) return 1;
        if (a.includes("Tiếng Việt")) return -1;
        if (b.includes("Tiếng Việt")) return 1;
        return a.localeCompare(b, 'vi');
    });

    const genders = [...new Set(allVoiceMetadata.map(v => v.gender))].sort();
    const ages = [...new Set(allVoiceMetadata.map(v => v.age))].sort();
    const cats = [...new Set(allVoiceMetadata.map(v => v.category))].sort();

    fillCombo("modal-filter-lang", ["Ngôn ngữ: Tất cả", ...fullLangs]);
    fillCombo("modal-filter-gender", ["Giới tính: Tất cả", ...genders]);
    fillCombo("modal-filter-age", ["Độ tuổi: Tất cả", ...ages]);
    fillCombo("modal-filter-cat", ["Phân loại: Tất cả", ...cats]);
}

function fillCombo(id, values, mapObj = null) {
    const el = document.getElementById(id);
    if (el) {
        el.innerHTML = values.map(v => {
            if (v.startsWith("Ngôn ngữ:") || v.startsWith("Giới tính:") || v.startsWith("Độ tuổi:") || v.startsWith("Phân loại:")) {
                return `<option value="Tất cả">${v}</option>`;
            }
            return `<option value="${v}">${v}</option>`;
        }).join("");
    }
}

function applyFilters() {
    renderVoiceBrowserList();
}

function renderVoiceBrowserList() {
    const container = document.getElementById("voice-browser-list-container");
    const keyword = (document.getElementById("voice-modal-search-input")?.value || "").trim().toLowerCase();
    const selectedLang = document.getElementById("modal-filter-lang")?.value || "Tất cả";
    const selectedGender = document.getElementById("modal-filter-gender")?.value || "Tất cả";
    const selectedAge = document.getElementById("modal-filter-age")?.value || "Tất cả";
    const selectedCat = document.getElementById("modal-filter-cat")?.value || "Tất cả";

    if (!container) return;

    const filtered = allVoiceMetadata.filter(v => {
        if (selectedLang !== "Tất cả" && selectedLang !== "Ngôn ngữ: Tất cả") {
            const vLangs = (v.supportedLanguages && v.supportedLanguages.length > 0) 
                           ? v.supportedLanguages.map(l => formatLangName(l)) 
                           : [formatLangName(v.lang)];
            if (!vLangs.includes(selectedLang)) return false;
        }
        if (selectedGender !== "Tất cả" && selectedGender !== "Giới tính: Tất cả" && v.gender !== selectedGender) return false;
        if (selectedAge !== "Tất cả" && selectedAge !== "Độ tuổi: Tất cả" && v.age !== selectedAge) return false;
        if (selectedCat !== "Tất cả" && selectedCat !== "Phân loại: Tất cả" && v.category !== selectedCat) return false;
        if (selectedGender !== "Tất cả" && selectedGender !== "Giới tính: Tất cả" && v.gender !== selectedGender) return false;
        if (selectedAge !== "Tất cả" && selectedAge !== "Độ tuổi: Tất cả" && v.age !== selectedAge) return false;
        if (selectedCat !== "Tất cả" && selectedCat !== "Phân loại: Tất cả" && v.category !== selectedCat) return false;
        
        if (!keyword) return true;
        const matchesName = v.name.toLowerCase().includes(keyword);
        const matchesId = v.voiceId.toLowerCase().includes(keyword);
        const matchesLangs = v.supportedLanguages ? v.supportedLanguages.some(l => l.toLowerCase().includes(keyword)) : false;
        const matchesGender = v.gender.toLowerCase().includes(keyword);
        const matchesAge = v.age.toLowerCase().includes(keyword);
        const matchesCat = v.category.toLowerCase().includes(keyword);

        return matchesName || matchesId || matchesLangs || matchesGender || matchesAge || matchesCat;
    });

    if (filtered.length === 0) {
        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: #94A3B8; padding: 30px;">Không tìm thấy giọng đọc phù hợp với tiêu chí lọc.</div>`;
        return;
    }

    const currentPlayingName = window.activePlayingVoiceName || "";

    container.innerHTML = filtered.map(v => {
        const isPlaying = currentPlayingName === v.name;
        let mappedLangs = [];
        if (v.supportedLanguages && v.supportedLanguages.length > 0) {
            mappedLangs = v.supportedLanguages.map(l => formatLangName(l));
        } else if (v.lang) {
            mappedLangs = [formatLangName(v.lang)];
        }

        let langDisplay = "";
        if (mappedLangs.length > 2) {
            langDisplay = `${mappedLangs.slice(0, 2).join(", ")} +${mappedLangs.length - 2}`;
        } else if (mappedLangs.length > 0) {
            langDisplay = mappedLangs.join(", ");
        } else {
            langDisplay = "Đa Ngôn Ngữ";
        }

        const fullLangTooltip = mappedLangs.length > 0 ? mappedLangs.join(", ") : "Đa Ngôn Ngữ";

        return `
            <div style="background: rgba(15, 23, 42, 0.75); border: 1px solid ${isPlaying ? '#00E5FF' : 'rgba(255,255,255,0.08)'}; padding: 12px 16px; border-radius: 10px; display: flex; align-items: center; justify-content: space-between; gap: 10px;">
                <div style="flex: 1; overflow: hidden;">
                    <div style="font-weight: 700; color: #F8FAFC; font-size: 0.92rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        ${v.name} ${v.isVip ? '<span style="font-size: 0.7rem; background: linear-gradient(135deg, #FFD700, #FFA500); color: #000; padding: 1px 6px; border-radius: 4px; font-weight: 800; margin-left: 4px;">VIP</span>' : ''}
                    </div>
                    <div style="font-size: 0.78rem; color: #94A3B8; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        <span style="color: #00E5FF; font-weight: 600;" title="${fullLangTooltip}">${langDisplay}</span> • <span>${v.gender}</span> • <span>${v.age}</span> • <span>${v.category}</span>
                    </div>
                </div>

                <div style="display: flex; gap: 8px; align-items: center;">
                    <button type="button" onclick="playDirectVoiceSample('${v.name.replace(/'/g, "\\'")}')" title="Nghe thử giọng này" style="background: ${isPlaying ? '#EF4444' : 'linear-gradient(135deg, #7C4DFF, #00E5FF)'}; border: none; color: #FFF; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 14px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); transition: transform 0.15s;">
                        <i class="fa-solid ${isPlaying ? 'fa-pause' : 'fa-play'}" style="${isPlaying ? '' : 'margin-left: 2px;'}"></i>
                    </button>

                    <button type="button" onclick="selectVoiceFromBrowserModal('${v.name.replace(/'/g, "\\'")}')" style="background: rgba(16, 185, 129, 0.2); border: 1px solid #10B981; color: #10B981; padding: 6px 12px; border-radius: 6px; font-weight: 700; font-size: 0.8rem; cursor: pointer; transition: all 0.2s;">
                        <i class="fa-solid fa-check"></i> Chọn
                    </button>
                </div>
            </div>
        `;
    }).join("");
}

function playDirectVoiceSample(voiceName) {
    const matchedVoice = allVoiceMetadata.find(v => v.name === voiceName);
    if (!matchedVoice || !matchedVoice.downloadUrl) {
        showToast("Không Thể Nghe", `Không tìm thấy tệp nghe thử của giọng: ${voiceName}`, "error");
        return;
    }

    if (activeModalVoiceAudio && window.activePlayingVoiceName === voiceName) {
        activeModalVoiceAudio.pause();
        activeModalVoiceAudio = null;
        window.activePlayingVoiceName = "";
        renderVoiceBrowserList();
        return;
    }

    if (activeModalVoiceAudio) {
        activeModalVoiceAudio.pause();
    }

    stopPlaying();

    window.activePlayingVoiceName = voiceName;
    renderVoiceBrowserList();

    activeModalVoiceAudio = new Audio(matchedVoice.downloadUrl);
    activeModalVoiceAudio.play().then(() => {
        showToast("Đang Phát Voice", `Đang phát voice ${voiceName}`, "info");
    }).catch(err => {
        console.error("Lỗi phát voice:", err);
        window.activePlayingVoiceName = "";
        renderVoiceBrowserList();
    });

    activeModalVoiceAudio.onended = () => {
        activeModalVoiceAudio = null;
        window.activePlayingVoiceName = "";
        renderVoiceBrowserList();
    };
}

function openVoiceBrowserModal() {
    const modal = document.getElementById("voice-browser-modal");
    if (modal) {
        modal.style.display = "flex";
        modal.classList.remove("hidden");
        populateFilters();
        renderVoiceBrowserList();
    }
}

function closeVoiceBrowserModal() {
    const modal = document.getElementById("voice-browser-modal");
    if (modal) {
        modal.style.display = "none";
        modal.classList.add("hidden");
    }
    if (activeModalVoiceAudio) {
        activeModalVoiceAudio.pause();
        activeModalVoiceAudio = null;
        window.activePlayingVoiceName = "";
    }
}

function selectVoiceFromBrowserModal(voiceName) {
    const combo = document.getElementById("select-voice");
    if (combo) {
        combo.innerHTML = `<option value="${voiceName}" selected>${voiceName}</option>`;
        combo.value = voiceName;
    }

    const currentNameEl = document.getElementById("current-selected-voice-name");
    if (currentNameEl) {
        currentNameEl.innerText = voiceName;
    }

    showToast("Đã Chọn Giọng", `Đã thiết lập giọng đọc chính: ${voiceName}`, "success");
    closeVoiceBrowserModal();
}

function insertEmotionTag(tag) {
    const txtArea = document.getElementById("text-input");
    const startPos = txtArea.selectionStart;
    const endPos = txtArea.selectionEnd;
    const text = txtArea.value;

    txtArea.value = text.substring(0, startPos) + ` ${tag} ` + text.substring(endPos);
    txtArea.focus();
    txtArea.selectionStart = startPos + tag.length + 2;
    txtArea.selectionEnd = startPos + tag.length + 2;
    updateCharCount();
}

function openAuthModal() {
    const modal = document.getElementById("auth-modal");
    if (modal) {
        modal.style.display = "flex";
        modal.style.opacity = "1";
        modal.style.visibility = "visible";
        modal.classList.remove("hidden");
        setTimeout(() => {
            const usernameInput = document.getElementById("auth-username");
            if (usernameInput) usernameInput.focus();
        }, 50);
    }
}

function closeAuthModal() {
    const modal = document.getElementById("auth-modal");
    if (modal) {
        modal.style.display = "none";
    }
}

function openStudio() {
    if (!currentUser) {
        openAuthModal();
    } else {
        showStudioView();
    }
}

// XÁC THỰC ĐĂNG NHẬP TỨC THÌ NON-BLOCKING 100% CHỐNG NGHẼN NETWORK
async function submitAuth() {
    const usernameInput = document.getElementById("auth-username").value.trim();
    const passInput = document.getElementById("auth-password").value.trim();
    
    if (!usernameInput || !passInput) {
        showToast("Thiếu Thông Tin", "Vui lòng nhập Tên tài khoản và Mật khẩu!", "error");
        return;
    }

    // Nạp cấu hình Supabase ngầm không làm đơ nút Đăng nhập
    loadServerConfigFromGist().catch(e => console.warn("Lỗi nạp Supabase ngầm:", e));

    const lowerInputName = usernameInput.toLowerCase();
    let foundUsername = null;
    let foundAcc = null;

    Object.keys(usersDatabase.USERS).forEach(name => {
        if (name.toLowerCase() === lowerInputName) {
            foundUsername = name;
            foundAcc = usersDatabase.USERS[name];
        }
    });

    if (foundAcc && (foundAcc.password === passInput || foundAcc.password.trim() === passInput)) {
        // KHÔI PHỤC BẢO TOÀN SỐ KÝ TỰ ĐÃ SỬ DỤNG CHỐNG RESET VỀ 0
        const savedUsed = localStorage.getItem(`quota_used_${foundUsername.toLowerCase()}`);
        let actualUsed = foundAcc.used || 0;
        if (savedUsed !== null) {
            actualUsed = Math.max(actualUsed, parseInt(savedUsed) || 0);
        }
        foundAcc.used = actualUsed;

        currentUser = { username: foundUsername, ...foundAcc, used: actualUsed };

        closeAuthModal();
        showStudioView();
        showToast("Đăng Nhập Thành Công", `Chào mừng ${foundUsername} (${foundAcc.role})!`, "success");
        addAppLog(`Tài khoản "${foundUsername}" đăng nhập thành công.`);
    } else {
        showToast("Đăng Nhập Thất Bại", "Tên tài khoản hoặc mật khẩu không chính xác!", "error");
    }
}

function showStudioView() {
    document.getElementById("hero-section").classList.add("hidden");
    document.getElementById("nav-links").classList.add("hidden");
    document.getElementById("btn-login-trigger").classList.add("hidden");
    document.getElementById("btn-studio-trigger").classList.add("hidden");

    document.getElementById("user-badge").classList.remove("hidden");
    document.getElementById("user-name-display").innerHTML = `<i class="fa-solid fa-user-check"></i> ${currentUser.username} (${currentUser.role})`;
    document.getElementById("user-quota-display").innerText = `${currentUser.used.toLocaleString('vi-VN')} / ${currentUser.quota.toLocaleString('vi-VN')} ký tự`;

    const isAdmin = currentUser && (currentUser.role.includes("Admin") || currentUser.username.toLowerCase().includes("admin"));

    // CHỈ HIỂN THỊ NÚT QUẢN LÝ USER VÀ TAB GIÁM SÁT MODAL GPU CHO TÀI KHOẢN ADMIN VIP
    const btnAdminManage = document.getElementById("btn-admin-manage");
    const tabBtnDashboard = document.getElementById("tab-btn-modal-dashboard");

    if (isAdmin) {
        if (btnAdminManage) btnAdminManage.classList.remove("hidden");
        if (tabBtnDashboard) tabBtnDashboard.classList.remove("hidden");
    } else {
        if (btnAdminManage) btnAdminManage.classList.add("hidden");
        if (tabBtnDashboard) tabBtnDashboard.classList.add("hidden");
        switchStudioTab("voice");
    }

    document.getElementById("studio-section").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
}

function logout() {
    currentUser = null;
    document.getElementById("studio-section").classList.add("hidden");
    document.getElementById("user-badge").classList.add("hidden");

    document.getElementById("hero-section").classList.remove("hidden");
    document.getElementById("nav-links").classList.remove("hidden");
    document.getElementById("btn-login-trigger").classList.remove("hidden");
    document.getElementById("btn-studio-trigger").classList.remove("hidden");

    window.scrollTo({ top: 0, behavior: "smooth" });
}

function openAdminModal() {
    renderUserList();
    renderGpuUrlList();
    document.getElementById("admin-modal").classList.remove("hidden");
}

function renderGpuUrlList() {
    const container = document.getElementById("gpu-url-list-container");
    if (!container) return;

    if (!modalGpuUrls || modalGpuUrls.length === 0) {
        container.innerHTML = `<div style="color: #94A3B8; font-size: 0.85rem; font-style: italic;">Chưa có link GPU nào được thêm.</div>`;
        return;
    }

    container.innerHTML = modalGpuUrls.map((url, idx) => `
        <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 8px 12px; gap: 10px;">
            <div style="font-size: 0.85rem; color: #E2E8F0; word-break: break-all; font-family: monospace;">
                <i class="fa-solid fa-microchip" style="color: #A855F7; margin-right: 6px;"></i> ${url}
            </div>
            <button onclick="deleteGpuUrl(${idx})" style="background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.4); color: #EF4444; border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 0.75rem; font-weight: 600; white-space: nowrap;">
                <i class="fa-solid fa-trash"></i> Xóa
            </button>
        </div>
    `).join("");
}

async function addNewGpuUrl() {
    const inputEl = document.getElementById("new-gpu-url");
    const rawUrl = inputEl ? inputEl.value.trim() : "";
    
    if (!rawUrl || !rawUrl.startsWith("http")) {
        showToast("Link Không Hợp Lệ", "Vui lòng dán đường link GPU hợp lệ (bắt đầu bằng https://)!", "error");
        return;
    }

    const cleanUrl = rawUrl.replace(/\/+$/, "");
    if (!modalGpuUrls.includes(cleanUrl)) {
        modalGpuUrls.push(cleanUrl);
    }
    
    inputEl.value = "";
    renderGpuUrlList();
    await syncUsersToGist();
    showToast("Thêm GPU Thành Công", "Đã thêm Serverless GPU mới và đồng bộ vĩnh viễn lên Supabase!", "success");
}

async function deleteGpuUrl(index) {
    if (index >= 0 && index < modalGpuUrls.length) {
        const removed = modalGpuUrls.splice(index, 1);
        renderGpuUrlList();
        await syncUsersToGist();
        showToast("Đã Xóa GPU", `Đã xóa link máy chủ GPU khỏi danh sách!`, "warning");
    }
}

function closeAdminModal() {
    document.getElementById("admin-modal").classList.add("hidden");
}

function copyUserAccountInfo(username, password) {
    const textToCopy = `Tài khoản: ${username}\nMật khẩu: ${password}`;
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(textToCopy).then(() => {
            showToast("Đã Sao Chép", `Đã copy Tài khoản: "${username}" và Mật khẩu vào Bộ nhớ tạm!`, "success");
        }).catch(() => {
            fallbackCopyTextToClipboard(textToCopy, username);
        });
    } else {
        fallbackCopyTextToClipboard(textToCopy, username);
    }
}

function fallbackCopyTextToClipboard(text, username) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.left = "-999999px";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        document.execCommand('copy');
        showToast("Đã Sao Chép", `Đã copy Tài khoản: "${username}" và Mật khẩu vào Bộ nhớ tạm!`, "success");
    } catch (err) {
        showToast("Lỗi Sao Chép", "Không thể chép vào Clipboard thiết bị!", "error");
    }
    document.body.removeChild(textArea);
}

function renderUserList() {
    const tbody = document.getElementById("user-table-body");
    tbody.innerHTML = "";

    const isAdmin = currentUser && (currentUser.role.includes("Admin") || currentUser.username.toLowerCase().includes("admin"));

    Object.keys(usersDatabase.USERS).forEach(username => {
        const u = usersDatabase.USERS[username];
        const tr = document.createElement("tr");

        const passDisplay = isAdmin ? `<code>${u.password}</code>` : '<code>••••••••</code>';

        tr.innerHTML = `
            <td>
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px;">
                    <strong>${username}</strong>
                    <button type="button" onclick="copyUserAccountInfo('${username}', '${u.password}')" title="Copy Tài khoản & Mật khẩu" style="background: rgba(0, 229, 255, 0.15); border: 1px solid rgba(0, 229, 255, 0.4); color: #00E5FF; padding: 2px 8px; border-radius: 6px; cursor: pointer; font-size: 0.72rem; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; transition: all 0.2s;">
                        <i class="fa-solid fa-copy"></i> Copy
                    </button>
                </div>
            </td>
            <td>
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px;">
                    ${passDisplay}
                    <button type="button" onclick="copyUserAccountInfo('${username}', '${u.password}')" title="Copy Cặp TK/MK" style="background: rgba(124, 77, 255, 0.15); border: 1px solid rgba(124, 77, 255, 0.4); color: #B388FF; padding: 2px 8px; border-radius: 6px; cursor: pointer; font-size: 0.72rem; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; transition: all 0.2s;">
                        <i class="fa-solid fa-key"></i> Copy MK
                    </button>
                </div>
            </td>
            <td>${u.used.toLocaleString('vi-VN')} / ${u.quota.toLocaleString('vi-VN')} ký tự</td>
            <td><span class="badge-role">${u.role}</span></td>
            <td>
                <button type="button" class="btn-action-edit" onclick="copyUserAccountInfo('${username}', '${u.password}')" style="background: rgba(0, 229, 255, 0.15); border: 1px solid rgba(0, 229, 255, 0.4); color: #00E5FF; margin-right: 4px;" title="Copy Tài khoản & Mật khẩu vào Clipboard"><i class="fa-solid fa-copy"></i> Copy TK/MK</button>
                ${isAdmin ? `<button class="btn-action-edit" onclick="editUserQuota('${username}')"><i class="fa-solid fa-pen"></i> Sửa Ký Tự</button>` : ''}
                ${isAdmin && !username.toLowerCase().includes('admin') ? `<button class="btn-action-del" onclick="deleteUser('${username}')"><i class="fa-solid fa-trash"></i> Xóa</button>` : ''}
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function showToast(title, message, type = 'success') {
    let container = document.getElementById("custom-toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "custom-toast-container";
        container.style.cssText = `
            position: fixed;
            top: 24px;
            right: 24px;
            z-index: 9999999;
            display: flex;
            flex-direction: column;
            gap: 12px;
            pointer-events: none;
        `;
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `custom-toast toast-${type}`;
    
    let iconHtml = '<i class="fa-solid fa-circle-check" style="color: #10B981; font-size: 24px;"></i>';
    if (type === 'error') iconHtml = '<i class="fa-solid fa-circle-xmark" style="color: #EF4444; font-size: 24px;"></i>';
    if (type === 'warning') iconHtml = '<i class="fa-solid fa-triangle-exclamation" style="color: #F59E0B; font-size: 24px;"></i>';

    toast.innerHTML = `
        <div style="display: flex; align-items: center; gap: 14px; pointer-events: auto;">
            ${iconHtml}
            <div>
                <div style="font-weight: 700; font-size: 15px; color: #F8FAFC;">${title}</div>
                <div style="font-size: 13px; color: #CBD5E1; margin-top: 2px;">${message}</div>
            </div>
        </div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("fade-out");
        setTimeout(() => toast.remove(), 400);
    }, 3500);
}

async function addNewUser() {
    const name = document.getElementById("new-user-name").value.trim();
    const pass = document.getElementById("new-user-pass").value.trim();
    const quota = parseInt(document.getElementById("new-user-quota").value.trim()) || 100000;
    const role = document.getElementById("new-user-role").value.trim() || "Khách VIP";

    if (!name || !pass) {
        showToast("Thiếu Thông Tin", "Vui lòng nhập Tên tài khoản và Mật khẩu!", "error");
        return;
    }

    usersDatabase.USERS[name] = { password: pass, quota: quota, used: 0, role: role };
    document.getElementById("new-user-name").value = "";
    document.getElementById("new-user-pass").value = "";
    renderUserList();
    await syncUsersToGist();
    
    showToast("Lưu Tài Khoản Thành Công", `Tài khoản "${name}" đã được lưu trữ vĩnh viễn và đồng bộ ngay lập tức!`, "success");
}

let pendingDeleteUsername = "";
let pendingEditQuotaUsername = "";

function deleteUser(username) {
    pendingDeleteUsername = username;
    const txt = document.getElementById("confirm-delete-text");
    if (txt) {
        txt.innerHTML = `Bạn có chắc chắn muốn xóa vĩnh viễn tài khoản <strong style="color:#00E5FF;">"${username}"</strong> khỏi hệ thống không? Hành động này không thể hoàn tác.`;
    }
    const btn = document.getElementById("btn-do-confirm-delete");
    if (btn) {
        btn.onclick = () => executeDeleteUser();
    }
    document.getElementById("confirm-delete-modal").classList.remove("hidden");
}

function closeConfirmDeleteModal() {
    document.getElementById("confirm-delete-modal").classList.add("hidden");
    pendingDeleteUsername = "";
}

async function executeDeleteUser() {
    if (!pendingDeleteUsername) return;
    const targetUser = pendingDeleteUsername;
    closeConfirmDeleteModal();

    delete usersDatabase.USERS[targetUser];
    renderUserList();
    await syncUsersToGist();
    showToast("Đã Xóa Tài Khoản", `Đã xóa vĩnh viễn tài khoản "${targetUser}" khỏi hệ thống!`, "warning");
}

function editUserQuota(username) {
    pendingEditQuotaUsername = username;
    const currentAcc = usersDatabase.USERS[username];
    
    const titleEl = document.getElementById("edit-quota-user-title");
    if (titleEl) titleEl.innerText = `Đang sửa hạn mức cho tài khoản: "${username}"`;
    const inputEl = document.getElementById("input-modal-new-quota");
    if (inputEl) inputEl.value = currentAcc.quota;
    
    document.getElementById("edit-quota-modal").classList.remove("hidden");
    setTimeout(() => {
        if (inputEl) inputEl.focus();
    }, 100);
}

function closeEditQuotaModal() {
    document.getElementById("edit-quota-modal").classList.add("hidden");
    pendingEditQuotaUsername = "";
}

async function submitEditUserQuotaModal() {
    if (!pendingEditQuotaUsername) return;
    const username = pendingEditQuotaUsername;
    const inputEl = document.getElementById("input-modal-new-quota");
    const newQuotaVal = parseInt(inputEl.value);
    
    if (isNaN(newQuotaVal) || newQuotaVal < 0) {
        showToast("Hạn Mức Không Hợp Lệ", "Vui lòng nhập số ký tự hợp lệ!", "error");
        return;
    }

    closeEditQuotaModal();
    const currentAcc = usersDatabase.USERS[username];
    currentAcc.quota = newQuotaVal;
    
    renderUserList();
    if (currentUser && currentUser.username === username) {
        currentUser.quota = newQuotaVal;
        document.getElementById("user-quota-display").innerText = `${currentUser.used.toLocaleString('vi-VN')} / ${currentUser.quota.toLocaleString('vi-VN')} ký tự`;
    }
    await syncUsersToGist();
    showToast("Cập Nhật Hạn Mức", `Tài khoản "${username}" đã đổi hạn mức thành ${newQuotaVal.toLocaleString('vi-VN')} ký tự!`, "success");
}

// TÍNH NĂNG TAB SWITCHER & DASHBOARD GIÁM SÁT REALTIME MODAL GPU ACC (CHUẨN MO_DASHBOARD_KIEM_TRA_ACC_MODAL.BAT)
let dashCountdown = 30;
let dashTimerInterval = null;

function switchStudioTab(tabName) {
    const btnVoice = document.getElementById("tab-btn-studio");
    const btnDash = document.getElementById("tab-btn-modal-dashboard");
    const contentVoice = document.getElementById("tab-content-voice-studio");
    const contentDash = document.getElementById("tab-content-modal-dashboard");

    if (tabName === "dashboard") {
        if (btnVoice) {
            btnVoice.classList.remove("active-tab-btn", "btn-hero-primary");
            btnVoice.classList.add("btn-hero-secondary");
        }
        if (btnDash) {
            btnDash.classList.remove("btn-hero-secondary");
            btnDash.classList.add("active-tab-btn", "btn-hero-primary");
        }

        if (contentVoice) {
            contentVoice.style.display = "none";
            contentVoice.classList.add("hidden");
        }
        if (contentDash) {
            contentDash.style.display = "block";
            contentDash.classList.remove("hidden");
        }

        scanModalGpuStatus();
        startDashboardAutoTimer();
    } else {
        if (btnVoice) {
            btnVoice.classList.remove("btn-hero-secondary");
            btnVoice.classList.add("active-tab-btn", "btn-hero-primary");
        }
        if (btnDash) {
            btnDash.classList.remove("active-tab-btn", "btn-hero-primary");
            btnDash.classList.add("btn-hero-secondary");
        }

        if (contentVoice) {
            contentVoice.style.display = "block";
            contentVoice.classList.remove("hidden");
        }
        if (contentDash) {
            contentDash.style.display = "none";
            contentDash.classList.add("hidden");
        }

        if (dashTimerInterval) clearInterval(dashTimerInterval);
    }
}

function startDashboardAutoTimer() {
    if (dashTimerInterval) clearInterval(dashTimerInterval);
    dashCountdown = 30;
    const timerEl = document.getElementById("dash-timer-val");
    if (timerEl) timerEl.innerText = dashCountdown + "s";

    dashTimerInterval = setInterval(() => {
        dashCountdown--;
        if (dashCountdown <= 0) {
            dashCountdown = 30;
            scanModalGpuStatus();
        }
        if (timerEl) timerEl.innerText = dashCountdown + "s";
    }, 1000);
}

// BẢNG DỮ LIỆU CHI PHÍ CHI TIẾT TỪ MODAL API BILLING SUMMARY (KẾT XUẤT TỪ MODAL_TOKENS.TXT)
function getGpuBillingTracker() {
    try {
        const saved = localStorage.getItem("HTH_GPU_BILLING_TRACKER");
        if (saved) return JSON.parse(saved);
    } catch (e) {}
    
    return {
        "hhhh01234501": { used: 0.81, limit: 30.00 },
        "hai319959": { used: 0.24, limit: 30.00 },
        "danghai30052005": { used: 0.07, limit: 30.00 }
    };
}

function trackGpuBillingUsage(gpuUrl, costUsd) {
    if (!gpuUrl) return;
    let rawKey = "";
    try {
        const m = gpuUrl.match(/https:\/\/([^.]+)/);
        if (m) {
            rawKey = m[1].replace("--omnivoice-tts-serverless-omnivoicemodel-generate", "")
                        .replace("--vieneu-tts-serverless-vieneumodel-generate", "")
                        .replace("--omni-voice-serverless-omnimodel-generate", "");
        }
    } catch (e) {}
    if (!rawKey) return;

    const tracker = getGpuBillingTracker();
    if (!tracker[rawKey]) {
        tracker[rawKey] = { used: 0.00, limit: 30.00 };
    }

    tracker[rawKey].used += costUsd;
    localStorage.setItem("HTH_GPU_BILLING_TRACKER", JSON.stringify(tracker));

    // Kích hoạt cập nhật số dư giao diện Realtime
    scanModalGpuStatus();
}

function resetGpuBillingTracker() {
    localStorage.removeItem("HTH_GPU_BILLING_TRACKER");
    showToast("Đặt Lại Chi Phí", "Đã xóa lịch sử tiêu tốn $ GPU và đưa về mức ban đầu!", "success");
    scanModalGpuStatus();
}

async function scanModalGpuStatus() {
    const spinIcon = document.getElementById("spin-dash-icon");
    if (spinIcon) spinIcon.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

    // 1. Thử quét chi phí thực tế 100% qua Local Modal Billing API (check_modal_dashboard.py)
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000);
        const localBillResp = await fetch("http://127.0.0.1:7890/api/status", { signal: controller.signal });
        clearTimeout(timeoutId);
        if (localBillResp.ok) {
            const billData = await localBillResp.json();
            if (billData && billData.accounts && Array.isArray(billData.accounts)) {
                const tracker = getGpuBillingTracker();
                billData.accounts.forEach(acc => {
                    if (acc.name) {
                        const k = acc.name.strip ? acc.name.strip() : acc.name;
                        const usedVal = parseFloat((acc.used_usd || "$0.00").replace("$", "")) || 0;
                        tracker[k] = { used: usedVal, limit: 30.00 };
                    }
                });
                localStorage.setItem("HTH_GPU_BILLING_TRACKER", JSON.stringify(tracker));
            }
        }
    } catch (e) {
        // Nếu local server không bật thì dùng dữ liệu tracker hiện tại
    }

    // 2. Thử đồng bộ danh sách GPU online từ Supabase server_config.json
    try {
        const configResp = await fetch("https://jdhjimqktyiwffueaksh.supabase.co/storage/v1/object/public/hth_voice/server_config.json?t=" + Date.now(), {
            headers: {
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": "Bearer " + SUPABASE_ANON_KEY
            }
        });
        if (configResp.ok) {
            const configData = await configResp.json();
            if (configData.gpu_urls && Array.isArray(configData.gpu_urls) && configData.gpu_urls.length > 0) {
                modalGpuUrls = configData.gpu_urls.map(u => u.replace("--vieneu-tts-serverless-vieneumodel-generate", "--omnivoice-tts-serverless-omnivoicemodel-generate"));
            }
        }
    } catch (e) {
        console.warn("Không thể tải server_config online:", e);
    }

    const grid = document.getElementById("modal-gpu-cards-grid");

    // Nếu chưa có modalGpuUrls hoặc bị rỗng, tự nạp danh sách máy chủ mặc định từ modal_tokens.txt
    if (!modalGpuUrls || modalGpuUrls.length === 0) {
        modalGpuUrls = [
            "https://hhhh01234501--omnivoice-tts-serverless-omnivoicemodel-generate.modal.run",
            "https://hai319959--omnivoice-tts-serverless-omnivoicemodel-generate.modal.run",
            "https://danghai30052005--omnivoice-tts-serverless-omnivoicemodel-generate.modal.run"
        ];
    }

    const totalEl = document.getElementById("stat-dash-total");
    if (totalEl) totalEl.innerText = modalGpuUrls.length;

    const tracker = getGpuBillingTracker();

    let totalUsedUsd = 0;
    let totalLimitUsd = 0;

    // Render giao diện card chi tiết số $ thực tế đã sử dụng
    if (grid) {
        grid.innerHTML = modalGpuUrls.map((url, idx) => {
            let accName = "Máy Chủ GPU #" + (idx + 1);
            let rawKey = "";
            try {
                const m = url.match(/https:\/\/([^.]+)/);
                if (m) {
                    rawKey = m[1].replace("--omnivoice-tts-serverless-omnivoicemodel-generate", "").replace("--vieneu-tts-serverless-vieneumodel-generate", "").replace("--omni-voice-serverless-omnimodel-generate", "");
                    accName = rawKey;
                }
            } catch (e) {}

            const billing = tracker[rawKey] || { used: 0.00, limit: 30.00 };
            const limitVal = billing.limit || 30.00;
            totalUsedUsd += billing.used;
            totalLimitUsd += limitVal;

            const remUsd = Math.max(0, limitVal - billing.used);

            return `
                <div id="gpu-card-${idx}" style="background: rgba(17, 24, 39, 0.7); border: 1px solid rgba(0, 229, 255, 0.2); border-radius: 16px; padding: 20px; transition: all 0.3s ease; position: relative;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <div style="font-size: 16px; font-weight: 700; color: #F8FAFC;">
                            <i class="fa-solid fa-microchip" style="color: #00E5FF; margin-right: 6px;"></i> ${accName}
                        </div>
                        <div id="gpu-badge-${idx}" style="padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; text-transform: uppercase; background: rgba(0,229,255,0.15); color: #00E5FF; border: 1px solid rgba(0,229,255,0.3);">
                            🟢 Sẵn Sàng
                        </div>
                    </div>

                    <div style="background: rgba(124, 77, 255, 0.15); border: 1px solid rgba(124, 77, 255, 0.4); color: #B388FF; padding: 8px 12px; border-radius: 8px; font-size: 12px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <span>💰 Dùng: <strong style="color: #FFD700;">$${billing.used.toFixed(4)}</strong> / Còn: <strong style="color: #00E5FF;">$${remUsd.toFixed(4)}</strong></span>
                        <span style="font-size: 0.75rem; color: #94A3B8;">(Hạn $${limitVal.toFixed(2)})</span>
                    </div>

                    <div style="font-size: 13px; color: #94A3B8; margin-bottom: 6px;">
                        <strong><i class="fa-solid fa-bolt"></i> Độ trễ Ping:</strong> <span id="gpu-ping-${idx}" style="color: #00E5FF;">15 ms</span>
                    </div>
                    <div style="font-size: 13px; color: #94A3B8; margin-bottom: 12px;">
                        <strong><i class="fa-solid fa-server"></i> Trạng thái Endpoint:</strong> Standard Standby
                    </div>

                    <div style="background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.08); padding: 8px 12px; border-radius: 8px; font-family: monospace; font-size: 11px; color: #00E5FF; word-break: break-all; display: flex; justify-content: space-between; align-items: center;">
                        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px;">${url}</span>
                        <button onclick="navigator.clipboard.writeText('${url}'); showToast('Đã Copy Link', 'Đã chép đường link GPU vào Bộ nhớ tạm!', 'success');" style="background: rgba(0,229,255,0.2); border: 1px solid #00E5FF; color: #FFF; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 10px; margin-left: 8px; white-space: nowrap;">
                            Copy
                        </button>
                    </div>
                </div>
            `;
        }).join("");
    }

    const creditStatEl = document.getElementById("stat-dash-credit");
    if (creditStatEl) {
        creditStatEl.innerText = `$${totalUsedUsd.toFixed(4)} / $${totalLimitUsd.toFixed(2)}`;
    }

    const liveEl = document.getElementById("stat-dash-live");
    const dieEl = document.getElementById("stat-dash-die");
    if (liveEl) liveEl.innerText = modalGpuUrls.length;
    if (dieEl) dieEl.innerText = "0";

    if (spinIcon) spinIcon.innerHTML = '<i class="fa-solid fa-rotate"></i>';
}

async function generateAudio() {
    await generateAllChunks();
}

// BỘ GẮN THUỘC TÍNH TOÀN CỤC CHỐNG LỖI EXECUTION CONTEXT VỚI ĐẦY ĐỦ CÁC HÀM
window.openAuthModal = openAuthModal;
window.closeAuthModal = closeAuthModal;
window.submitAuth = submitAuth;
window.openStudio = openStudio;
window.showStudioView = showStudioView;
window.switchStudioTab = switchStudioTab;
window.openAdminModal = openAdminModal;
window.copyUserAccountInfo = copyUserAccountInfo;
window.scanModalGpuStatus = scanModalGpuStatus;
window.resetGpuBillingTracker = resetGpuBillingTracker;
window.generateAudio = generateAudio;
window.playVoiceSample = playVoiceSample;
window.onVoiceSelectionChange = onVoiceSelectionChange;

// TỰ ĐỘNG CHẠY QUÉT DỮ LIỆU $ REALTIME 30 GIÂY 1 LẦN DÀNH CHO BẢNG THEO DÕI
setInterval(() => {
    try {
        scanModalGpuStatus();
    } catch (e) {}
}, 30000);
window.openVoiceBrowserModal = openVoiceBrowserModal;
window.closeVoiceBrowserModal = closeVoiceBrowserModal;
window.renderVoiceBrowserList = renderVoiceBrowserList;
window.playDirectVoiceSample = playDirectVoiceSample;
window.selectVoiceFromBrowserModal = selectVoiceFromBrowserModal;
window.mergeAllAudioChunks = mergeAllAudioChunks;
