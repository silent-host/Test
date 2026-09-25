package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"os"
	"strings"
	"time"

	"github.com/chromedp/chromedp"
	"github.com/go-vgo/robotgo"
	"github.com/gorilla/websocket"
)

// ================== سیٹنگز ==================
var (
	edgePort  = "9222"
	botID     = "1"
	wsServer  = "ws://127.0.0.1:8080/ivas"
	targetURL = "https://www.ivasms.com/portal/live/my_sms"
)

var wsConn *websocket.Conn

func init() {
	rand.Seed(time.Now().UnixNano())
	if len(os.Args) > 2 {
		edgePort = os.Args[1]
		botID = os.Args[2]
	}
	wsServer = fmt.Sprintf("ws://13.53.136.240:8080/ivas%s", botID)
}

// ================== ویب ساکٹ کنکشن ==================
func connectWS() {
	var err error
	wsConn, _, err = websocket.DefaultDialer.Dial(wsServer, nil)
	if err != nil {
		log.Printf("⚠️ [Bot %s] WS Error: %v. Retrying in 5s...", botID, err)
		time.Sleep(5 * time.Second)
		connectWS()
		return
	}
	fmt.Printf("✅ [Bot %s] Connected to WebSocket Server!\n", botID)

	go func() {
		for {
			_, _, err := wsConn.ReadMessage()
			if err != nil {
				time.Sleep(5 * time.Second)
				connectWS()
				return
			}
		}
	}()
}

// ================== ڈیٹا بھیجنے کا فنکشن ==================
func sendDataToWS(data string) {
	if wsConn != nil {
		payload := map[string]string{
			"botId":     botID,
			"timestamp": time.Now().Format(time.RFC3339),
			"data":      data,
		}
		jsonData, _ := json.Marshal(payload)
		err := wsConn.WriteMessage(websocket.TextMessage, jsonData)
		if err == nil {
			fmt.Printf("📤 [Bot %s] Data sent to WS.\n", botID)
		}
	}
}

// ================== SQUARE BOX DHOONDNE WALA FUNCTION ==================
// Ye function screen ke center area ko scan karta hai aur aisa square box
// dhoondta hai jiske charon taraf dark (grey/black) border ho aur
// andar safed (white) ho. Yehi Cloudflare checkbox ki pehchaan hai.
func findCheckboxByShape() (int, int, bool) {
	// 1. Screen ki size lo
	sw, sh := robotgo.GetScreenSize()

	// 2. Sirf center area scan karo (fast aur safe)
	// Cloudflare ka box hamesha center mein hota hai
	startX := sw / 4
	startY := sh / 4
	scanW := sw / 2
	scanH := sh / 2

	// 3. Screenshot lo us area ka
	img := robotgo.CaptureImg(startX, startY, scanW, scanH)
	if img == nil {
		return 0, 0, false
	}

	bounds := img.Bounds()

	// 4. Har pixel scan karo (2 pixel ke jump se, taake fast ho)
	for y := 15; y < bounds.Max.Y-15; y += 2 {
		for x := 15; x < bounds.Max.X-15; x += 2 {

			// (a) Center WHITE hona chahiye
			cr, cg, cb, _ := img.At(x, y).RGBA()
			if cr < 55000 || cg < 55000 || cb < 55000 {
				continue
			}

			// (b) Left side DARK hona chahiye (12 pixels door)
			lr, lg, lb, _ := img.At(x-12, y).RGBA()
			if lr > 38000 || lg > 38000 || lb > 38000 {
				continue
			}

			// (c) Right side DARK
			rr, rg, rb, _ := img.At(x+12, y).RGBA()
			if rr > 38000 || rg > 38000 || rb > 38000 {
				continue
			}

			// (d) Top side DARK
			tr, tg, tb, _ := img.At(x, y-12).RGBA()
			if tr > 38000 || tg > 38000 || tb > 38000 {
				continue
			}

			// (e) Bottom side DARK
			br, bg, bb, _ := img.At(x, y+12).RGBA()
			if br > 38000 || bg > 38000 || bb > 38000 {
				continue
			}

			// Agar charon taraf dark border hai aur center white hai,
			// to ye 100% checkbox hai!
			return startX + x, startY + y, true
		}
	}

	return 0, 0, false
}

// ================== ROBOTGO SE CLICK KARNA ==================
func clickCheckboxWithRobot(x, y int) {
	fmt.Printf("🖱️ [Bot %s] Checkbox found at (%d, %d). Clicking...\n", botID, x, y)

	// Human ki tarah mouse move karo (pehle thora door, phir target par)
	robotgo.Move(x-20, y-20)
	time.Sleep(time.Duration(rand.Intn(400)+200) * time.Millisecond)
	robotgo.Move(x-5, y-5)
	time.Sleep(time.Duration(rand.Intn(200)+150) * time.Millisecond)
	robotgo.Move(x, y)
	time.Sleep(time.Duration(rand.Intn(200)+150) * time.Millisecond)

	// Asli OS-level click
	robotgo.Click("left")
	fmt.Printf("☑️ [Bot %s] Clicked successfully!\n", botID)

	time.Sleep(5 * time.Second)
}

// ================== مین فنکشن ==================
func main() {
	fmt.Printf("=========================================\n")
	fmt.Printf("🤖 Bot ID: %s | Edge Port: %s\n", botID, edgePort)
	fmt.Printf("🔗 Forwarding to: %s\n", wsServer)
	fmt.Printf("=========================================\n")

	connectWS()

	// ایج براؤزر سے کنیکٹ ہو
	debugURL := fmt.Sprintf("http://localhost:%s", edgePort)
	allocCtx, cancel := chromedp.NewRemoteAllocator(context.Background(), debugURL)
	defer cancel()

	ctx, cancelCtx := chromedp.NewContext(allocCtx)
	defer cancelCtx()

	// پہلی بار ٹارگٹ پیج کھولو
	fmt.Printf("🌐 [Bot %s] Opening initial website...\n", botID)
	err := chromedp.Run(ctx, chromedp.Navigate(targetURL))
	if err != nil {
		log.Fatalf("❌ [Bot %s] Failed to open website: %v", botID, err)
	}

	// ================== MAIN LOOP ==================
	for {
		// 1. رینڈم وقفہ (40 سے 80 سیکنڈ)
		randomSeconds := rand.Intn(41) + 40
		fmt.Printf("⏳ [Bot %s] Waiting %d seconds...\n", botID, randomSeconds)
		time.Sleep(time.Duration(randomSeconds) * time.Second)

		// 2. پیج ریفریش کرو
		fmt.Printf("🔄 [Bot %s] Refreshing...\n", botID)
		err := chromedp.Run(ctx, chromedp.Reload())
		if err != nil {
			log.Printf("❌ [Bot %s] Refresh error: %v", botID, err)
			continue
		}

		// 3. پیج لوڈ ہونے کا انتظار
		time.Sleep(6 * time.Second)

		// 4. پیج کا ٹیکسٹ نکالو
		var pageText string
		err = chromedp.Run(ctx,
			chromedp.Evaluate(`document.body.innerText`, &pageText),
		)
		if err != nil {
			log.Printf("❌ [Bot %s] Error extracting data: %v", botID, err)
			continue
		}

		// 5. Cloudflare detect karo (text se)
		if strings.Contains(pageText, "Performing security verification") ||
			strings.Contains(pageText, "Verify you are human") ||
			strings.Contains(pageText, "malicious bots") {

			fmt.Printf("🚨 [Bot %s] CLOUDFLARE DETECTED! Scanning screen for checkbox...\n", botID)

			// 6. Screen par square box dhoondo (RobotGo se)
			cfX, cfY, found := findCheckboxByShape()
			if found {
				clickCheckboxWithRobot(cfX, cfY)

				// Click ke baad 8 second wait karo, phir dobara text check karo
				time.Sleep(8 * time.Second)
				chromedp.Run(ctx, chromedp.Evaluate(`document.body.innerText`, &pageText))
			} else {
				fmt.Printf("⚠️ [Bot %s] Checkbox not found on screen. Retrying next cycle.\n", botID)
			}
		} else {
			fmt.Printf("✅ [Bot %s] No CAPTCHA. Page is clean.\n", botID)
		}

		// 7. ڈیٹا ویب ساکٹ پر بھیج دو
		sendDataToWS(pageText)
	}
}
