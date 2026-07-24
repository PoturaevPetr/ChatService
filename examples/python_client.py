"""
Пример клиента на Python для ChatService

Демонстрирует:
- Регистрацию пользователя
- Шифрование сообщений
- Отправку через REST
- Получение через WebSocket
"""

import requests
import websocket
import json
import uuid
import threading
import time

from Crypto.PublicKey import RSA
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Random import get_random_bytes
import base64


class ChatClient:
    """Клиент для ChatService"""

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.access_token = None
        self.refresh_token = None
        self.user_id = None
        self.private_key = None
        self.public_key = None

    def register(self, username: str, service_id: str) -> dict:
        """Регистрация: клиент генерирует RSA-пару и шлёт только public_key."""
        key = RSA.generate(2048)
        self.private_key = key.export_key().decode("utf-8")
        self.public_key = key.publickey().export_key().decode("utf-8")

        response = requests.post(
            f"{self.base_url}/api/v1/auth/register",
            json={
                "username": username,
                "service_id": service_id,
                "password": "example-pass-ChangeMe1!",
                "public_key": self.public_key,
            },
        )
        response.raise_for_status()
        data = response.json()

        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.user_id = uuid.UUID(data["user_id"])
        # Сервер не возвращает private_key
        assert data.get("private_key") in (None, ""), "server must not return private_key"

        print(f"✅ Registered: {self.user_id} ({username})")
        return data

    def get_headers(self) -> dict:
        """Получить заголовки с токеном авторизации"""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def get_user_public_key(self, user_id: uuid.UUID) -> str:
        """Получить публичный ключ пользователя"""
        response = requests.get(
            f"{self.base_url}/api/v1/keys/public/{user_id}",
            headers=self.get_headers()
        )
        response.raise_for_status()
        data = response.json()
        return data["public_key"]

    def encrypt_message_e2e(
        self,
        message: dict,
        member_public_keys: dict,
    ) -> dict:
        """
        Клиентский E2E: одно AES-тело + RSA-обёртка ключа для каждого участника.
        member_public_keys: { user_id_str: pem_public_key }
        """
        message_json = json.dumps(message).encode("utf-8")
        aes_key = get_random_bytes(32)
        nonce = get_random_bytes(12)
        aes_cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
        encrypted_data, tag = aes_cipher.encrypt_and_digest(message_json)
        encrypted_with_tag = encrypted_data + tag

        recipient_keys = []
        for uid, pem in member_public_keys.items():
            rsa_cipher = PKCS1_OAEP.new(RSA.import_key(pem))
            encrypted_aes_key = rsa_cipher.encrypt(aes_key)
            recipient_keys.append(
                {
                    "user_id": str(uid),
                    "encrypted_aes_key": base64.b64encode(encrypted_aes_key).decode("utf-8"),
                }
            )

        return {
            "encrypted_data": base64.b64encode(encrypted_with_tag).decode("utf-8"),
            "nonce": base64.b64encode(nonce).decode("utf-8"),
            "recipient_keys": recipient_keys,
            "signature": None,
        }

    def decrypt_message(self, encrypted: dict) -> dict:
        """Расшифровать сообщение"""
        encrypted_data = base64.b64decode(encrypted["encrypted_data"])
        encrypted_aes_key = base64.b64decode(encrypted["encrypted_aes_key"])
        nonce = base64.b64decode(encrypted["nonce"])

        private_key = RSA.import_key(self.private_key)
        rsa_cipher = PKCS1_OAEP.new(private_key)
        aes_key = rsa_cipher.decrypt(encrypted_aes_key)

        aes_cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
        decrypted_data = aes_cipher.decrypt_and_verify(
            encrypted_data[:-16],
            encrypted_data[-16:],
        )

        return json.loads(decrypted_data.decode("utf-8"))

    def send_message(self, recipient_id: uuid.UUID, message: dict) -> dict:
        """Отправить E2E-сообщение (шифрование на клиенте)."""
        recipient_public_key = self.get_user_public_key(recipient_id)
        member_keys = {
            str(self.user_id): self.public_key,
            str(recipient_id): recipient_public_key,
        }
        e2e = self.encrypt_message_e2e(message, member_keys)

        response = requests.post(
            f"{self.base_url}/api/v1/messages/",
            headers=self.get_headers(),
            json={
                "recipient_id": str(recipient_id),
                "e2e": e2e,
            },
        )
        response.raise_for_status()
        return response.json()

    def get_messages(self, unread_only: bool = False) -> list:
        """Получить сообщения"""
        endpoint = "/api/v1/messages/unread" if unread_only else "/api/v1/messages/"
        response = requests.get(
            f"{self.base_url}{endpoint}",
            headers=self.get_headers()
        )
        response.raise_for_status()
        return response.json()

    def start_websocket(self, on_message_callback):
        """Запустить WebSocket соединение"""
        ws_url = f"ws://localhost:8080/ws/{self.user_id}?token={self.access_token}"

        def on_message(ws, message):
            data = json.loads(message)
            print(f"📨 WebSocket received: {data['type']}")
            on_message_callback(data)

        def on_error(ws, error):
            print(f"❌ WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            print("🔌 WebSocket closed")

        def on_open(ws):
            print("✅ WebSocket connected")
            # Отправляем ping
            ws.send(json.dumps({"type": "ping"}))

        ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )

        # Запускаем в отдельном потоке
        ws_thread = threading.Thread(target=ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()

        return ws


# Пример использования
if __name__ == "__main__":
    # Регистрируем двух пользователей
    client1 = ChatClient()
    client1.register("john_doe", "service_a")

    client2 = ChatClient()
    client2.register("jane_smith", "service_a")

    # Client1 отправляет сообщение client2
    print("\n📤 Sending message...")
    client1.send_message(
        recipient_id=client2.user_id,
        message={"text": "Hello from Client1!", "timestamp": time.time()}
    )

    # Client2 получает сообщения
    print("\n📥 Getting messages...")
    messages = client2.get_messages()
    for msg in messages:
        print(f"Message from {msg['sender_id']}: {msg}")

    # Client2 запускает WebSocket для real-time получения
    print("\n🔌 Starting WebSocket for Client2...")

    def on_new_message(data):
        if data["type"] == "new_message":
            print(f"🔔 New message notification: {data}")

    client2.start_websocket(on_new_message)

    # Client1 отправляет еще одно сообщение
    time.sleep(1)
    client1.send_message(
        recipient_id=client2.user_id,
        message={"text": "Real-time message!", "timestamp": time.time()}
    )

    # Держим WebSocket открытым
    print("\n⏳ Keeping WebSocket open for 5 seconds...")
    time.sleep(5)

    print("\n✅ Example completed!")
