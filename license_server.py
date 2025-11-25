from flask import Flask, request, jsonify
import sqlite3
import datetime
import os

app = Flask(__name__)
DB_NAME = "licenses.db"

def init_db():
    """Инициализация базы данных"""
    # Note: On Render free tier, the filesystem is ephemeral. 
    # The database will be reset on every deploy/restart.
    # For production, use a persistent disk or an external database (PostgreSQL).
    if not os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # Таблица лицензий
        c.execute('''CREATE TABLE IF NOT EXISTS licenses
                     (key TEXT PRIMARY KEY, 
                      status TEXT DEFAULT 'active', 
                      expiration_date TEXT,
                      max_machines INTEGER DEFAULT 1)''')
        
        # Таблица активаций (связка ключ-машина)
        c.execute('''CREATE TABLE IF NOT EXISTS activations
                     (machine_id TEXT, 
                      license_key TEXT, 
                      last_check TEXT,
                      ip_address TEXT,
                      PRIMARY KEY (machine_id, license_key))''')
        
        # Добавляем тестовый ключ
        c.execute("INSERT OR IGNORE INTO licenses (key, status, max_machines) VALUES (?, ?, ?)", 
                  ("TEST-KEY-12345", "active", 5))
        
        conn.commit()
        conn.close()
        print("База данных инициализирована")

@app.route('/')
def index():
    return "License Server is Running"

@app.route('/api/check_license', methods=['POST'])
def check_license():
    data = request.json
    machine_id = data.get('machine_id')
    license_key = data.get('license_key')
    
    if not machine_id or not license_key:
        return jsonify({"status": "error", "message": "Missing data"}), 400
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. Проверяем сам ключ
    c.execute("SELECT status, max_machines FROM licenses WHERE key=?", (license_key,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"status": "invalid", "message": "Key not found"}), 200
        
    status, max_machines = row
    
    if status != 'active':
        conn.close()
        return jsonify({"status": status, "message": "License is not active"}), 200
    
    # 2. Проверяем привязку к машине
    c.execute("SELECT count(*) FROM activations WHERE license_key=?", (license_key,))
    current_activations = c.fetchone()[0]
    
    c.execute("SELECT * FROM activations WHERE machine_id=? AND license_key=?", (machine_id, license_key))
    activation = c.fetchone()
    
    if not activation:
        # Новая машина
        if current_activations >= max_machines:
            conn.close()
            return jsonify({"status": "limit_exceeded", "message": "Max machines limit reached"}), 200
        
        # Активируем
        c.execute("INSERT INTO activations (machine_id, license_key, last_check, ip_address) VALUES (?, ?, ?, ?)",
                  (machine_id, license_key, datetime.datetime.now().isoformat(), request.remote_addr))
        conn.commit()
    else:
        # Обновляем время последней проверки
        c.execute("UPDATE activations SET last_check=?, ip_address=? WHERE machine_id=? AND license_key=?",
                  (datetime.datetime.now().isoformat(), request.remote_addr, machine_id, license_key))
        conn.commit()
    
    conn.close()
    return jsonify({"status": "active"})

@app.route('/admin/licenses', methods=['GET'])
def list_licenses():
    """Админский метод для просмотра лицензий"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM licenses")
    licenses = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(licenses)

@app.route('/admin/block_key', methods=['POST'])
def block_key():
    """Блокировка ключа (Kill-switch)"""
    key = request.json.get('key')
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE licenses SET status='blocked' WHERE key=?", (key,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "message": f"Key {key} blocked"})

# Инициализируем БД при старте модуля (чтобы работало с Gunicorn)
init_db()

if __name__ == '__main__':
    # Получаем порт из переменной окружения (требование Render)
    # По умолчанию 8000 для локального запуска
    port = int(os.environ.get("PORT", 8000))
    print(f"Сервер лицензий запущен на порту {port}")
    # Слушаем 0.0.0.0 (требование Render)
    app.run(host='0.0.0.0', port=port)
