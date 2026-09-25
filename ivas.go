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
	wsServer  = "ws://127.0.0.1:8080/ivas" // یہاں اپنا سرور ایڈریس لکھو
	targetURL = "https://www.ivasms.com/portal/live/my_sms"
)

// یہ وہ پیجز ہیں جن پر ہم باری باری جائیں گے تاکہ کوکیز زندہ رہیں
var rotateURLs = []string{
	"https://www.ivasms.com/portal",
	"https://www.ivasms.com/portal/sms/received",
	"https://www.ivasms.com/portal/numbers",
}

var wsConn *websocket.Conn

func init() {
	rand.Seed(time.Now().UnixNano())
	if len(os.Args) > 2 {
		edgePort = os.Args[1]
		botID = os.Args[2]
	}
	wsServer = fmt.Sprintf("ws://127.0.0.1:8080/ivas%s", botID)
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
	fmt.Printf("✅ [Bot %s] Connected to WebSocket Server (Port 8080)!\n", botID)

	go func() {
		for {
			_, _, err := wsConn.ReadMessage()
			if err != nil {
				log.Printf("❌ [Bot %s] WS Disconnected. Reconnecting...", botID)
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
			fmt.Printf("📤 [Bot %s] Data forwarded to WS.\n", botID)
		}
	}
}

// ================== مین فنکشن ==================
func main() {
	fmt.Printf("=========================================\n")
	fmt.Printf("🤖 Bot ID: %s | Connecting to Edge on Port: %s\n", botID, edgePort)
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

	// ================== لامحدود لوپ ==================
	for {
		// 1. 40 سے 80 سیکنڈ کا رینڈم وقفہ
		randomSeconds := rand.Intn(41) + 40
		fmt.Printf("⏳ [Bot %s] Waiting %d seconds before next action...\n", botID, randomSeconds)
		time.Sleep(time.Duration(randomSeconds) * time.Second)

		// 2. رینڈملی کوئی اور پیج اوپن کرو (تاکہ یوزر ایکٹو لگے)
		randomURL := rotateURLs[rand.Intn(len(rotateURLs))]
		fmt.Printf("🔄 [Bot %s] Visiting random page: %s\n", botID, randomURL)
		err := chromedp.Run(ctx, chromedp.Navigate(randomURL))
		if err != nil {
			log.Printf("⚠️ [Bot %s] Error on random page: %v", botID, err)
		}

		// 3. 3 سے 7 سیکنڈ رکو
		time.Sleep(time.Duration(rand.Intn(5)+3) * time.Second)

		// 4. واپس اپنے اصل ٹارگٹ پیج پر آ جاؤ
		fmt.Printf("🎯 [Bot %s] Returning to target page...\n", botID)
		err = chromedp.Run(ctx, chromedp.Navigate(targetURL))
		if err != nil {
			log.Printf("❌ [Bot %s] Error returning to target: %v", botID, err)
			continue
		}

		// 5. پیج لوڈ ہونے کا انتظار کرو (5 سیکنڈ)
		time.Sleep(5 * time.Second)

		// 6. پیج سے ڈیٹا نکالو (SMS والا ڈیٹا)
		var pageText string
		err = chromedp.Run(ctx,
			chromedp.Evaluate(`document.body.innerText`, &pageText),
		)
		if err != nil {
			log.Printf("❌ [Bot %s] Error extracting data: %v", botID, err)
			continue
		}

		// 7. ڈیٹا ویب ساکٹ پر بھیج دو (پورٹ 8080 پر)
		sendDataToWS(pageText)
	}
}
