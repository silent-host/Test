package main

import (
	"fmt"
	"log"
	"net/http"
	"sync"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// تمام ایکٹو کلائنٹس کا پول (Channel Pool)
type ClientHub struct {
	clients map[*websocket.Conn]bool
	mu      sync.Mutex
}

var hubMap = make(map[string]*ClientHub)
var hubMu sync.Mutex

func getHub(path string) *ClientHub {
	hubMu.Lock()
	defer hubMu.Unlock()
	if hubMap[path] == nil {
		hubMap[path] = &ClientHub{
			clients: make(map[*websocket.Conn]bool),
		}
	}
	return hubMap[path]
}

func main() {
	http.HandleFunc("/ivas", handleConnection)
	http.HandleFunc("/ivas1", handleConnection)
	http.HandleFunc("/ivas2", handleConnection)
	http.HandleFunc("/ivas3", handleConnection)

	fmt.Println("🚀 WebSocket Broadcast Hub started on ws://0.0.0.0:8080")
	fmt.Println("Waiting for bots and forwarders...")

	err := http.ListenAndServe("0.0.0.0:8080", nil)
	if err != nil {
		log.Fatal("❌ Server failed to start: ", err)
	}
}

func handleConnection(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Println("❌ Upgrade error:", err)
		return
	}
	defer conn.Close()

	hub := getHub(r.URL.Path)
	hub.mu.Lock()
	hub.clients[conn] = true
	hub.mu.Unlock()

	fmt.Printf("✅ Bot/Client connected: %s (Active on path: %d)\n", r.URL.Path, len(hub.clients))

	defer func() {
		hub.mu.Lock()
		delete(hub.clients, conn)
		hub.mu.Unlock()
		fmt.Printf("❌ Connection closed: %s\n", r.URL.Path)
	}()

	for {
		msgType, msg, err := conn.ReadMessage()
		if err != nil {
			break
		}

		msgStr := string(msg)
		fmt.Printf("\n📩 Data received from [%s]:\n%s\n", r.URL.Path, msgStr)

		// 🟢 براڈکاسٹ: جو میسج آیا ہے وہ اسی پاتھ پر جڑے باقی تمام کلائنٹس (ٹیلیگرام بوٹ) کو فارورڈ کرو
		hub.mu.Lock()
		for client := range hub.clients {
			if client != conn { // خود بھیجنے والے کو واپس نہ بھیجو
				errSend := client.WriteMessage(msgType, msg)
				if errSend != nil {
					log.Printf("⚠️ Failed to forward to a client: %v", errSend)
				} else {
					fmt.Printf("📤 Forwarded frame to Telegram Bot on [%s]\n", r.URL.Path)
				}
			}
		}
		hub.mu.Unlock()
	}
}
