"""
Модуль создания и обновления тестовых пользователей (test_alice и test_bob)
с предустановленными Zero-Knowledge бэкапами ключей и общей комнатой для мгновенного тестирования.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.orm import Session

from server.auth.jwt_handler import jwt_handler
from server.database.Devices import Devices
from server.database.MessageDeviceKeys import MessageDeviceKeys
from server.database.MessageRecipientKeys import MessageRecipientKeys
from server.database.Messages import Messages
from server.database.RoomUsers import RoomUsers
from server.database.Rooms import Rooms
from server.database.UserKeyBackups import UserKeyBackups
from server.database.Users import Users

logger = logging.getLogger(__name__)

ALICE_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCbmLOkUNPipZYC
3NI2LH5qTCd1zx1On7bz1Scc5OzMIR0HHG+kSEJ4sMDxOdNqAFJ/Dh6vmvWuXqJB
zyfbc2tLukL4YatoFKUxtzOTMFDpFrCCLcvXk5g+DeWCl+nnao03zOYBfbuseRcP
o9xivIQE3l/YT/W8AzVrHSgeIAcmy+0e5sVTA7W1dLsBeb7pfTqUBEzylTCDzg4a
pcMPRHHkWSBy6Y3SgkNglhZ4m+3mWjb9VyXIs7rGlygk6fEXEGEgfwuU0h5h8gz4
GNd61doEuYppNuc8xCXD5ASadMKVJIPJvCMYBGFw2IxkczYj8ibobrV2aIurDaMJ
gnFhNkvnAgMBAAECggEAIndHy60P0lOlkArEEbX3Zqppz0HKlyDv0ME1gcP/5BOt
r2aQIE7VUpCsnIKXnxJlM7m3+GQV6cMSpAs0I/tEGCkxLn3MDykLkqCnLwJz2b3p
6VwlnCIYhh5j6XKnIFjM4UBk7o2gZcsI3bEJX2GsyLtNdcf4geYgDhMOUOX9T41i
EbIG7GYrw/v9H9x9QIth4vo1BV3xg0JBc/pPcNQjWnkY1ssSikgr3cPPdzq8Xxfj
j37c+Txv/FkrDW4mbbLxyKvDOPcdm93t/NIhlBjEU69CjZVk8gwC9VwJseXFPdbx
p1zDgkN7HnXFCUyrFC8aXLAHI5hp681a4/tRGchWSQKBgQDK3C1SVNTKLWp8dfkB
eIE9Ql5ySObI08ziLhYybjkpb1ahZN2aRdMAvLFq+OFRcvGE9NwVSvM+JdxzjeyL
0bzxMVKKgj3Nq31E4koPT1440/rJiUM3hQCLpQCBwvC6cHvYi8ATk3sI+Iz0JDCR
3FgiAnQVs7fE2GBPmnyYXkUw2wKBgQDEWwXmxgQHsOLGwaXJv+e4SoodeEUhE076
5WNCfPioZUWXDq7e4CvhdSZfOqIovHtS1dg4HTsmAs9HHzZ2m7FwMBywG8vWEKou
cLGgAxQFxQX1E2ABezC5ZdCSGMpbEUZ4qTZu3fGPCDZfJjgo/+EBiKsB4q/5V4xR
zizIgPxI5QKBgCRwQEPVsRNP7RzGJCA7gRt73HMy3SGdyeOm253bZrEmqqz67UNU
3332ZvgMFI0I1JFJWm8Is4CqVFr9V0wWNJYugeEXW/qhnzLMYvk1DHuwuA+TdFt4
rIxo6xpj5dHXeqd/EtVxXFxUKR2BkqfgqIQTZL6xNYVKSKKD4XWNGWiZAoGAYzmU
K+BY3QIYN1RYUTF3CXwxe17xoBs/yC3vEQRSK9axafpziBFEW3R15Z2doHRO5bdG
wmSTJUw6LripLxrSedz2QlBpm01kkn9EY5XqolfEAOq/k0ALiUTYN1vrtkVulT79
UN07WopN35tSufVEYSANOrCxOJFzSUuk+dWkp7kCgYEAvhMILUE3mznch0hinzCP
fNu5Q+PdDerppUmBH81Kqi/1hQ45RWfc2gPTnGDk6/lkMgUTfxKA7Qjp+C7Y4hlz
FsUUnUteooPJ6vEsXu/I6hfL3w8Cw+ut1oYIbWn3InfgOT4/958VKCHkwnSDlIH7
41MEZDI0w2QigpBrIky0QH8=
-----END PRIVATE KEY-----""".strip()

ALICE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAm5izpFDT4qWWAtzSNix+
akwndc8dTp+289UnHOTszCEdBxxvpEhCeLDA8TnTagBSfw4er5r1rl6iQc8n23Nr
S7pC+GGraBSlMbczkzBQ6Rawgi3L15OYPg3lgpfp52qNN8zmAX27rHkXD6PcYryE
BN5f2E/1vAM1ax0oHiAHJsvtHubFUwO1tXS7AXm+6X06lARM8pUwg84OGqXDD0Rx
5FkgcumN0oJDYJYWeJvt5lo2/VclyLO6xpcoJOnxFxBhIH8LlNIeYfIM+BjXetXa
BLmKaTbnPMQlw+QEmnTClSSDybwjGARhcNiMZHM2I/Im6G61dmiLqw2jCYJxYTZL
5wIDAQAB
-----END PUBLIC KEY-----""".strip()

BOB_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDHsdlPkITY9pCx
dKenfcwrcfyO6TwFNZJE/BKzRsB12wWiCyvCXwiXpXIMf6Xlr7Vmuf97uK4FFoOT
H4970hXG2VhbxhgpPD6OJOMJPMZLLFyYfDasSoZiPTxxqxPaDtTxg46XxKLgcCKs
VLtp96WM/x05C1UuuUSRK2rN+u7qG2/8kI9Gw/Xz17mBFNokAKINm6qbJ3FkFQ6R
zHEENFaFINMrmTiHKbRJKwMA+h8VVrHt/FC2QXgdr/Nr/4OlUGsvqpMKUR9ueL3r
SiKX5OcsMWoa3jLfVGRwUgxpwenFjzDYB4JFNjoPM1oH6wsZxyXL20r099+Wya8m
A3AhKV0XAgMBAAECggEAL/UjRjtj3CMizqtAVDYe4VQnnj6fHnUmIpETAKD+OY+X
A7qBENX330tpX10Mf2O6QehrVdAdYrVsddm/gLIMbsvlr2ycgtKoB0UOjTpeONF3
j1tNWgUvzsn8CSRXySeEtles1//uSc5EVXSn6aQCyyC9aOSy2Vy+/coahUs9M1Vk
QCPG4ACzX5MPH5yWgjtXsxCXjDDPDlBgxpfqWW3c1ZWw1RoJZHlxq3O7jsVyJUzL
sIZDB3XGokWpkszrz/cgkHrRp/kmkHE4jqogs5pX1xDpUpjP5vXh9BJiNdSWWeKL
IEYBlNqsdmZ0N5q3pshzoAVPpmnkpy0KPIdb5noUQQKBgQD86x2BC1gHiX+GUo+G
/WwAUiFo9oXfp5vSeQcrT7M4foXyftM6Bf/Fns71s5JW6zS7/DP/THQY9MD81dLY
ceSmCElFFfeY77agLwpcTkYCTSIHHqyKQrzUV63nGYlUK97sUmetxK/NcFnoreMJ
ZYKq6H46mWsogmvDtE5Y1xVzIQKBgQDKILjdu4SZha30pZqdOddWRVZ2dcwl3NF5
Asju040qZX0GIyeT/alJlyCeSIaW+3wSIIejWKU+XkM8hR7RJlQQHGDlSl0o+ePq
Xw3NMD78h92f7EzxmRDjKf2mNm1xmPVUf1wrLqhVFVf6HA+6gLA/WW9A/tQWGbkh
A04PNUqBNwKBgByG6G0FuogfGiMsbMPtEaF3og0UwUTYwtqajBR2iOB2ZOVVKL4C
rza7EtzjxD3JickqSTMijHXEJYBfHckMD54qkRkZwTOe1hp7M8/1hC/+QzhKXWu6
21GYEiVe2/6CdEJziP4wkSO66Gk2M8V7jaF5V8OESnHnRABu9edPWzwBAoGAFptm
UdaBVDJxbGWBT4iCnzGOJB20wZ9bBm/bTWr35QAI5cDU0maSopp2mX1/IC/shpKA
2TI2+SzN1F0HP1lMGaky5TJWDRk19qa/Am4c/V2s2hAx4uu9ycqOhiKcRxJWjibY
hjPnu+xxNJYi5Dc0f0FfgiN+USJ7ZEfcWTMarC0CgYEArXEeXTRz4UVZ/LUKYnjD
2v8hGcqsr/sYruRXIBJR30ejDdbjjKewC1AD1f2NAVKJtIskafVkwCE/+l23IQtV
8vlTFoo+4CQUbUF9mUY+tnS45rssuyOv5TsTKMPxkRzsEidm0WaO3wzisGfL6QVd
axzJ8SI0DAG8NhcOQtkX86o=
-----END PRIVATE KEY-----""".strip()

BOB_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAx7HZT5CE2PaQsXSnp33M
K3H8juk8BTWSRPwSs0bAddsFogsrwl8Il6VyDH+l5a+1Zrn/e7iuBRaDkx+Pe9IV
xtlYW8YYKTw+jiTjCTzGSyxcmHw2rEqGYj08casT2g7U8YOOl8Si4HAirFS7afel
jP8dOQtVLrlEkStqzfru6htv/JCPRsP189e5gRTaJACiDZuqmydxZBUOkcxxBDRW
hSDTK5k4hym0SSsDAPofFVax7fxQtkF4Ha/za/+DpVBrL6qTClEfbni960oil+Tn
LDFqGt4y31RkcFIMacHpxY8w2AeCRTY6DzNaB+sLGccly9tK9PfflsmvJgNwISld
FwIDAQAB
-----END PUBLIC KEY-----""".strip()

TEST_USERS_DATA = [
    {
        "username": "test_alice",
        "service_id": "chatApp",
        "first_name": "Алиса",
        "last_name": "Тестовая",
        "password": "TestPassword123!",
        "cloud_password": "CloudSecret123!",
        "device_id": "test_alice_web_1",
        "private_key_pem": ALICE_PRIVATE_KEY_PEM,
        "public_key_pem": ALICE_PUBLIC_KEY_PEM,
    },
    {
        "username": "test_bob",
        "service_id": "chatApp",
        "first_name": "Боб",
        "last_name": "Тестовый",
        "password": "TestPassword123!",
        "cloud_password": "CloudSecret123!",
        "device_id": "test_bob_web_1",
        "private_key_pem": BOB_PRIVATE_KEY_PEM,
        "public_key_pem": BOB_PUBLIC_KEY_PEM,
    },
]


def generate_rsa_keypair() -> tuple[str, str]:
    """Генерирует пару RSA-2048 ключей в формате PEM."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


def encrypt_private_key_backup(
    private_pem: str,
    passphrase: str,
    iterations: int = 310000,
) -> dict[str, str | dict]:
    """
    Шифрует приватный ключ мастер-паролем через PBKDF2-SHA256 + AES-256-GCM.
    Полностью совместимо с форматом frontend (keyBackupCrypto.ts).
    """
    salt = os.urandom(16)
    nonce = os.urandom(12)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    derived_key = kdf.derive(passphrase.encode("utf-8"))

    aesgcm = AESGCM(derived_key)
    ciphertext = aesgcm.encrypt(nonce, private_pem.encode("utf-8"), None)

    return {
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "kdf": "pbkdf2-sha256",
        "kdf_salt_b64": base64.b64encode(salt).decode("ascii"),
        "kdf_params": {"iterations": iterations},
        "wrap_alg": "aes-256-gcm",
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
    }


def seed_test_users(db: Session) -> dict[str, uuid.UUID]:
    """
    Идемпотентный сидинг тестовых пользователей:
    - Создает/обновляет test_alice и test_bob
    - Сохраняет стабильный Zero-Knowledge бэкап в UserKeyBackups
    - Создает/обновляет первичное устройство в Devices со стабильным открытым ключом
    - Создает Direct Room между ними с валидным расшифровываемым приветственным сообщением
    """
    created_ids: dict[str, uuid.UUID] = {}

    for data in TEST_USERS_DATA:
        username = data["username"]
        user = db.query(Users).filter(Users.username == username).first()

        password_hash = jwt_handler.hash_password(data["password"])

        if not user:
            user = Users(
                id=uuid.uuid4(),
                username=username,
                service_id=data["service_id"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                password_hash=password_hash,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            db.flush()
            logger.info("Created test user: %s (id=%s)", username, user.id)
        else:
            user.password_hash = password_hash
            user.is_active = True
            user.first_name = data["first_name"]
            user.last_name = data["last_name"]
            db.flush()
            logger.info("Updated test user: %s (id=%s)", username, user.id)

        created_ids[username] = user.id

        # Проверяем или обновляем ключевой бэкап стабильными ключами
        backup = db.query(UserKeyBackups).filter(UserKeyBackups.user_id == user.id).first()
        private_pem = data["private_key_pem"]
        public_pem = data["public_key_pem"]
        enc_info = encrypt_private_key_backup(private_pem, data["cloud_password"])

        if not backup:
            backup = UserKeyBackups(
                user_id=user.id,
                ciphertext=str(enc_info["ciphertext"]),
                kdf=str(enc_info["kdf"]),
                kdf_salt_b64=str(enc_info["kdf_salt_b64"]),
                kdf_params=enc_info["kdf_params"],
                wrap_alg=str(enc_info["wrap_alg"]),
                nonce_b64=str(enc_info["nonce_b64"]),
            )
            db.add(backup)
            logger.info("Created key backup for: %s", username)
        else:
            backup.ciphertext = str(enc_info["ciphertext"])
            backup.kdf = str(enc_info["kdf"])
            backup.kdf_salt_b64 = str(enc_info["kdf_salt_b64"])
            backup.kdf_params = enc_info["kdf_params"]
            backup.wrap_alg = str(enc_info["wrap_alg"])
            backup.nonce_b64 = str(enc_info["nonce_b64"])
            logger.info("Ensured deterministic key backup for: %s", username)

        # Проверяем или регистрируем первичное устройство
        dev_id = data["device_id"]
        device = db.query(Devices).filter(Devices.user_id == user.id, Devices.device_id == dev_id).first()
        if not device:
            device = Devices(
                user_id=user.id,
                device_id=dev_id,
                name=f"{data['first_name']} Web Device",
                platform="web",
                identity_key_public=public_pem,
                is_active=True,
            )
            db.add(device)
            logger.info("Registered device %s for %s", dev_id, username)
        else:
            device.is_active = True
            device.identity_key_public = public_pem

    # Создаем/проверяем Direct Room между Алисой и Бобом
    alice_id = created_ids.get("test_alice")
    bob_id = created_ids.get("test_bob")

    if alice_id and bob_id:
        alice_rooms = {
            ru.room_id
            for ru in db.query(RoomUsers).filter(RoomUsers.user_id == alice_id).all()
        }
        bob_rooms = {
            ru.room_id
            for ru in db.query(RoomUsers).filter(RoomUsers.user_id == bob_id).all()
        }
        common = alice_rooms.intersection(bob_rooms)
        direct_room = None
        if common:
            direct_room = (
                db.query(Rooms)
                .filter(Rooms.id.in_(common), Rooms.room_type == "direct")
                .first()
            )

        if not direct_room:
            direct_room = Rooms(
                id=uuid.uuid4(),
                name="Алиса и Боб",
                room_type="direct",
                created_by=alice_id,
                participant_count=2,
                is_active=True,
            )
            db.add(direct_room)
            db.flush()

            db.add(RoomUsers(user_id=alice_id, room_id=direct_room.id, role="member"))
            db.add(RoomUsers(user_id=bob_id, room_id=direct_room.id, role="member"))
            logger.info("Created direct room between test_alice and test_bob (id=%s)", direct_room.id)

        # Создаем тестовое расшифровываемое приветственное сообщение только если сообщений еще нет
        existing_msgs_count = db.query(Messages).filter(Messages.room_id == direct_room.id).count()
        if existing_msgs_count == 0:
            try:
                greeting_text = "Привет, Алиса! Это защищенный тестовый чат с Zero-Knowledge сквозным шифрованием."
                plain_json = json.dumps({"text": greeting_text}).encode("utf-8")
                aes_key = os.urandom(32)
                nonce = os.urandom(12)
                aesgcm = AESGCM(aes_key)
                enc_data = aesgcm.encrypt(nonce, plain_json, None)

                alice_pub = serialization.load_pem_public_key(ALICE_PUBLIC_KEY_PEM.encode("utf-8"))
                bob_pub = serialization.load_pem_public_key(BOB_PUBLIC_KEY_PEM.encode("utf-8"))

                oaep_pad = padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                )
                wrap_alice = alice_pub.encrypt(aes_key, oaep_pad)
                wrap_bob = bob_pub.encrypt(aes_key, oaep_pad)

                enc_data_b64 = base64.b64encode(enc_data).decode("ascii")
                nonce_b64 = base64.b64encode(nonce).decode("ascii")
                wrap_alice_b64 = base64.b64encode(wrap_alice).decode("ascii")
                wrap_bob_b64 = base64.b64encode(wrap_bob).decode("ascii")

                msg = Messages(
                    id=uuid.uuid4(),
                    sender_id=bob_id,
                    recipient_id=alice_id,
                    room_id=direct_room.id,
                    encrypted_data=enc_data_b64,
                    nonce=nonce_b64,
                    status="delivered",
                    is_read=False,
                )
                db.add(msg)
                db.flush()

                db.add(MessageRecipientKeys(message_id=msg.id, user_id=alice_id, encrypted_aes_key=wrap_alice_b64))
                db.add(MessageRecipientKeys(message_id=msg.id, user_id=bob_id, encrypted_aes_key=wrap_bob_b64))
                db.add(MessageDeviceKeys(message_id=msg.id, user_id=alice_id, device_id="test_alice_web_1", encrypted_aes_key=wrap_alice_b64))
                db.add(MessageDeviceKeys(message_id=msg.id, user_id=bob_id, device_id="test_bob_web_1", encrypted_aes_key=wrap_bob_b64))
                logger.info("Seeded initial decrypted message in direct room: %s", msg.id)
            except Exception as e:
                logger.warning("Failed to seed initial greeting message: %s", e)

        db.commit()
        return created_ids
