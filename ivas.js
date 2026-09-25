package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"os"
	"time"

	"github.com/chromedp/chromedp"
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
	// یہاں اپنا پبلک آئی پی لگا لو اگر باہر سے دیکھنا ہے
	wsServer = fmt.Sprintf("ws://13.53.136.240:8080/ivas%s", botID)
}

// ================== ویب ساکٹ ==================
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

func sendDataToWS(data string) {
	if wsConn != nil {
		payload := map[string]string{
			"botId":     botID,
			"timestamp": time.Now().Format(time.RFC3339),
			"data":      data,
		}
		jsonData, _ := json.Marshal(payload)
		wsConn.WriteMessage(websocket.TextMessage, jsonData)
		fmt.Printf("📤 [Bot %s] Data sent to WS.\n", botID)
	}
}

// ================== کلاؤڈ فلیر پر انسان کی طرح کلک ==================
func handleCloudflare(ctx context.Context) {
	// 1. کلاؤڈ فلیر کے iframe کا پتہ لگاؤ
	var box map[string]float64
	err := chromedp.Run(ctx,
		chromedp.Evaluate(`(() => {
			const iframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
			if (iframe) {
				const rect = iframe.getBoundingClientRect();
				return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
			}
			return null;
		})()`, &box),
	)

	if err != nil || box == nil || box["width"] == 0 {
		fmt.Printf("ℹ️ [Bot %s] No Cloudflare checkbox found.\n", botID)
		return
	}

	// 2. چیک باکس کا حساب لگاؤ (ویریفائی ٹیکسٹ کے بائیں طرف)
	// عام طور پر باکس iframe کے اندر بائیں طرف 30 پکسل کے فاصلے پر ہوتا ہے
	clickX := box["x"] + 30
	clickY := box["y"] + 30

	fmt.Printf("🖱️ [Bot %s] Cloudflare detected! Clicking at X:%.0f Y:%.0f...\n", botID, clickX, clickY)

	// 3. ماؤس کو انسان کی طرح حرکت دے کر کلک کرو
	err = chromedp.Run(ctx,
		// پہلے ماؤس کو تھوڑا اوپر لے جاؤ (جیسے انسان کرتا ہے)
		chromedp.MouseMove(clickX-15, clickY-15),
		chromedp.Sleep(time.Duration(rand.Intn(500)+300)*time.Millisecond),
		// پھر ہدف پر لے جاؤ
		chromedp.MouseMove(clickX, clickY),
		chromedp.Sleep(time.Duration(rand.Intn(300)+200)*time.Millisecond),
		// اور کلک کرو
		chromedp.MouseClickXY(clickX, clickY),
	)
	if err != nil {
		fmt.Printf("❌ [Bot %s] Error clicking checkbox: %v\n", botID, err)
	} else {
		fmt.Printf("☑️ [Bot %s] Checkbox clicked. Waiting for verification...\n", botID)
	}

	// کلک کے بعد انتظار کرو تاکہ تصدیق ہو جائے
	time.Sleep(5 * time.Second)
}

// ================== مین فنکشن ==================
func main() {
	fmt.Printf("=========================================\n")
	fmt.Printf("🤖 Bot ID: %s | Edge Port: %s\n", botID, edgePort)
	fmt.Printf("🔗 Forwarding to: %s\n", wsServer)
	fmt.Printf("=========================================\n")

	connectWS()

	// ایج سے کنیکٹ ہو
	debugURL := fmt.Sprintf("http://localhost:%s", edgePort)
	allocCtx, cancel := chromedp.NewRemoteAllocator(context.Background(), debugURL)
	defer cancel()

	ctx, cancelCtx := chromedp.NewContext(allocCtx)
	defer cancelCtx()

	// پہلی بار پیج کھولو
	fmt.Printf("🌐 [Bot %s] Opening website...\n", botID)
	err := chromedp.Run(ctx, chromedp.Navigate(targetURL))
	if err != nil {
		log.Fatalf("❌ [Bot %s] Failed to open website: %v", botID, err)
	}

	// ================== صرف ریفریش والا لوپ ==================
	for {
		// 1. کلاؤڈ فلیر چیک کرو (اگر آیا ہو تو کلک کرو)
		handleCloudflare(ctx)

		// 2. رینڈم وقفہ (40 سے 80 سیکنڈ)
		randomSeconds := rand.Intn(41) + 40
		fmt.Printf("⏳ [Bot %s] Waiting %d seconds before next refresh...\n", botID, randomSeconds)
		time.Sleep(time.Duration(randomSeconds) * time.Second)

		// 3. صرف ریفریش کرو (پیج روٹیشن ہٹا دی ہے)
		fmt.Printf("🔄 [Bot %s] Refreshing target page...\n", botID)
		err := chromedp.Run(ctx, chromedp.Reload())
		if err != nil {
			log.Printf("❌ [Bot %s] Refresh error: %v", botID, err)
			continue
		}

		// 4. پیج لوڈ ہونے کا انتظار کرو
		time.Sleep(5 * time.Second)

		// 5. ریفریش کے بعد ڈیٹا نکالو اور بھیجو
		var pageText string
		err = chromedp.Run(ctx,
			chromedp.Evaluate(`document.body.innerText`, &pageText),
		)
		if err == nil {
			sendDataToWS(pageText)
		}
	}
}
