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
        "saved_pos": None,  # (x, y) jo pehli baar success hui
        "failed_attempts": 0,  # Kitni baar saved pos se click fail hua
    },
    # {
    #     "id": "2",
    #     "edge_port": "9223",
    #     "target_url": "https://www.ivasms.com/portal/live/my_sms",
    #     "ws_server": "ws://127.0.0.1:8080/ivas2",
    #     "ws_client": None,
    #     "cdp_ws": None,
    #     "saved_pos": None,
    #     "failed_attempts": 0,
    # },
]

MIN_SIZE = 24
MAX_SIZE = 38
MAX_FAILED_BEFORE_REDETECT = 3  # 3 baar fail hone par dobara detect karo

# ================== KEEP ALIVE (ANTI-IDLE) ==================
def keep_screen_alive():
    """Har 45 second baad mouse ko move karega taake RDP screen lock ya idle na ho"""
    while True:
        try:
            time.sleep(45)
            with ui_lock:
                pyautogui.moveRel(1, 1, duration=0.1)
                pyautogui.moveRel(-1, -1, duration=0.1)
                pyautogui.press('shift')
        except Exception:
            pass

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
    except Exception:
        pass

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
            except Exception:
                pass

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
        except Exception:
            pass
        time.sleep(3)
        return True
    except Exception:
        return False

# ================== SCREENSHOT (THREAD-SAFE) ==================
def take_screenshot(bot):
    for attempt in range(2):
        try:
            if bot.get("cdp_ws"):
                try:
                    cmd_id = random.randint(10000, 99999)
                    cdp_command(bot["cdp_ws"], cmd_id, "Page.bringToFront")
                    time.sleep(0.3)
                except Exception:
                    pass

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

# ================== DETECTION (OPENCV SMART MATCHER) ==================
def detect_checkbox_position(bot):
    """
    1. Square checkbox dhoondo (Dark border + Pure White center + Verify text nearby)
    2. Backup: Cloudflare Orange Cloud dhoondo aur uske left pe checkbox click karo
    """
    img = take_screenshot(bot)
    if img is None:
        print(f"❌ [Bot {bot['id']}] No screenshot.")
        return None

    try:
        screen_h, screen_w = img.shape[:2]
        print(f"🔍 [Bot {bot['id']}] Scanning ({screen_w}x{screen_h})...")

        # ------------------ METHOD 1: SQUARE CHECKBOX DETECTION ------------------
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Checkbox ka border dark grey hota hai (40 se 135 ke darmiyan)
        border_mask = cv2.inRange(gray, 40, 135)
        contours, _ = cv2.findContours(border_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        for cnt in contours:
            try:
                x, y, w, h = cv2.boundingRect(cnt)
                if MIN_SIZE <= w <= MAX_SIZE and MIN_SIZE <= h <= MAX_SIZE:
                    ar = float(w) / h
                    # Bilkul square (chakor) hona chahiye (0.88 se 1.12)
                    if 0.88 <= ar <= 1.12:
                        cx = x + w // 2
                        cy = y + h // 2
                        
                        # Taskbar ya screen boundaries ko exclude karo
                        if cx < 60 or cy < 100 or cy > screen_h - 60:
                            continue

                        # Checkbox ke andar center color safaid (pure white) hona chahiye
                        center_color = img[cy, cx]
                        if center_color[0] > 220 and center_color[1] > 220 and center_color[2] > 220:
                            
                            # Tasdeeq: Checkbox ke dayen taraf (text area me) dark pixels hone chahiye
                            text_sample_x = min(screen_w - 5, cx + 45)
                            text_color = gray[cy, text_sample_x]
                            has_text_nearby = (text_color < 120)  # Dark text present

                            candidates.append({
                                "x": cx, "y": cy,
                                "w": w, "h": h,
                                "has_text": has_text_nearby
                            })
            except Exception:
                continue

        # Agar candidates milein to jiske sath text verify ho usko pehle lo
        if candidates:
            candidates.sort(key=lambda c: (not c["has_text"], c["x"]))
            best = candidates[0]
            print(f"🎯 [Bot {bot['id']}] Square Box Found: ({best['x']}, {best['y']}) size={best['w']}x{best['h']}")

            # Debug image save
            try:
                debug_img = img.copy()
                cv2.rectangle(debug_img,
                              (best["x"] - best["w"] // 2, best["y"] - best["h"] // 2),
                              (best["x"] + best["w"] // 2, best["y"] + best["h"] // 2),
                              (0, 255, 0), 2)
                cv2.imwrite(f"debug_click_bot{bot['id']}.png", debug_img)
            except Exception:
                pass

            return (best["x"], best["y"])

        # ------------------ METHOD 2: CLOUDFLARE ORANGE CLOUD DETECTOR ------------------
        print(f"⚠️ [Bot {bot['id']}] Box border not isolated, scanning for Cloudflare Orange Logo...")
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Orange cloud color range
        lower_orange = np.array([10, 140, 160])
        upper_orange = np.array([25, 255, 255])
        orange_mask = cv2.inRange(hsv, lower_orange, upper_orange)

        cloud_contours, _ = cv2.findContours(orange_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cc in cloud_contours:
            area = cv2.contourArea(cc)
            if 300 < area < 2500:
                cx, cy, cw, ch = cv2.boundingRect(cc)
                
                # Sirf Browser wale hissay (X < 900) me search karein, Desktop par nahi
                if cx > 900:
                    continue

                # Cloud logo mil gaya, checkbox is se taqreeban 185px left par hota hai
                target_box_x = cx - 185
                target_box_y = cy + ch // 2 + 5

                if 60 < target_box_x < 900:
                    print(f"🎯 [Bot {bot['id']}] Located via Orange Cloud! Target Box: ({target_box_x}, {target_box_y})")
                    return (target_box_x, target_box_y)

        print(f"⚠️ [Bot {bot['id']}] Neither Box nor Orange Logo found.")
        return None

    except Exception as e:
        print(f"❌ [Bot {bot['id']}] Detection error: {e}")
        return None

# ================== CLOUDFLARE HANDLER ==================
def handle_cloudflare(bot, page_text):
    """
    Smart handler with position memory and auto-fallback
    """
    # Bad saved pos check
    if bot["saved_pos"] is not None:
        if bot["saved_pos"][0] < 60:
            bot["saved_pos"] = None

    # PHASE 1: SAVED POSITION
    if bot["saved_pos"] is not None:
        x, y = bot["saved_pos"]
        print(f"🧠 [Bot {bot['id']}] Using SAVED position: ({x}, {y})")
        time.sleep(1.5)
        if safe_click(bot, x, y):
            time.sleep(6)  # Verification circle delay
            return True

    # PHASE 2: FRESH DETECTION
    print(f"🔍 [Bot {bot['id']}] No saved position. Detecting via OpenCV...")

    for attempt in range(8):
        pos = detect_checkbox_position(bot)
        if pos:
            x, y = pos
            print(f"🎯 [Bot {bot['id']}] Detected target: ({x}, {y})")

            time.sleep(1.5)

            if safe_click(bot, x, y):
                bot["saved_pos"] = (x, y)
                bot["failed_attempts"] = 0
                print(f"🧠 [Bot {bot['id']}] Position SAVED: ({x}, {y})")
                time.sleep(6)
                return True
            else:
                print(f"⚠️ [Bot {bot['id']}] Click failed. Retrying...")
        else:
            print(f"⏳ [Bot {bot['id']}] Attempt {attempt+1}: Widget not ready, waiting...")
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

                handle_cloudflare(bot, page_text)

                time.sleep(8)

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

                        if ("Performing security verification" in new_text or
                            "Verify you are human" in new_text):

                            bot["failed_attempts"] += 1
                            print(f"⚠️ [Bot {bot['id']}] CAPTCHA STILL THERE. Failed attempts: {bot['failed_attempts']}")

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
                bot["failed_attempts"] = 0

            send_data_to_server(bot, page_text)

        except Exception as e:
            print(f"❌ [Bot {bot['id']}] Error: {e}")
            time.sleep(10)
            continue

# ================== MAIN ==================
if __name__ == "__main__":
    print("=========================================")
    print("🤖 MULTI-BOT (Edge Automation)")
    print(f"📏 Size Filter: {MIN_SIZE}-{MAX_SIZE}px")
    print("🧠 SMART: Position Memory + Auto-Fallback")
    print("🎯 Pehli baar: OpenCV detect → Save position")
    print("⚡ Agli baar: Direct click (no screenshot needed)")
    print("🔄 3 fails hone par: Auto re-detect")
    print("💡 Anti-Idle Screen Protector: ENABLED")
    print("=========================================")

    # 1. Anti-Idle Thread start
    idle_thread = threading.Thread(target=keep_screen_alive, daemon=True)
    idle_thread.start()

    # 2. Bots Threads
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
