import json
import time
import random
import requests
import websocket
import cv2
import numpy as np
import pyautogui

# ================== SETTINGS ==================
EDGE_PORT = "9222"
BOT_ID = "1"
WS_SERVER = f"ws://127.0.0.1:8080/ivas{BOT_ID}"
TARGET_URL = "https://www.ivasms.com/portal/live/my_sms"

ws_client = None

# ================== WEBSOCKET (SERVER SE) ==================
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
            print(f"❌ [Bot {BOT_ID}] Send error: {e}")
            connect_to_server()

# ================== EDGE CDP SE CONNECT ==================
def get_cdp_target():
    try:
        r = requests.get(f"http://127.0.0.1:{EDGE_PORT}/json")
        targets = r.json()
        for t in targets:
            if t.get("type") == "page" and "ivasms.com" in t.get("url", ""):
                return t.get("webSocketDebuggerUrl")
        for t in targets:
            if t.get("type") == "page":
                return t.get("webSocketDebuggerUrl")
    except Exception as e:
        print(f"❌ [Bot {BOT_ID}] CDP Error: {e}")
    return None

def cdp_command(ws, cmd_id, method, params=None):
    msg = {"id": cmd_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))

def cdp_wait_response(ws, cmd_id, timeout=10):
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

# ================== OPENCV: SQUARE BOX DETECTION & CLICK ==================
def find_and_click_checkbox():
    """
    Ye function screen ka screenshot leta hai, OpenCV se square shape
    dhoondta hai jiske andar safed (white) ho, aur phir us par
    pyautogui se real mouse click karta hai.
    """
    print(f"🔍 [Bot {BOT_ID}] Scanning screen for checkbox...")

    # 1. Screenshot lo
    screenshot = pyautogui.screenshot()
    img = np.array(screenshot)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    # 2. Grey (black & white) banao
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Threshold lagao (dark borders highlight karo)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # 4. Shapes (contours) dhoondo
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for cnt in contours:
        area = cv2.contourArea(cnt)
        # Checkbox ka area chhota hota hai
        if 300 < area < 3000:
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)

            # 4 corners matlab square ya rectangle
            if len(approx) == 4:
                x, y, w, h = cv2.boundingRect(approx)
                aspect_ratio = float(w) / h

                # Square check (lambai aur chaurai barabar)
                if 0.7 <= aspect_ratio <= 1.3:
                    center_x = x + w // 2
                    center_y = y + h // 2
                    center_color = img[center_y, center_x]

                    # Andar safed (white) color ho
                    if center_color[0] > 200 and center_color[1] > 200 and center_color[2] > 200:
                        print(f"✅ [Bot {BOT_ID}] Square checkbox FOUND at ({center_x}, {center_y})")

                        # Human-like mouse movement
                        pyautogui.moveTo(center_x - 15, center_y - 15, duration=0.3)
                        time.sleep(random.uniform(0.15, 0.4))
                        pyautogui.moveTo(center_x, center_y, duration=0.2)
                        time.sleep(random.uniform(0.1, 0.3))
                        pyautogui.click()

                        print(f"☑️ [Bot {BOT_ID}] Clicked successfully!")
                        time.sleep(5)
                        return True

    print(f"⚠️ [Bot {BOT_ID}] Checkbox not found on screen.")
    return False

# ================== MAIN BOT LOOP ==================
def start_bot():
    connect_to_server()

    cdp_url = get_cdp_target()
    if not cdp_url:
        print(f"❌ [Bot {BOT_ID}] No target tab. Edge khula hai?")
        return

    print(f"🔗 [Bot {BOT_ID}] Connecting to Edge CDP...")
    try:
        cdp_ws = websocket.create_connection(
            cdp_url, timeout=10, suppress_origin=True
        )
        print(f"✅ [Bot {BOT_ID}] Connected to Edge CDP!")
    except Exception as e:
        print(f"❌ [Bot {BOT_ID}] CDP failed: {e}")
        return

    # Pehli baar page kholo
    cmd_id = 1
    cdp_command(cdp_ws, cmd_id, "Page.navigate", {"url": TARGET_URL})
    cdp_wait_response(cdp_ws, cmd_id, timeout=10)
    print(f"🌐 [Bot {BOT_ID}] Page opened.")

    # ================== INFINITE LOOP ==================
    while True:
        wait_sec = random.randint(40, 80)
        print(f"⏳ [Bot {BOT_ID}] Next refresh in {wait_sec} seconds...")
        time.sleep(wait_sec)

        # Refresh karo
        cmd_id += 1
        print(f"🔄 [Bot {BOT_ID}] Refreshing...")
        cdp_command(cdp_ws, cmd_id, "Page.reload", {"ignoreCache": False})
        cdp_wait_response(cdp_ws, cmd_id, timeout=15)

        time.sleep(6)

        # Page ka text nikalo
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

        # Cloudflare detect
        if ("Performing security verification" in page_text or
            "Verify you are human" in page_text or
            "malicious bots" in page_text):

            print(f"🚨 [Bot {BOT_ID}] CLOUDFLARE DETECTED!")

            # Try up to 5 times to find and click
            for attempt in range(5):
                if find_and_click_checkbox():
                    break
                time.sleep(3)

            # Click ke baad 10 second wait
            time.sleep(10)

            # Dobara text nikalo
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
            print(f"✅ [Bot {BOT_ID}] No CAPTCHA.")

        # Data server ko bhejo
        send_data_to_server(page_text)


if __name__ == "__main__":
    print("=========================================")
    print(f"🤖 Python Bot ID: {BOT_ID}")
    print(f"🔗 Forwarding to: {WS_SERVER}")
    print("📸 OpenCV-based checkbox clicker (no AutoHotkey)")
    print("=========================================")
    start_bot()
