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
	// پورٹ 8080 پر سرور چالو کرو
	http.HandleFunc("/ivas", handleConnection)
	http.HandleFunc("/ivas1", handleConnection)
	http.HandleFunc("/ivas2", handleConnection)
	http.HandleFunc("/ivas3", handleConnection)

	fmt.Println("🚀 WebSocket Server started on ws://127.0.0.1:8080")
	fmt.Println("اب بوٹ چلاؤ...")

	err := http.ListenAndServe("127.0.0.1:8080", nil)
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

	fmt.Printf("✅ نیا بوٹ کنیکٹ ہو گیا: %s\n", r.URL.Path)

	for {
		_, msg, err := conn.ReadMessage()
		if err != nil {
			fmt.Printf("❌ کنکشن بند ہو گیا: %s\n", r.URL.Path)
			break
		}
		// یہاں تمہیں بوٹ سے ڈیٹا ملے گا
		fmt.Printf("\n📩 [%s] سے ڈیٹا آیا:\n%s\n", r.URL.Path, string(msg))
	}
}
