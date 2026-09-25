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
	// اپنا پبلک آئی پی یہاں لگا لو
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

	// ================== صرف ریفریش اور ڈیٹا والا لوپ ==================
	for {
		// 1. رینڈم وقفہ (40 سے 80 سیکنڈ)
		randomSeconds := rand.Intn(41) + 40
		fmt.Printf("⏳ [Bot %s] Waiting %d seconds before next refresh...\n", botID, randomSeconds)
		time.Sleep(time.Duration(randomSeconds) * time.Second)

		// 2. صرف ریفریش کرو
		fmt.Printf("🔄 [Bot %s] Refreshing target page...\n", botID)
		err := chromedp.Run(ctx, chromedp.Reload())
		if err != nil {
			log.Printf("❌ [Bot %s] Refresh error: %v", botID, err)
			continue
		}

		// 3. پیج لوڈ ہونے کا انتظار کرو (10 سیکنڈ)
		// یہ وقت AutoHotkey کو دیا جا رہا ہے تاکہ وہ کلاؤڈ فلیر پر کلک کر سکے
		fmt.Printf("⏳ [Bot %s] Waiting for page to load (and AHK to click)...\n", botID)
		time.Sleep(10 * time.Second)

		// 4. پیج سے ڈیٹا نکالو
		var pageText string
		err = chromedp.Run(ctx,
			chromedp.Evaluate(`document.body.innerText`, &pageText),
		)
		if err != nil {
			log.Printf("❌ [Bot %s] Error extracting data: %v", botID, err)
			continue
		}

		// 5. ڈیٹا ویب ساکٹ پر بھیج دو
		sendDataToWS(pageText)
	}
}
