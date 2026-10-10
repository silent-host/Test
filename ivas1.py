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
        "saved_pos": None,
        "failed_attempts": 0,
    },
]

# سائز کی حدود
MIN_SIZE = 20
MAX_SIZE = 50
MAX_FAILED_BEFORE_REDETECT = 3

# ================== KEEP ALIVE (ANTI-IDLE) ==================
def keep_screen_alive():
    """Har 45 second baad mouse ko move karega taake RDP screen lock na ho"""
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

# ================== DETECTION (NEW SHAPE & TEXT BASED) ==================
def detect_checkbox_position(bot):
    """
    Naya Logic:
    1. Sirf Chakor (Square) box dhoondega.
    2. Box ke andar ka rang safaid (White) hona chahiye.
    3. Box ke right side par Text (Verify) ka block hona chahiye.
    4. Screen ke upar wale hissay (Y < 400) ko completely ignore karega.
    """
    img = take_screenshot(bot)
    if img is None:
        print(f"❌ [Bot {bot['id']}] No screenshot.")
        return None

    try:
        screen_h, screen_w = img.shape[:2]
        print(f"🔍 [Bot {bot['id']}] Scanning ({screen_w}x{screen_h})...")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 1. Dark borders ko highlight karne ke liye threshold
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
        
        # 2. Contours dhoondo
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_candidate = None

        for cnt in contours:
            try:
                area = cv2.contourArea(cnt)
                peri = cv2.arcLength(cnt, True)
                if peri == 0: continue

                x, y, w, h = cv2.boundingRect(cnt)

                # Filter 1: Size (Chakor box 20-50px ka hota hai)
                if MIN_SIZE <= w <= MAX_SIZE and MIN_SIZE <= h <= MAX_SIZE:
                    ar = float(w) / h
                    
                    # Filter 2: Aspect Ratio (Bilkul chakor 0.8 se 1.2 ke darmiyan)
                    if 0.8 <= ar <= 1.2:
                        cx = x + w // 2
                        cy = y + h // 2

                        # ================== SAKHT FILTER ==================
                        # Screen ke upar wale hissay ko ignore karo (URL bar, website title, etc.)
                        # Kyunke asli captcha box hamesha screen ke nichlay hissay mein hota hai.
                        if cy < 400: 
                            continue
                        
                        # Right side (Terminal window) ko ignore karo
                        if cx > screen_w * 0.6:
                            continue
                        # ===================================================

                        # Filter 3: Box ka center safaid (White) hona chahiye
                        center_color = img[cy, cx]
                        if all(c > 200 for c in center_color):
                            
                            # Filter 4: "Verify" Text Check (Box ke right side par text block hona chahiye)
                            text_zone_x_start = x + w + 5
                            text_zone_x_end = min(x + w + 120, screen_w)
                            
                            if text_zone_x_end > text_zone_x_start:
                                text_zone = gray[y:y+h, text_zone_x_start:text_zone_x_end]
                                # Agar wahan text hai, to pixels ka standard deviation zyada hoga
                                if np.std(text_zone) > 25:
                                    best_candidate = (cx, cy)
                                    print(f"🎯 [Bot {bot['id']}] Perfect Chakor Box + Verify Text Found: ({cx}, {cy}) size={w}x{h}")
                                    break
            except Exception:
                continue

        if best_candidate:
            try:
                debug_img = img.copy()
                cv2.rectangle(debug_img,
                              (best_candidate[0] - 20, best_candidate[1] - 20),
                              (best_candidate[0] + 20, best_candidate[1] + 20),
                              (0, 255, 0), 2)
                cv2.imwrite(f"debug_click_bot{bot['id']}.png", debug_img)
            except Exception:
                pass
            return best_candidate

        # ------------------ BACKUP: ORANGE CLOUD ------------------
        print(f"⚠️ [Bot {bot['id']}] Box not found directly, checking Orange Cloud...")
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_orange = np.array([5, 100, 100])
        upper_orange = np.array([30, 255, 255])
        orange_mask = cv2.inRange(hsv, lower_orange, upper_orange)

        cloud_contours, _ = cv2.findContours(orange_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cc in cloud_contours:
            area = cv2.contourArea(cc)
            if 300 < area < 2500:
                cx, cy, cw, ch = cv2.boundingRect(cc)
                # Sirf nichlay hissay mein dhoondo (Y > 400)
                if cx < screen_w * 0.6 and cy > 400:
                    target_box_x = cx - 185
                    target_box_y = cy + ch // 2 + 5
                    print(f"🎯 [Bot {bot['id']}] Located via Orange Cloud! Box: ({target_box_x}, {target_box_y})")
                    return (target_box_x, target_box_y)

        print(f"⚠️ [Bot {bot['id']}] No valid checkbox found.")
        return None

    except Exception as e:
        print(f"❌ [Bot {bot['id']}] Detection error: {e}")
        return None

# ================== CLOUDFLARE HANDLER ==================
def handle_cloudflare(bot, page_text):
    if bot["saved_pos"] is not None:
        # Agar saved position screen ke top par hai (Y < 400), to discard karo
        if bot["saved_pos"][1] < 400:
            print(f"🗑️ [Bot {bot['id']}] Discarding invalid saved pos (Top Area): {bot['saved_pos']}")
            bot["saved_pos"] = None

    # PHASE 1: SAVED POSITION
    if bot["saved_pos"] is not None:
        x, y = bot["saved_pos"]
        print(f"🧠 [Bot {bot['id']}] Using SAVED position: ({x}, {y})")
        time.sleep(1.5)
        if safe_click(bot, x, y):
            time.sleep(6)
            return True

    # PHASE 2: FRESH DETECTION
    print(f"🔍 [Bot {bot['id']}] Detecting fresh position via OpenCV...")

    for attempt in range(8):
        pos = detect_checkbox_position(bot)
        if pos:
            x, y = pos
            print(f"🎯 [Bot {bot['id']}] Target locked: ({x}, {y})")

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
            print(f"⏳ [Bot {bot['id']}] Attempt {attempt+1}: Waiting for widget...")
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
            wait_sec = random.randint(20, 30)
            print(f"⏳ [Bot {bot['id']}] Next refresh in {wait_sec}s...")
            time.sleep(wait_sec)

            if not ensure_cdp(bot):
                time.sleep(5)
                continue

            cmd_id += 1
            print(f"🔄 [Bot {bot['id']}] Refreshing...")
            cdp_command(bot["cdp_ws"], cmd_id, "Page.reload", {"ignoreCache": False})
            cdp_wait_response(bot["cdp_ws"], cmd_id, timeout=15)
            
            # Refresh ke baad thora wait karo taake page load ho jaye
            time.sleep(4)

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

            if ("Performing security verification" in page_text or
                "Verify you are human" in page_text or
                "malicious bots" in page_text):

                print(f"🚨 [Bot {bot['id']}] CLOUDFLARE DETECTED! Waiting 6 seconds for it to fully load...")
                
                # ================== YEH HAI ASAL FIX ==================
                # Captcha load hone ke liye 6 second ka intezar karo
                time.sleep(6) 
                # ======================================================

                handle_cloudflare(bot, page_text)
                time.sleep(6)

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
            time.sleep(5)
            continue

# ================== MAIN ==================
if __name__ == "__main__":
    print("=========================================")
    print("🤖 MULTI-BOT (Edge Automation - Linux Optimized)")
    print(f"📏 Size Filter: {MIN_SIZE}-{MAX_SIZE}px")
    print("🧠 SMART: Square Shape + Verify Text Detection")
    print("🎯 Target Zone: Y > 400 (Nichla Hissa)")
    print("⏳ Wait Time: 6 seconds after CAPTCHA detection")
    print("=========================================")

    idle_thread = threading.Thread(target=keep_screen_alive, daemon=True)
    idle_thread.start()

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
