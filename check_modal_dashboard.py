import os
import sys
import json
import re
import subprocess
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PORT = 7890
IS_DEPLOYING = False
DEPLOY_LOGS = []

def load_accounts_from_txt(txt_path="modal_tokens.txt"):
    if not os.path.exists(txt_path):
        return []
    
    accounts = []
    with open(txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 1. Bóc tách từ câu lệnh raw modal token set --token-id ak-... --token-secret as-... --profile=xxx
            match_id = re.search(r'--token-id[=\s]+([^\s]+)', line)
            match_secret = re.search(r'--token-secret[=\s]+([^\s]+)', line)
            if match_id and match_secret:
                t_id = match_id.group(1).strip("\"':=")
                t_secret = match_secret.group(1).strip("\"':=")
                match_prof = re.search(r'--profile[=\s]+([^\s]+)', line)
                name = match_prof.group(1).strip("\"':=") if match_prof else f"Acc {len(accounts)+1}"
                accounts.append({"type": "token", "id": t_id, "secret": t_secret, "name": name})
                continue
                
            # 2. Bóc tách dạng ak-... | as-... | Tên Acc
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 2 and parts[0].startswith("ak-") and parts[1].startswith("as-"):
                name = parts[2] if len(parts) >= 3 else f"Acc {len(accounts)+1}"
                accounts.append({"type": "token", "id": parts[0], "secret": parts[1], "name": name})
                continue
                
            # 3. Bóc tách dạng profile name
            if len(parts) >= 1 and not line.startswith("ak-"):
                prof_name = parts[0]
                label = parts[1] if len(parts) >= 2 else f"Profile ({prof_name})"
                accounts.append({"type": "profile", "profile": prof_name, "name": label})
                
    return accounts

def check_single_account(acc):
    info = {
        "name": acc.get("name", "Account"),
        "status": "DIE",
        "username": "N/A",
        "url": "N/A",
        "latency_ms": 0,
        "used_usd": "$0.00",
        "rem_credit": "$30.00",
        "credit_usd": "Còn $30.00 (Đã dùng $0.00)",
        "details": ""
    }
    
    modal_exe = os.path.join(os.path.dirname(sys.executable), 'Scripts', 'modal.exe')
    if not os.path.exists(modal_exe):
        modal_exe = 'modal'
        
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    
    if acc.get("type") == "token":
        env["MODAL_TOKEN_ID"] = acc["id"]
        env["MODAL_TOKEN_SECRET"] = acc["secret"]
        if "MODAL_PROFILE" in env:
            del env["MODAL_PROFILE"]
    else:
        env["MODAL_PROFILE"] = acc.get("profile", "default")
        
    # 1. Kiểm tra xác thực token & ứng dụng (MIỄN PHÍ 100%, KHÔNG BẬT GPU)
    try:
        cmd = [modal_exe, "app", "list"]
        start_t = time.time()
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
        info["latency_ms"] = int((time.time() - start_t) * 1000)
        
        if res.returncode == 0:
            info["status"] = "LIVE"
            info["details"] = "Token hợp lệ & đã xác thực!"
            if "profile" in acc:
                info["username"] = acc["profile"]
            elif "id" in acc:
                info["username"] = f"Token ({acc['id'][:8]}...)"
                
            for line in res.stdout.splitlines():
                if "omnivoice-tts-serverless" in line or "vieneu-tts-serverless" in line:
                    parts = line.split()
                    if parts:
                        app_name = parts[0]
                        info["details"] = f"App '{app_name}' đã deploy sẵn sàng!"
        else:
            info["status"] = "DIE"
            info["details"] = f"Lỗi xác thực: {res.stderr.strip()[:100]}"
    except Exception as e:
        info["status"] = "DIE"
        info["details"] = f"Lỗi kết nối: {str(e)[:100]}"

    # 2. Truy vấn chi phí bằng modal billing summary (MIỄN PHÍ 100%, KHÔNG BẬT GPU)
    if info["status"] == "LIVE":
        try:
            cmd_bill = [modal_exe, "billing", "summary"]
            res_bill = subprocess.run(cmd_bill, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
            if res_bill.returncode == 0:
                metered_match = re.search(r'Metered Cost:\s+([\d\.]+)', res_bill.stdout)
                if metered_match:
                    used_val = float(metered_match.group(1))
                    rem_val = max(0.0, 30.0 - used_val)
                    info["used_usd"] = f"${used_val:.2f}"
                    info["rem_credit"] = f"${rem_val:.2f}"
                    info["credit_usd"] = f"Còn ${rem_val:.2f} (Đã dùng ${used_val:.2f})"
        except Exception:
            pass

    # Suy ra Endpoint URL dạng tĩnh (KHÔNG HTTP PING để tránh gọi GPU tỉnh dậy tốn tiền)
    uname = acc.get("name", "").strip()
    if acc.get("type") == "profile":
        uname = acc.get("profile", "")
        
    if uname and not uname.startswith("Acc") and not uname.startswith("Profile"):
        info["username"] = uname
        constructed_url = f"https://{uname}--omnivoice-tts-serverless-omnivoicemodel-generate.modal.run"
        info["url"] = constructed_url
        info["endpoint_status"] = "Sẵn sàng (Standby)"
            
    return info

def run_deploy_all_thread():
    global IS_DEPLOYING, DEPLOY_LOGS
    IS_DEPLOYING = True
    DEPLOY_LOGS = ["🚀 Bắt đầu khởi chạy Deploy hàng loạt cho tất cả các tài khoản..."]
    
    python_exe = sys.executable
    deploy_script = "deploy_all_modal.py"
    
    try:
        process = subprocess.Popen(
            [python_exe, deploy_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        
        for line in iter(process.stdout.readline, ''):
            if line:
                clean_line = line.strip()
                if clean_line:
                    DEPLOY_LOGS.append(clean_line)
                    
        process.stdout.close()
        process.wait()
        DEPLOY_LOGS.append("🎉 ĐÃ HOÀN TẤT TIẾN TRÌNH DEPLOY HÀNG LOẠT!")
    except Exception as e:
        DEPLOY_LOGS.append(f"❌ Lỗi trong tiến trình Deploy: {e}")
    finally:
        IS_DEPLOYING = False

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/api/status":
            accounts = load_accounts_from_txt()
            results = []
            threads = []
            
            def worker(acc):
                res = check_single_account(acc)
                results.append(res)
                
            for acc in accounts:
                t = threading.Thread(target=worker, args=(acc,))
                threads.append(t)
                t.start()
                
            for t in threads:
                t.join(timeout=12)
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(json.dumps({"total": len(results), "accounts": results}, ensure_ascii=False).encode('utf-8'))
            return
            
        elif self.path == "/api/deploy":
            global IS_DEPLOYING
            if not IS_DEPLOYING:
                threading.Thread(target=run_deploy_all_thread, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}, ensure_ascii=False).encode('utf-8'))
            return
            
        elif self.path == "/api/deploy-logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(json.dumps({"is_deploying": IS_DEPLOYING, "logs": DEPLOY_LOGS}, ensure_ascii=False).encode('utf-8'))
            return

        html_content = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⚡ Realtime Dashboard - Modal API Billing & Monitor</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: #0B0F19; color: #F3F4F6; padding: 30px 20px; min-height: 100vh; }
        .container { max-width: 1150px; margin: 0 auto; }
        
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; background: rgba(17, 24, 39, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 20px 28px; }
        .brand { display: flex; align-items: center; gap: 14px; }
        .brand-icon { width: 44px; height: 44px; background: linear-gradient(135deg, #00E5FF, #7C4DFF); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: bold; color: #fff; box-shadow: 0 0 20px rgba(0,229,255,0.4); }
        .brand-title { font-size: 20px; font-weight: 800; background: linear-gradient(90deg, #00E5FF, #A78BFA); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .brand-subtitle { font-size: 13px; color: #9CA3AF; margin-top: 2px; }
        
        .header-actions { display: flex; gap: 12px; align-items: center; }
        .btn { font-weight: 700; border: none; padding: 12px 20px; border-radius: 10px; cursor: pointer; transition: all 0.3s ease; display: flex; align-items: center; gap: 8px; font-size: 14px; }
        .btn-refresh { background: linear-gradient(135deg, #00E676, #00B0FF); color: #050B14; box-shadow: 0 4px 15px rgba(0,230,118,0.3); }
        .btn-refresh:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,230,118,0.5); }
        .btn-deploy { background: linear-gradient(135deg, #7C4DFF, #FF007F); color: #FFF; box-shadow: 0 4px 15px rgba(124,77,255,0.4); }
        .btn-deploy:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(124,77,255,0.6); }

        .timer-box { font-size: 13px; color: #00E5FF; font-weight: 600; text-align: right; margin-bottom: 20px; display: flex; justify-content: flex-end; align-items: center; gap: 8px; }

        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: rgba(17, 24, 39, 0.5); border: 1px solid rgba(255,255,255,0.05); border-radius: 16px; padding: 20px; backdrop-filter: blur(8px); }
        .stat-val { font-size: 30px; font-weight: 800; color: #FFF; margin-top: 6px; }
        .stat-lbl { font-size: 13px; color: #9CA3AF; text-transform: uppercase; letter-spacing: 0.5px; }

        .acc-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 20px; }
        .acc-card { background: rgba(17, 24, 39, 0.6); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; padding: 22px; transition: all 0.3s ease; position: relative; }
        .acc-card:hover { border-color: rgba(0, 229, 255, 0.4); transform: translateY(-4px); box-shadow: 0 8px 30px rgba(0,0,0,0.4); }
        .acc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
        .acc-name { font-size: 17px; font-weight: 700; color: #F9FAFB; }
        
        .badge { padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
        .badge-live { background: rgba(0, 230, 118, 0.15); color: #00E676; border: 1px solid rgba(0, 230, 118, 0.3); }
        .badge-die { background: rgba(255, 51, 102, 0.15); color: #FF3366; border: 1px solid rgba(255, 51, 102, 0.3); }

        .credit-tag { background: rgba(124, 77, 255, 0.15); border: 1px solid rgba(124, 77, 255, 0.4); color: #B388FF; padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: 700; display: inline-block; margin-bottom: 12px; }

        .acc-info { font-size: 13px; color: #9CA3AF; margin-bottom: 8px; line-height: 1.5; }
        .acc-info strong { color: #E5E7EB; }
        
        .url-box { background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06); padding: 10px 14px; border-radius: 8px; font-family: monospace; font-size: 12px; color: #00E5FF; word-break: break-all; margin-top: 12px; display: flex; justify-content: space-between; align-items: center; }
        .btn-copy { background: rgba(255,255,255,0.1); border: none; color: #FFF; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 11px; margin-left: 8px; }
        .btn-copy:hover { background: #00E5FF; color: #000; }

        .log-panel { background: #050B14; border: 1px solid rgba(124,77,255,0.3); border-radius: 16px; padding: 20px; margin-top: 30px; display: none; }
        .log-title { font-weight: 700; color: #B388FF; margin-bottom: 10px; font-size: 15px; display: flex; justify-content: space-between; }
        .log-content { background: #000; padding: 15px; border-radius: 8px; height: 180px; overflow-y: auto; font-family: monospace; font-size: 12px; color: #00E676; line-height: 1.6; }

        .loader { border: 3px solid rgba(255,255,255,0.1); border-radius: 50%; border-top: 3px solid #00E676; width: 14px; height: 14px; animation: spin 1s linear infinite; display: inline-block; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <div class="brand-icon">⚡</div>
                <div>
                    <div class="brand-title">MODAL API REALTIME MONITOR & BILLING</div>
                    <div class="brand-subtitle">Siêu cấp tool Voice VIP PRO - Kiểm tra Chi phí & Deploy hàng loạt</div>
                </div>
            </div>
            <div class="header-actions">
                <button class="btn btn-deploy" id="btnDeploy" onclick="startDeployAll()">
                    🚀 DEPLOY TẤT CẢ ACC
                </button>
                <button class="btn btn-refresh" id="btnRefresh" onclick="manualRefresh()">
                    <span id="spinIcon">🔄</span> Quét Ngay
                </button>
            </div>
        </header>

        <div class="timer-box">
            <span>⏱️ Tự động quét lại trong:</span>
            <strong id="timerVal" style="font-size: 16px;">30s</strong>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-lbl">Tổng số Tài khoản</div>
                <div class="stat-val" id="totalAcc">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-lbl">Tài khoản Live 🟢</div>
                <div class="stat-val" style="color:#00E676" id="liveAcc">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-lbl">Tài khoản Lỗi 🔴</div>
                <div class="stat-val" style="color:#FF3366" id="dieAcc">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-lbl">Tổng Chi phí Đã dùng 💵</div>
                <div class="stat-val" style="color:#00E5FF" id="totalUsedUsd">$0.00</div>
            </div>
        </div>

        <div class="acc-grid" id="accList">
            <div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #9CA3AF;">
                <div class="loader"></div> Đang kiểm tra chi phí & trạng thái Realtime của các tài khoản...
            </div>
        </div>

        <div class="log-panel" id="logPanel">
            <div class="log-title">
                <span>📋 NHẬT KÝ DEPLOY HÀNG LOẠT REALTIME</span>
                <span id="deployStatusLbl" style="color:#00E5FF;">ĐANG CHẠY...</span>
            </div>
            <div class="log-content" id="logText"></div>
        </div>
    </div>

    <script>
        let countdown = 30;
        let timerInterval = null;
        let logPollInterval = null;

        function startTimer() {
            clearInterval(timerInterval);
            countdown = 30;
            document.getElementById('timerVal').innerText = countdown + 's';
            timerInterval = setInterval(() => {
                countdown--;
                if (countdown <= 0) {
                    countdown = 30;
                    fetchStatus();
                }
                document.getElementById('timerVal').innerText = countdown + 's';
            }, 1000);
        }

        async function manualRefresh() {
            startTimer();
            await fetchStatus();
        }

        async function fetchStatus() {
            const btn = document.getElementById('btnRefresh');
            const spin = document.getElementById('spinIcon');
            spin.innerHTML = '<div class="loader"></div>';
            btn.disabled = true;

            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                document.getElementById('totalAcc').innerText = data.total;
                let liveCount = 0;
                let dieCount = 0;
                let sumUsedUsd = 0;

                const grid = document.getElementById('accList');
                grid.innerHTML = '';

                data.accounts.forEach(acc => {
                    if (acc.status === 'LIVE') liveCount++;
                    else dieCount++;

                    let usedVal = parseFloat((acc.used_usd || '$0.00').replace('$', '')) || 0;
                    sumUsedUsd += usedVal;

                    const badgeClass = acc.status === 'LIVE' ? 'badge-live' : 'badge-die';
                    const badgeText = acc.status === 'LIVE' ? '🟢 LIVE' : '🔴 DIE';

                    let urlHTML = '';
                    if (acc.url && acc.url !== 'N/A') {
                        urlHTML = `
                            <div class="url-box">
                                <span>${acc.url}</span>
                                <button class="btn-copy" onclick="navigator.clipboard.writeText('${acc.url}'); alert('Đã chép Link URL!');">Copy</button>
                            </div>
                        `;
                    }

                    grid.innerHTML += `
                        <div class="acc-card">
                            <div class="acc-header">
                                <div class="acc-name">${acc.name}</div>
                                <div class="badge ${badgeClass}">${badgeText}</div>
                            </div>
                            <div class="credit-tag">💰 Credit còn: ${acc.rem_credit} (Đã dùng ${acc.used_usd})</div>
                            <div class="acc-info"><strong>Username:</strong> ${acc.username}</div>
                            <div class="acc-info"><strong>Độ trễ API:</strong> ${acc.latency_ms} ms</div>
                            <div class="acc-info"><strong>Trạng thái Endpoint:</strong> ${acc.endpoint_status || 'Sẵn sàng'}</div>
                            <div class="acc-info"><strong>Chi tiết:</strong> ${acc.details}</div>
                            ${urlHTML}
                        </div>
                    `;
                });

                document.getElementById('liveAcc').innerText = liveCount;
                document.getElementById('dieAcc').innerText = dieCount;
                document.getElementById('totalUsedUsd').innerText = '$' + sumUsedUsd.toFixed(2);
            } catch (err) {
                console.error(err);
            } finally {
                spin.innerText = '🔄';
                btn.disabled = false;
            }
        }

        async function startDeployAll() {
            if (!confirm('Bạn có chắc chắn muốn Deploy lại tệp modal_vieneu_app.py cho TẤT CẢ TÀI KHOẢN trong modal_tokens.txt?')) {
                return;
            }

            document.getElementById('logPanel').style.display = 'block';
            document.getElementById('btnDeploy').disabled = true;
            document.getElementById('deployStatusLbl').innerText = '⏳ ĐANG TIẾN HÀNH DEPLOY...';

            await fetch('/api/deploy');

            clearInterval(logPollInterval);
            logPollInterval = setInterval(pollDeployLogs, 1500);
        }

        async function pollDeployLogs() {
            try {
                const res = await fetch('/api/deploy-logs');
                const data = await res.json();
                
                const logBox = document.getElementById('logText');
                logBox.innerText = data.logs.join('\\n');
                logBox.scrollTop = logBox.scrollHeight;

                if (!data.is_deploying) {
                    clearInterval(logPollInterval);
                    document.getElementById('btnDeploy').disabled = false;
                    document.getElementById('deployStatusLbl').innerText = '✅ HOÀN TẤT DEPLOY!';
                    fetchStatus();
                }
            } catch (e) {
                console.error(e);
            }
        }

        fetchStatus();
        startTimer();
    </script>
</body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))

def run_server():
    server = HTTPServer(('127.0.0.1', PORT), DashboardHandler)
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 65)
    print(f"🚀 DASHBOARD MONITOR & BILLING REALTIME ĐANG CHẠY TẠI: {url}")
    print("=" * 65)
    
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server.serve_forever()

if __name__ == '__main__':
    run_server()
