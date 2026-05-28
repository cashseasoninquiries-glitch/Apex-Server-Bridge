import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# The internal Docker network address for the Vault
DB_HOST = "apex_postgres_vault"
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASS = os.getenv("POSTGRES_PASSWORD")

def get_db_connection():
    """Establishes a direct line to the PostgreSQL Vault."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        return conn
    except Exception as e:
        print(f"DATABASE FAULT: Could not connect to the Vault. {e}")
        return None

def initialize_vault():
    """Pours the concrete for the database tables."""
    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()
    
    # Create the exact tables from your legacy SQLite build, but in PostgreSQL
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            alpaca_key VARCHAR(255),
            alpaca_secret VARCHAR(255),
            discord_url VARCHAR(255),
            webhook_token VARCHAR(255) UNIQUE
        );
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            msg TEXT
        );
    ''')
    
    conn.commit()
    cursor.close()
    conn.close()
    print("Vault Tables Verified & Initialized.")

if __name__ == "__main__":
    # Test the connection if this file is run directly
    initialize_vault()