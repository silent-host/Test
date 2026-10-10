package main

import (
	"fmt"
	"log"
	"net/http"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

func main() {
	// Register WebSocket route handlers
	http.HandleFunc("/ivas", handleConnection)
	http.HandleFunc("/ivas1", handleConnection)
	http.HandleFunc("/ivas2", handleConnection)
	http.HandleFunc("/ivas3", handleConnection)

	fmt.Println("🚀 WebSocket Server started on ws://0.0.0.0:8080")
	fmt.Println("Waiting for incoming bot connections...")

	// Listen on all network interfaces so external traffic is accepted
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

	fmt.Printf("✅ Bot connected: %s\n", r.URL.Path)

	for {
		_, msg, err := conn.ReadMessage()
		if err != nil {
			fmt.Printf("❌ Connection closed: %s\n", r.URL.Path)
			break
		}
		// Log incoming payload from connected bot
		fmt.Printf("\n📩 Data received from [%s]:\n%s\n", r.URL.Path, string(msg))
	}
}
