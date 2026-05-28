import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# === 1. PASTE YOUR REAL ALPACA KEYS HERE JUST ONCE ===
# (Make sure to keep the keys inside the quotes)
RAW_API_KEY = "PKSLZSEW767QRABA5KNL6PHFBA".encode('utf-8')
RAW_SECRET_KEY = "3PKxV46kGNsenXsvbzhTWfSnEtrgSpd2ZK5xDW3WAekY".encode('utf-8')

print("Generating sovereign vault keys...")

# === 2. THE MATH (DO NOT TOUCH) ===
# Generate a 256-bit AES Master Key
aes_key = AESGCM.generate_key(bit_length=256)
aesgcm = AESGCM(aes_key)

# Generate a 12-byte Nonce
nonce = os.urandom(12)

# Encrypt the raw keys
encrypted_api = aesgcm.encrypt(nonce, RAW_API_KEY, None)
encrypted_secret = aesgcm.encrypt(nonce, RAW_SECRET_KEY, None)

# Base64 encode everything so it prints as clean text you can copy/paste
b64_aes_key = base64.b64encode(aes_key).decode('utf-8')
b64_nonce = base64.b64encode(nonce).decode('utf-8')
b64_enc_api = base64.b64encode(encrypted_api).decode('utf-8')
b64_enc_secret = base64.b64encode(encrypted_secret).decode('utf-8')

# === 3. THE OUTPUT ===
print("\n" + "="*40)
print("🔐 SUCCESS. COPY THE DATA BELOW. 🔐")
print("="*40)

print("\n[STEP A] Paste this exactly into your .env file:")
print(f"AES_KEY={b64_aes_key}")
print(f"NONCE={b64_nonce}")

print("\n[STEP B] Paste this exactly into your vault_guard.py file:")
print(f"ENCRYPTED_API = '{b64_enc_api}'")
print(f"ENCRYPTED_SECRET = '{b64_enc_secret}'")
print("\n" + "="*40)