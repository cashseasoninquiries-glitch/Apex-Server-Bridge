import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- CONFIGURATION ---
# Point this to your Bridge folder where your .env lives
WATCH_PATH = "/app"
ENV_FILE = ".env"

class ConfigHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory and ENV_FILE in event.src_path:
            self.validate_env(event.src_path)

    def validate_env(self, file_path):
        print(f"\n--- [CONFIG WATCHER] .env change detected. Validating... ---")
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
                config = {l.split('=')[0].strip(): l.split('=')[1].strip() for l in lines if '=' in l}
            
            key = config.get('APCA_API_KEY_ID', '')
            url = config.get('APCA_API_BASE_URL', '')

            # Logic Check 1: Paper Key vs Live URL
            if "paper-api" not in url and key.startswith("PK"):
                print("❌ [CRITICAL] Mismatch: Using PAPER key with LIVE URL.")
                print("FIX: Change URL to https://paper-api.alpaca.markets")
            
            # Logic Check 2: Length Check
            elif len(key) < 20:
                print("⚠️ [WARNING] Key seems too short. Check for copy-paste errors.")
            
            else:
                print("✅ [OK] Environment looks logically sound.")
                
        except Exception as e:
            print(f"--- [WATCHER ERROR] Failed to parse .env: {e} ---")

if __name__ == "__main__":
    event_handler = ConfigHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_PATH, recursive=False)
    observer.start()

    print(f"Config Watcher is ACTIVE and guarding {WATCH_PATH}/.env")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()