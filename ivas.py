import json
import time
import random
import requests
import websocket
import cv2
import numpy as np
import pyautogui
import threading

# ================== SHARED LOCK ==================
ui_lock = threading.Lock()

# ================== BOT CONFIGURATION ==================
BOTS = [
    {
        "id": "1",
        "edge_port": "9222",
        "target_url": "https://www.ivasms.com/portal/live/my_sms",
        "ws_server": "ws://127.0.0.1:8080/ivas1",
        "ws_client": None,
        "cdp_ws": None,
        "saved_pos": None,  # 🧠 (x, y) jo pehli baar success hui
        "failed_attempts": 0,  # Kitni baar saved pos se click fail hua
    },
    {
        "id": "2",
        "edge_port": "9223",
        "target_url": "https://www.ivasms.com/portal/live/my_sms",
        "ws_server": "ws://127.0.0.1:8080/ivas2",
        "ws_client": None,
        "cdp_ws": None,
        "saved_pos": None,
        "failed_attempts": 0,
    },
]

MIN_SIZE = 35
MAX_SIZE = 40
MAX_FAILED_BEFORE_REDETECT = 3  # 3 baar fail hone par dobara detect karo

# ================== WEBSOCKET ==================
def connect_to_server(bot):
    try:
        bot["ws_client"] = websocket.create_connection(bot["ws_server"], timeout=10)
        print(f"✅ [Bot {bot['id']}] Connected to WS ({bot['ws_server']})!")
        return True
    except Exception as e:
        print(f"⚠️ [Bot {bot['id']}] WS Error: {e}")
        return False

def send_data_to_server(bot, data):
    try:
        if bot["ws_client"] is None:
            if not connect_to_server(bot):
                return
        payload = {
            "botId": bot["id"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data": data
        }
        bot["ws_client"].send(json.dumps(payload))
        print(f"📤 [Bot {bot['id']}] Data sent.")
    except Exception as e:
        print(f"❌ [Bot {bot['id']}] Send error: {e}")
        bot["ws_client"] = None
        connect_to_server(bot)

# ================== EDGE CDP ==================
def get_cdp_target(bot):
    try:
        r = requests.get(f"http://127.0.0.1:{bot['edge_port']}/json", timeout=5)
        targets = r.json()
        for t in targets:
            if t.get("type") == "page" and "ivasms.com" in t.get("url", ""):
                return t.get("webSocketDebuggerUrl")
        for t in targets:
            if t.get("type") == "page":
                return t.get("webSocketDebuggerUrl")
    except Exception as e:
        print(f"❌ [Bot {bot['id']}] CDP Error: {e}")
    return None

def cdp_command(ws, cmd_id, method, params=None):
    try:
        msg = {"id": cmd_id, "method": method}
        if params:
            msg["params"] = params
        ws.send(json.dumps(msg))
    except: pass

def cdp_wait_response(ws, cmd_id, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            ws.settimeout(1)
            result = ws.recv()
            data = json.loads(result)
            if data.get("id") == cmd_id:
                return data
        except: continue
    return None

def ensure_cdp(bot):
    try:
        if bot["cdp_ws"] is not None:
            try:
                bot["cdp_ws"].settimeout(2)
                cmd_id = random.randint(10000, 99999)
                cdp_command(bot["cdp_ws"], cmd_id, "Runtime.evaluate", {
                    "expression": "1+1", "returnByValue": True
                })
                resp = cdp_wait_response(bot["cdp_ws"], cmd_id, timeout=3)
                if resp is not None:
                    return True
            except: pass

        print(f"🔗 [Bot {bot['id']}] (Re)connecting to Edge (port {bot['edge_port']})...")
        cdp_url = get_cdp_target(bot)
        if not cdp_url:
            return False
        bot["cdp_ws"] = websocket.create_connection(cdp_url, timeout=10, suppress_origin=True)
        print(f"✅ [Bot {bot['id']}] CDP Connected!")
        return True
    except Exception as e:
        print(f"❌ [Bot {bot['id']}] CDP failed: {e}")
        bot["cdp_ws"] = None
        return False

# ================== SCREEN WAKE-UP ==================
def wake_screen(bot):
    print(f"💡 [Bot {bot['id']}] Waking screen...")
    try:
        sw, sh = pyautogui.size()
        cx = sw // 2
        cy = sh // 2
        try:
            pyautogui.moveTo(cx, cy, duration=0.2)
            time.sleep(0.2)
            pyautogui.click()
        except: pass
        time.sleep(3)
        return True
    except: return False

# ================== SCREENSHOT (THREAD-SAFE) ==================
def take_screenshot(bot):
    for attempt in range(2):
        try:
            with ui_lock:
                screenshot = pyautogui.screenshot()
                img = np.array(screenshot)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return img
        except Exception as e:
            print(f"⚠️ [Bot {bot['id']}] Screenshot {attempt+1} failed: {e}")
            if attempt < 1:
                wake_screen(bot)
    return None

# ================== CLICK (THREAD-SAFE) ==================
def safe_click(bot, cx, cy):
    try:
        with ui_lock:
            pyautogui.moveTo(cx - 15, cy - 15, duration=0.3)
            time.sleep(random.uniform(0.15, 0.4))
            pyautogui.moveTo(cx, cy, duration=0.2)
            time.sleep(random.uniform(0.1, 0.3))
            pyautogui.click()
        print(f"☑️ [Bot {bot['id']}] Clicked at ({cx}, {cy})!")
        return True
    except Exception as e:
        print(f"❌ [Bot {bot['id']}] Click failed: {e}")
        return False

# ================== DETECTION (OPENCV) ==================
def detect_checkbox_position(bot):
    """Screenshot lo, 35-40px square dhoondo, position return karo"""
    img = take_screenshot(bot)
    if img is None:
        print(f"❌ [Bot {bot['id']}] No screenshot.")
        return None

    try:
        screen_h, screen_w = img.shape[:2]
        print(f"🔍 [Bot {bot['id']}] Scanning ({screen_w}x{screen_h})...")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        for cnt in contours:
            try:
                area = cv2.contourArea(cnt)
                if 800 < area < 2500:
                    peri = cv2.arcLength(cnt, True)
                    approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
                    if len(approx) == 4:
                        x, y, w, h = cv2.boundingRect(approx)
                        if MIN_SIZE <= w <= MAX_SIZE and MIN_SIZE <= h <= MAX_SIZE:
                            ar = float(w) / h
                            if 0.85 <= ar <= 1.15:
                                cx = x + w // 2
                                cy = y + h // 2
                                center_color = img[cy, cx]
                                if (center_color[0] > 200 and
                                    center_color[1] > 200 and
                                    center_color[2] > 200):
                                    candidates.append({
                                        "x": cx, "y": cy,
                                        "w": w, "h": h, "area": w * h
                                    })
            except: continue

        if not candidates:
            print(f"⚠️ [Bot {bot['id']}] No {MIN_SIZE}-{MAX_SIZE}px square found.")
            return None

        screen_cx = screen_w // 2
        screen_cy = screen_h // 2
        candidates.sort(key=lambda c: abs(c["x"] - screen_cx) + abs(c["y"] - screen_cy))
        best = candidates[0]

        print(f"🎯 [Bot {bot['id']}] Found {len(candidates)} candidate(s). Best: ({best['x']}, {best['y']}) size={best['w']}x{best['h']}")

        # Debug image
        try:
            debug_img = img.copy()
            cv2.rectangle(debug_img,
                          (best["x"]-best["w"]//2, best["y"]-best["h"]//2),
                          (best["x"]+best["w"]//2, best["y"]+best["h"]//2),
                          (0, 255, 0), 3)
            cv2.imwrite(f"debug_click_bot{bot['id']}.png", debug_img)
        except: pass

        return (best["x"], best["y"])

    except Exception as e:
        print(f"❌ [Bot {bot['id']}] Detection error: {e}")
        return None

# ================== CLOUDFLARE HANDLER (NEW LOGIC) ==================
def handle_cloudflare(bot, page_text):
    """
    Smart handler:
    1. Agar saved_pos hai -> wait 1.5s, direct click
    2. Click ke baad check karo -> page text badla?
    3. Agar nahi badla (3 baar) -> dobara detect karo
    """
    # ================== PHASE 1: SAVED POSITION ==================
    if bot["saved_pos"] is not None:
        x, y = bot["saved_pos"]
        print(f"🧠 [Bot {bot['id']}] Using SAVED position: ({x}, {y})")

        # 1.5 second wait (Cloudflare loader ke liye)
        time.sleep(1.5)

        # Direct click
        if safe_click(bot, x, y):
            time.sleep(4)
            return True  # Assume successful (agar fail hua to next cycle pata chalega)

    # ================== PHASE 2: FRESH DETECTION ==================
    print(f"🔍 [Bot {bot['id']}] No saved position. Detecting via OpenCV...")

    for attempt in range(8):
        pos = detect_checkbox_position(bot)
        if pos:
            x, y = pos
            print(f"🎯 [Bot {bot['id']}] Detected: ({x}, {y})")

            # 1.5 second wait before click
            time.sleep(1.5)

            if safe_click(bot, x, y):
                # 🧠 SAVE the position!
                bot["saved_pos"] = (x, y)
                bot["failed_attempts"] = 0
                print(f"🧠 [Bot {bot['id']}] Position SAVED: ({x}, {y})")
                time.sleep(5)
                return True
            else:
                print(f"⚠️ [Bot {bot['id']}] Click failed. Retrying...")
        else:
            print(f"⏳ [Bot {bot['id']}] Attempt {attempt+1}: Box not ready, waiting...")
        time.sleep(1.5)

    print(f"❌ [Bot {bot['id']}] Could not detect/click after 8 attempts.")
    return False

# ================== BOT THREAD ==================
def bot_thread(bot):
    print(f"=========================================")
    print(f"🤖 [Bot {bot['id']}] Starting (port {bot['edge_port']})")
    print(f"📏 Size Filter: {MIN_SIZE}-{MAX_SIZE}px")
    print(f"🧠 Position Memory ENABLED")
    print(f"=========================================")

    for _ in range(5):
        if connect_to_server(bot): break
        time.sleep(5)

    for _ in range(10):
        if ensure_cdp(bot): break
        print(f"⏳ [Bot {bot['id']}] Waiting for Edge...")
        time.sleep(5)

    if not bot["cdp_ws"]:
        print(f"❌ [Bot {bot['id']}] No CDP. Exiting.")
        return

    cmd_id = 1
    cdp_command(bot["cdp_ws"], cmd_id, "Page.navigate", {"url": bot["target_url"]})
    cdp_wait_response(bot["cdp_ws"], cmd_id, timeout=10)
    print(f"🌐 [Bot {bot['id']}] Page opened.")

    while True:
        try:
            wait_sec = random.randint(120, 240)  # 2-4 minutes
            print(f"⏳ [Bot {bot['id']}] Next refresh in {wait_sec}s...")
            time.sleep(wait_sec)

            if not ensure_cdp(bot):
                time.sleep(10)
                continue

            cmd_id += 1
            print(f"🔄 [Bot {bot['id']}] Refreshing...")
            cdp_command(bot["cdp_ws"], cmd_id, "Page.reload", {"ignoreCache": False})
            cdp_wait_response(bot["cdp_ws"], cmd_id, timeout=15)
            time.sleep(6)

            # Text nikalo
            page_text = ""
            try:
                cmd_id += 1
                cdp_command(bot["cdp_ws"], cmd_id, "Runtime.evaluate", {
                    "expression": "document.body.innerText",
                    "returnByValue": True
                })
                response = cdp_wait_response(bot["cdp_ws"], cmd_id, timeout=10)
                if response and "result" in response:
                    result = response["result"].get("result", {})
                    page_text = result.get("value", "")
            except Exception as e:
                print(f"⚠️ [Bot {bot['id']}] Text error: {e}")

            # Cloudflare detect
            if ("Performing security verification" in page_text or
                "Verify you are human" in page_text or
                "malicious bots" in page_text):

                print(f"🚨 [Bot {bot['id']}] CLOUDFLARE DETECTED!")

                # Handle it
                handle_cloudflare(bot, page_text)

                # Wait for verification
                time.sleep(8)

                # Check karo success hui ya nahi
                try:
                    cmd_id += 1
                    cdp_command(bot["cdp_ws"], cmd_id, "Runtime.evaluate", {
                        "expression": "document.body.innerText",
                        "returnByValue": True
                    })
                    response = cdp_wait_response(bot["cdp_ws"], cmd_id, timeout=10)
                    if response and "result" in response:
                        result = response["result"].get("result", {})
                        new_text = result.get("value", "")

                        # Check: captcha gaya ya nahi?
                        if ("Performing security verification" in new_text or
                            "Verify you are human" in new_text):

                            bot["failed_attempts"] += 1
                            print(f"⚠️ [Bot {bot['id']}] CAPTCHA STILL THERE. Failed attempts: {bot['failed_attempts']}")

                            # 3 baar fail hone par saved position delete karo
                            if bot["failed_attempts"] >= MAX_FAILED_BEFORE_REDETECT:
                                print(f"🗑️ [Bot {bot['id']}] Clearing saved position (3 fails). Will re-detect.")
                                bot["saved_pos"] = None
                                bot["failed_attempts"] = 0
                        else:
                            print(f"✅ [Bot {bot['id']}] CAPTCHA SOLVED!")
                            bot["failed_attempts"] = 0
                            page_text = new_text
                except Exception as e:
                    print(f"⚠️ [Bot {bot['id']}] Verification check error: {e}")
            else:
                print(f"✅ [Bot {bot['id']}] No CAPTCHA.")
                bot["failed_attempts"] = 0  # Reset

            send_data_to_server(bot, page_text)

        except Exception as e:
            print(f"❌ [Bot {bot['id']}] Error: {e}")
            time.sleep(10)
            continue

# ================== MAIN ==================
if __name__ == "__main__":
    print("=========================================")
    print("🤖 MULTI-BOT (2 Edge Browsers)")
    print(f"📏 Size Filter: {MIN_SIZE}-{MAX_SIZE}px")
    print("🧠 SMART: Position Memory + Auto-Fallback")
    print("🎯 Pehli baar: OpenCV detect → Save position")
    print("⚡ Agli baar: Direct click (no screenshot needed)")
    print("🔄 3 fails hone par: Auto re-detect")
    print("=========================================")

    threads = []
    for bot in BOTS:
        t = threading.Thread(target=bot_thread, args=(bot,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(2)

    while True:
        try:
            time.sleep(60)
        except KeyboardInterrupt:
            print("\n🛑 Stopping all bots...")
            break
