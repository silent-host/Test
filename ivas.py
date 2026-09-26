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

# 🧠 Learned size (pichli successful click ka size)
learned_size = None
SIZE_TOLERANCE = 5  # pixels ka farq allow karo

ws_client = None
cdp_ws = None

# ================== WEBSOCKET ==================
def connect_to_server():
    global ws_client
    try:
        ws_client = websocket.create_connection(WS_SERVER, timeout=10)
        print(f"✅ [Bot {BOT_ID}] Connected to WebSocket Server ({WS_SERVER})!")
        return True
    except Exception as e:
        print(f"⚠️ [Bot {BOT_ID}] WS Error: {e}. Retrying in 5s...")
        return False

def send_data_to_server(data):
    global ws_client
    try:
        if ws_client is None:
            if not connect_to_server():
                return
        payload = {
            "botId": BOT_ID,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data": data
        }
        ws_client.send(json.dumps(payload))
        print(f"📤 [Bot {BOT_ID}] Data sent to server.")
    except Exception as e:
        print(f"❌ [Bot {BOT_ID}] Send error: {e}. Reconnecting...")
        ws_client = None
        connect_to_server()

# ================== EDGE CDP ==================
def get_cdp_target():
    try:
        r = requests.get(f"http://127.0.0.1:{EDGE_PORT}/json", timeout=5)
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
    try:
        msg = {"id": cmd_id, "method": method}
        if params:
            msg["params"] = params
        ws.send(json.dumps(msg))
    except Exception as e:
        print(f"⚠️ [Bot {BOT_ID}] CDP send failed: {e}")

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

def ensure_cdp():
    global cdp_ws
    try:
        if cdp_ws is not None:
            try:
                cdp_ws.settimeout(2)
                cmd_id = random.randint(10000, 99999)
                cdp_command(cdp_ws, cmd_id, "Runtime.evaluate", {
                    "expression": "1+1", "returnByValue": True
                })
                resp = cdp_wait_response(cdp_ws, cmd_id, timeout=3)
                if resp is not None:
                    return True
            except:
                pass

        print(f"🔗 [Bot {BOT_ID}] (Re)connecting to Edge CDP...")
        cdp_url = get_cdp_target()
        if not cdp_url:
            print(f"❌ [Bot {BOT_ID}] No target tab found.")
            return False
        cdp_ws = websocket.create_connection(cdp_url, timeout=10, suppress_origin=True)
        print(f"✅ [Bot {BOT_ID}] CDP Connected!")
        return True
    except Exception as e:
        print(f"❌ [Bot {BOT_ID}] CDP connect failed: {e}")
        cdp_ws = None
        return False

# ================== SCREEN WAKE-UP ==================
def wake_screen_and_retry():
    print(f"💡 [Bot {BOT_ID}] Trying to wake screen by clicking center...")
    try:
        sw, sh = pyautogui.size()
        center_x = sw // 2
        center_y = sh // 2
        try:
            pyautogui.moveTo(center_x, center_y, duration=0.2)
            time.sleep(0.2)
            pyautogui.click()
            print(f"🖱️ [Bot {BOT_ID}] Clicked center ({center_x}, {center_y})")
        except Exception as e:
            print(f"⚠️ [Bot {BOT_ID}] Click failed: {e}")

        time.sleep(3)
        try:
            screenshot = pyautogui.screenshot()
            img = np.array(screenshot)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            print(f"✅ [Bot {BOT_ID}] Screen is awake!")
            return img
        except Exception as e:
            print(f"⚠️ [Bot {BOT_ID}] Still no screenshot: {e}")
            return None
    except Exception as e:
        print(f"❌ [Bot {BOT_ID}] Wake-up failed: {e}")
        return None

# ================== OPENCV: FULL SCREEN - LARGEST OR SAME SIZE ==================
def find_and_click_checkbox():
    global learned_size

    # ================== SCREENSHOT WITH RETRY ==================
    img = None
    for attempt in range(3):
        try:
            screenshot = pyautogui.screenshot()
            img = np.array(screenshot)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            break
        except Exception as e:
            print(f"⚠️ [Bot {BOT_ID}] Screenshot attempt {attempt+1} failed: {e}")
            if attempt < 2:
                img = wake_screen_and_retry()
                if img is not None:
                    break

    if img is None:
        print(f"❌ [Bot {BOT_ID}] Could not get screenshot after 3 tries.")
        return False

    # ================== DETECTION LOGIC ==================
    try:
        screen_h, screen_w = img.shape[:2]
        print(f"🔍 [Bot {BOT_ID}] Scanning FULL screen ({screen_w}x{screen_h})...")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []

        for cnt in contours:
            try:
                area = cv2.contourArea(cnt)
                # Square checkbox area 200-2000 pixels
                if 200 < area < 2000:
                    peri = cv2.arcLength(cnt, True)
                    approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)

                    if len(approx) == 4:
                        x, y, w, h = cv2.boundingRect(approx)
                        # Size 15-60 pixels
                        if 15 <= w <= 60 and 15 <= h <= 60:
                            aspect_ratio = float(w) / h
                            # Square check
                            if 0.85 <= aspect_ratio <= 1.15:
                                cx = x + w // 2
                                cy = y + h // 2
                                # Andar white color
                                center_color = img[cy, cx]
                                if (center_color[0] > 200 and
                                    center_color[1] > 200 and
                                    center_color[2] > 200):
                                    candidates.append({
                                        "x": cx, "y": cy,
                                        "w": w, "h": h,
                                        "area": w * h
                                    })
            except Exception:
                continue

        if not candidates:
            print(f"⚠️ [Bot {BOT_ID}] No square found on screen.")
            return False

        # ================== FILTER BY LEARNED SIZE ==================
        best = None

        if learned_size is not None:
            # 🧠 Pichli baar ka size pata hai - usi size ka dhoondo
            print(f"🧠 [Bot {BOT_ID}] Learned size: {learned_size}x{learned_size} (±{SIZE_TOLERANCE})")
            matching = []
            for c in candidates:
                if (abs(c["w"] - learned_size) <= SIZE_TOLERANCE and
                    abs(c["h"] - learned_size) <= SIZE_TOLERANCE):
                    matching.append(c)

            if matching:
                # Multiple matching ho sakte - largest pick karo
                matching.sort(key=lambda c: c["area"], reverse=True)
                best = matching[0]
                print(f"✅ [Bot {BOT_ID}] Found {len(matching)} candidates matching learned size")
            else:
                print(f"⚠️ [Bot {BOT_ID}] No candidate matches learned size. Falling back to largest.")
                # Fallback: largest pick karo
                candidates.sort(key=lambda c: c["area"], reverse=True)
                best = candidates[0]
        else:
            # 🎯 Pehli baar: sab se bara square pick karo
            print(f"🎯 [Bot {BOT_ID}] First time: {len(candidates)} squares found. Picking LARGEST.")
            candidates.sort(key=lambda c: c["area"], reverse=True)
            best = candidates[0]

            # Print top 5 for debugging
            for i, c in enumerate(candidates[:5]):
                print(f"   #{i+1}: size={c['w']}x{c['h']} area={c['area']} pos=({c['x']},{c['y']})")

        # ================== CLICK ==================
        print(f"🎯 [Bot {BOT_ID}] CLICKING: ({best['x']}, {best['y']}) size={best['w']}x{best['h']}")

        # Debug image
        try:
            debug_img = img.copy()
            # Best (green)
            cv2.rectangle(debug_img,
                          (best["x"]-best["w"]//2, best["y"]-best["h"]//2),
                          (best["x"]+best["w"]//2, best["y"]+best["h"]//2),
                          (0, 255, 0), 3)
            # Other candidates (blue)
            for c in candidates:
                if c != best:
                    cv2.rectangle(debug_img,
                                  (c["x"]-c["w"]//2, c["y"]-c["h"]//2),
                                  (c["x"]+c["w"]//2, c["y"]+c["h"]//2),
                                  (255, 0, 0), 1)
            cv2.imwrite("debug_click.png", debug_img)
        except: pass

        # Human-like click
        cx, cy = best["x"], best["y"]
        try:
            pyautogui.moveTo(cx - 15, cy - 15, duration=0.3)
            time.sleep(random.uniform(0.15, 0.4))
            pyautogui.moveTo(cx, cy, duration=0.2)
            time.sleep(random.uniform(0.1, 0.3))
            pyautogui.click()
            print(f"☑️ [Bot {BOT_ID}] Clicked!")
        except Exception as e:
            print(f"❌ [Bot {BOT_ID}] Click failed: {e}")
            return False

        # 🧠 LEARN: Size save karo (agar pehli baar ho ya different ho)
        if learned_size is None:
            learned_size = best["w"]
            print(f"🧠 [Bot {BOT_ID}] Learned checkbox size: {learned_size}x{learned_size}")
        elif abs(best["w"] - learned_size) > SIZE_TOLERANCE:
            # Naya size mila, update karo
            learned_size = best["w"]
            print(f"🧠 [Bot {BOT_ID}] Updated learned size: {learned_size}x{learned_size}")

        time.sleep(5)
        return True

    except Exception as e:
        print(f"❌ [Bot {BOT_ID}] Detection error: {e}")
        return False

# ================== MAIN LOOP ==================
def start_bot():
    connect_to_server()

    if not ensure_cdp():
        print(f"❌ [Bot {BOT_ID}] Cannot connect to Edge. Retrying in 10s...")
        time.sleep(10)
        return

    cmd_id = 1
    cdp_command(cdp_ws, cmd_id, "Page.navigate", {"url": TARGET_URL})
    cdp_wait_response(cdp_ws, cmd_id, timeout=10)
    print(f"🌐 [Bot {BOT_ID}] Page opened.")

    while True:
        try:
            wait_sec = random.randint(40, 80)
            print(f"⏳ [Bot {BOT_ID}] Next refresh in {wait_sec} seconds...")
            time.sleep(wait_sec)

            if not ensure_cdp():
                print(f"⚠️ [Bot {BOT_ID}] CDP not available. Retrying...")
                time.sleep(10)
                continue

            cmd_id += 1
            print(f"🔄 [Bot {BOT_ID}] Refreshing...")
            cdp_command(cdp_ws, cmd_id, "Page.reload", {"ignoreCache": False})
            cdp_wait_response(cdp_ws, cmd_id, timeout=15)

            time.sleep(6)

            # Text nikalo
            page_text = ""
            try:
                cmd_id += 1
                cdp_command(cdp_ws, cmd_id, "Runtime.evaluate", {
                    "expression": "document.body.innerText",
                    "returnByValue": True
                })
                response = cdp_wait_response(cdp_ws, cmd_id, timeout=10)
                if response and "result" in response:
                    result = response["result"].get("result", {})
                    page_text = result.get("value", "")
            except Exception as e:
                print(f"⚠️ [Bot {BOT_ID}] Text extract error: {e}")

            # Cloudflare detect
            if ("Performing security verification" in page_text or
                "Verify you are human" in page_text or
                "malicious bots" in page_text):

                print(f"🚨 [Bot {BOT_ID}] CLOUDFLARE DETECTED!")

                for attempt in range(5):
                    try:
                        if find_and_click_checkbox():
                            break
                    except Exception as e:
                        print(f"⚠️ [Bot {BOT_ID}] Click attempt error: {e}")
                    time.sleep(3)

                time.sleep(10)

                try:
                    cmd_id += 1
                    cdp_command(cdp_ws, cmd_id, "Runtime.evaluate", {
                        "expression": "document.body.innerText",
                        "returnByValue": True
                    })
                    response = cdp_wait_response(cdp_ws, cmd_id, timeout=10)
                    if response and "result" in response:
                        result = response["result"].get("result", {})
                        page_text = result.get("value", "")
                except:
                    pass
            else:
                print(f"✅ [Bot {BOT_ID}] No CAPTCHA.")

            send_data_to_server(page_text)

        except KeyboardInterrupt:
            print(f"\n🛑 [Bot {BOT_ID}] Stopped by user.")
            break
        except Exception as e:
            print(f"❌ [Bot {BOT_ID}] Unexpected error: {e}")
            print(f"⏳ [Bot {BOT_ID}] Waiting 10s before retry...")
            time.sleep(10)
            continue


if __name__ == "__main__":
    print("=========================================")
    print(f"🤖 Python Bot ID: {BOT_ID}")
    print(f"🔗 Forwarding to: {WS_SERVER}")
    print("🛡️ Crash-Proof Mode Enabled")
    print("🧠 Smart Size Learning (Largest First)")
    print("=========================================")

    while True:
        try:
            start_bot()
        except KeyboardInterrupt:
            print("\n🛑 Stopped by user.")
            break
        except Exception as e:
            print(f"❌ [Bot {BOT_ID}] Fatal error: {e}")
            print(f"🔄 Restarting in 15s...")
            time.sleep(15)
            continue
