import json
import time
import random
import requests
import websocket
import threading

# ================== سیٹنگز ==================
EDGE_PORT = "9222"          # Edge ka debug port
BOT_ID = "1"                # Bot number
WS_SERVER = f"ws://127.0.0.1:8080/ivas{BOT_ID}"  # Aapna server (Go)
TARGET_URL = "https://www.ivasms.com/portal/live/my_sms"

# ================== ویب ساکٹ کنکشن (اپنے سرور سے) ==================
ws_client = None

def connect_to_server():
    global ws_client
    try:
        ws_client = websocket.create_connection(WS_SERVER, timeout=10)
        print(f"✅ [Bot {BOT_ID}] Connected to WebSocket Server ({WS_SERVER})!")
    except Exception as e:
        print(f"⚠️ [Bot {BOT_ID}] WS Error: {e}. Retrying in 5s...")
        time.sleep(5)
        connect_to_server()

def send_data_to_server(data):
    global ws_client
    if ws_client:
        try:
            payload = {
                "botId": BOT_ID,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": data
            }
            ws_client.send(json.dumps(payload))
            print(f"📤 [Bot {BOT_ID}] Data sent to server.")
        except Exception as e:
            print(f"❌ [Bot {BOT_ID}] Error sending data: {e}")
            connect_to_server()

# ================== CDP (Edge Browser) سے کنیکٹ ہونا ==================
def get_cdp_target():
    """Edge ke CDP se target tab ka WebSocket URL lo"""
    try:
        r = requests.get(f"http://127.0.0.1:{EDGE_PORT}/json")
        targets = r.json()
        for t in targets:
            if t.get("type") == "page" and "ivasms.com" in t.get("url", ""):
                return t.get("webSocketDebuggerUrl")
        # Agar target tab nahi mila to pehla page tab le lo
        for t in targets:
            if t.get("type") == "page":
                return t.get("webSocketDebuggerUrl")
    except Exception as e:
        print(f"❌ [Bot {BOT_ID}] CDP Error: {e}")
    return None

def cdp_command(ws, cmd_id, method, params=None):
    """CDP command bhejo"""
    msg = {"id": cmd_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))

def cdp_wait_response(ws, cmd_id, timeout=10):
    """CDP response ka wait karo"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            ws.settimeout(1)
            result = ws.recv()
            data = json.loads(result)
            if data.get("id") == cmd_id:
                return data
        except Exception:
            continue
    return None

# ================== مین بوٹ لاجک ==================
def start_bot():
    connect_to_server()

    # 1. Target tab ka CDP URL lo
    cdp_url = get_cdp_target()
    if not cdp_url:
        print(f"❌ [Bot {BOT_ID}] No target tab found. Edge khola hua hai?")
        return

    print(f"🔗 [Bot {BOT_ID}] Connecting to Edge CDP...")
    
    try:
        cdp_ws = websocket.create_connection(cdp_url, timeout=10)
        print(f"✅ [Bot {BOT_ID}] Connected to Edge CDP!")
    except Exception as e:
        print(f"❌ [Bot {BOT_ID}] CDP Connection failed: {e}")
        return

    # 2. Pehli baar page navigate karo
    cmd_id = 1
    cdp_command(cdp_ws, cmd_id, "Page.navigate", {"url": TARGET_URL})
    cdp_wait_response(cdp_ws, cmd_id, timeout=10)
    print(f"🌐 [Bot {BOT_ID}] Page opened.")

    # ================== INFINITE LOOP ==================
    loop_count = 0
    while True:
        loop_count += 1
        
        # Random wait (40 to 80 seconds)
        wait_sec = random.randint(40, 80)
        print(f"⏳ [Bot {BOT_ID}] Waiting {wait_sec} seconds...")
        time.sleep(wait_sec)

        # 1. Page refresh karo
        cmd_id += 1
        print(f"🔄 [Bot {BOT_ID}] Refreshing page...")
        cdp_command(cdp_ws, cmd_id, "Page.reload", {"ignoreCache": False})
        cdp_wait_response(cdp_ws, cmd_id, timeout=15)
        
        # 2. Page load hone ka wait
        time.sleep(6)

        # 3. Page ka text nikalo
        cmd_id += 1
        cdp_command(cdp_ws, cmd_id, "Runtime.evaluate", {
            "expression": "document.body.innerText",
            "returnByValue": True
        })
        response = cdp_wait_response(cdp_ws, cmd_id, timeout=10)
        
        page_text = ""
        if response and "result" in response:
            result = response["result"].get("result", {})
            page_text = result.get("value", "")

        # 4. Check karo ke Cloudflare hai ya nahi
        if "Performing security verification" in page_text or "Verify you are human" in page_text:
            print(f"🚨 [Bot {BOT_ID}] CLOUDFLARE DETECTED! Waiting for clicker...")
            time.sleep(10)  # Python clicker ya AHK click karega
            # Dobara text nikalo click ke baad
            cmd_id += 1
            cdp_command(cdp_ws, cmd_id, "Runtime.evaluate", {
                "expression": "document.body.innerText",
                "returnByValue": True
            })
            response = cdp_wait_response(cdp_ws, cmd_id, timeout=10)
            if response and "result" in response:
                result = response["result"].get("result", {})
                page_text = result.get("value", "")
        else:
            print(f"✅ [Bot {BOT_ID}] Page is clean. No CAPTCHA.")

        # 5. Data server par bhejo
        send_data_to_server(page_text)

if __name__ == "__main__":
    print("=========================================")
    print(f"🤖 Python Bot ID: {BOT_ID}")
    print(f"🔗 Forwarding to: {WS_SERVER}")
    print("=========================================")
    start_bot()
