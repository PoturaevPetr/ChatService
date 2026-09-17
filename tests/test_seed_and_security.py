"""
Unit tests for seed_test_users and Zero-Knowledge security invariants.
"""

import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.database.Users import Users
from server.database.UserKeyBackups import UserKeyBackups
from server.database.Rooms import Rooms
from server.database.RoomUsers import RoomUsers
from server.database.Devices import Devices
from server.database.DeviceLoginPending import DeviceLoginPending
from server.database.seed_test_users import (
    seed_test_users,
    generate_rsa_keypair,
    encrypt_private_key_backup,
)
from server.auth.jwt_handler import jwt_handler
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64


def test_generate_rsa_keypair():
    priv, pub = generate_rsa_keypair()
    assert "-----BEGIN PRIVATE KEY-----" in priv
    assert "-----BEGIN PUBLIC KEY-----" in pub


def test_encrypt_decrypt_key_backup():
    priv, pub = generate_rsa_keypair()
    password = "CloudSecret123!"
    enc = encrypt_private_key_backup(priv, password, iterations=1000)

    salt = base64.b64decode(enc["kdf_salt_b64"])
    nonce = base64.b64decode(enc["nonce_b64"])
    ciphertext = base64.b64decode(enc["ciphertext"])

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=1000,
    )
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
    assert decrypted == priv

    # Wrong password check
    kdf_wrong = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=1000,
    )
    key_wrong = kdf_wrong.derive(b"WrongPassword123!")
    aesgcm_wrong = AESGCM(key_wrong)
    failed = False
    try:
        aesgcm_wrong.decrypt(nonce, ciphertext, None)
    except Exception:
        failed = True
    assert failed, "Decryption with wrong password must fail!"


def test_seed_test_users_sqlite():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    created_ids = seed_test_users(db)
    assert "test_alice" in created_ids
    assert "test_bob" in created_ids

    alice = db.query(Users).filter(Users.username == "test_alice").first()
    assert alice is not None
    assert jwt_handler.verify_password("TestPassword123!", alice.password_hash)

    bob = db.query(Users).filter(Users.username == "test_bob").first()
    assert bob is not None
    assert jwt_handler.verify_password("TestPassword123!", bob.password_hash)

    # Check key backup
    alice_backup = db.query(UserKeyBackups).filter(UserKeyBackups.user_id == alice.id).first()
    assert alice_backup is not None
    assert alice_backup.wrap_alg == "aes-256-gcm"
    assert alice_backup.kdf == "pbkdf2-sha256"

    # Check direct room
    room_users_alice = db.query(RoomUsers).filter(RoomUsers.user_id == alice.id).all()
    room_users_bob = db.query(RoomUsers).filter(RoomUsers.user_id == bob.id).all()
    alice_rids = {ru.room_id for ru in room_users_alice}
    bob_rids = {ru.room_id for ru in room_users_bob}
    common = alice_rids.intersection(bob_rids)
    assert len(common) >= 1

    db.close()


if __name__ == "__main__":
    print("Testing generate_rsa_keypair...")
    test_generate_rsa_keypair()
    print("Testing encrypt_decrypt_key_backup...")
    test_encrypt_decrypt_key_backup()
    print("Testing seed_test_users_sqlite...")
    test_seed_test_users_sqlite()
    print("All python tests passed successfully!")
