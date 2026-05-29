import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

load_dotenv()

# === CHECK THESE STRINGS CAREFULLY ===
ENCRYPTED_API = 'iKPtUVh8mF8u98j0J+e3dhnjruxsb1ly/4watI3kBx4OBknLHsE2DgIF'
ENCRYPTED_SECRET = '67j1ZVQb62Nej4zAG/6GQU7SiPQNWUJa+Ll4HBj9sYP9FWxpNXTXXDG68T5m9+ZRAZ6AqdvHEzRg91FV'

def run_forensic_diagnostic():
    print("--- Vault Forensic Report ---")
    
    # 1. Check .env Loading
    aes_key_raw = os.getenv("AES_KEY")
    nonce_raw = os.getenv("NONCE")
    
    print(f"Checking .env variables...")
    print(f"-> AES_KEY found: {'YES' if aes_key_raw else 'NO'}")
    print(f"-> NONCE found:   {'YES' if nonce_raw else 'NO'}")
    
    if not aes_key_raw or not nonce_raw:
        print("❌ STOP: The script can't see your .env variables. Check your .env file name.")
        return

    try:
        # 2. Try to decode Base64
        print(f"Attempting Base64 Decode...")
        aes_key = base64.b64decode(aes_key_raw)
        nonce = base64.b64decode(nonce_raw)
        enc_api = base64.b64decode(ENCRYPTED_API)
        
        # 3. Attempt Decryption
        print(f"Attempting AES-GCM Decryption...")
        aesgcm = AESGCM(aes_key)
        decrypted_api = aesgcm.decrypt(nonce, enc_api, None).decode('utf-8')
        
        print("\n✅ SUCCESS: Vault Unlocked.")
    except Exception as e:
        print(f"\n❌ DECRYPTION FAILED")
        print(f"Technical Reason: {type(e).__name__}")
        print("\n--- Troubleshooting Steps ---")
        print("1. Did you copy a space at the end of the string in .env?")
        print("2. Are there extra quotes INSIDE the quotes in vault_test.py?")
        print("3. Did you delete 'keymaster.py' and generate NEW keys but forgot to update .env?")

run_forensic_diagnostic()