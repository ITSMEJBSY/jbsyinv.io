#!/usr/bin/env python3
"""
JBSY Inventory - Local Backend Server
Serves index.html and provides API endpoints for inventory.db
Run: python server.py
Then open: http://localhost:8000
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
import sqlite3
import json
import os
import sys

DB_FILE = 'inventory.db'
PORT = 8000

# Full schema matching the HTML app
SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    id TEXT PRIMARY KEY,
    name TEXT,
    category TEXT,
    serial TEXT,
    brand TEXT,
    status TEXT,
    user TEXT,
    empId TEXT,
    position TEXT,
    immHead TEXT,
    empStatus TEXT,
    purpose TEXT,
    dept TEXT,
    contact TEXT,
    email TEXT,
    location TEXT,
    purchaseDate TEXT,
    warrantyDate TEXT,
    cost REAL,
    condition TEXT,
    notes TEXT,
    attachment TEXT,
    photo TEXT
);
CREATE TABLE IF NOT EXISTS auditLogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    tag TEXT,
    name TEXT,
    action TEXT,
    user TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS maintLogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    tag TEXT,
    name TEXT,
    title TEXT,
    tech TEXT,
    cost REAL,
    notes TEXT,
    resolved INTEGER
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    name TEXT,
    role TEXT,
    passwordHash TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg TEXT,
    ts TEXT,
    color TEXT
);
"""

# Columns of the inventory table (for safe INSERT/UPDATE)
INVENTORY_COLS = [
    'id','name','category','serial','brand','status','user','empId','position',
    'immHead','empStatus','purpose','dept','contact','email','location',
    'purchaseDate','warrantyDate','cost','condition','notes','attachment','photo'
]

def init_db():
    """Create tables if the DB file doesn't exist yet."""
    conn = sqlite3.connect(DB_FILE)
    conn.executescript(SCHEMA)
    # Try adding missing columns for older DBs
    for col, typ in [
        ('attachment','TEXT'), ('photo','TEXT'),
        ('empId','TEXT'), ('position','TEXT'), ('immHead','TEXT'),
        ('empStatus','TEXT'), ('purpose','TEXT'), ('dept','TEXT'),
        ('contact','TEXT'), ('email','TEXT'),
        ('passwordHash','TEXT'), ('created','TEXT'),
    ]:
        try:
            conn.execute(f"ALTER TABLE inventory ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN passwordHash TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN created TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(SimpleHTTPRequestHandler):
    # Silence per-request logging noise (optional)
    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def _send_json(self, obj, status=200):
        data = json.dumps(obj, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode('utf-8'))

    def do_OPTIONS(self):
        # CORS preflight
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # ---- GET ----
    def do_GET(self):
        if self.path == '/api/health':
            self._send_json({'ok': True, 'db': os.path.abspath(DB_FILE)})
            return
        if self.path == '/api/all':
            # Returns full DB in one shot for initial load
            conn = get_conn()
            try:
                result = {}
                for table in ['inventory','auditLogs','maintLogs','users','activity']:
                    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                    result[table] = [row_to_dict(r) for r in rows]
                self._send_json(result)
            finally:
                conn.close()
            return
        # Default: serve static files (index.html, cong.png, etc.)
        super().do_GET()

    # ---- POST ----
    def do_POST(self):
        try:
            body = self._read_body()
        except Exception as e:
            self._send_json({'error': f'Invalid JSON: {e}'}, 400)
            return

        if self.path == '/api/inventory/save':
            # Save (insert or replace) one inventory item
            self._save_inventory(body)
            return
        if self.path == '/api/inventory/delete':
            self._delete_inventory(body)
            return
        if self.path == '/api/inventory/replace_all':
            self._replace_all_inventory(body)
            return
        if self.path == '/api/generic/save':
            self._generic_save(body)
            return
        if self.path == '/api/generic/delete':
            self._generic_delete(body)
            return
        if self.path == '/api/generic/add':
            self._generic_add(body)
            return
        if self.path == '/api/generic/clear':
            self._generic_clear(body)
            return
        self._send_json({'error': 'Unknown endpoint'}, 404)

    # ---- Handlers ----
    def _save_inventory(self, item):
        if 'id' not in item or not item['id']:
            self._send_json({'error': 'id required'}, 400); return
        conn = get_conn()
        try:
            # Build only known columns
            cols = [c for c in INVENTORY_COLS if c in item]
            vals = [item[c] for c in cols]
            placeholders = ','.join('?' * len(cols))
            conn.execute(
                f"INSERT OR REPLACE INTO inventory ({','.join(cols)}) VALUES ({placeholders})",
                vals
            )
            conn.commit()
            self._send_json({'ok': True, 'id': item['id']})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)
        finally:
            conn.close()

    def _delete_inventory(self, body):
        item_id = body.get('id')
        if not item_id:
            self._send_json({'error': 'id required'}, 400); return
        conn = get_conn()
        try:
            conn.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
            conn.commit()
            self._send_json({'ok': True})
        finally:
            conn.close()

    def _replace_all_inventory(self, body):
        items = body.get('items', [])
        conn = get_conn()
        try:
            conn.execute("DELETE FROM inventory")
            for item in items:
                cols = [c for c in INVENTORY_COLS if c in item]
                vals = [item[c] for c in cols]
                placeholders = ','.join('?' * len(cols))
                conn.execute(
                    f"INSERT OR REPLACE INTO inventory ({','.join(cols)}) VALUES ({placeholders})",
                    vals
                )
            conn.commit()
            self._send_json({'ok': True, 'count': len(items)})
        except Exception as e:
            conn.rollback()
            self._send_json({'error': str(e)}, 500)
        finally:
            conn.close()

    def _generic_save(self, body):
        """INSERT OR REPLACE into users table (username as key)."""
        table = body.get('table')
        item = body.get('item', {})
        if table != 'users':
            self._send_json({'error': 'unsupported table'}, 400); return
        conn = get_conn()
        try:
            keys = list(item.keys())
            ph = ','.join('?' * len(keys))
            conn.execute(f"INSERT OR REPLACE INTO users ({','.join(keys)}) VALUES ({ph})",
                         [item[k] for k in keys])
            conn.commit()
            self._send_json({'ok': True})
        finally:
            conn.close()

    def _generic_add(self, body):
        """INSERT auto-increment row into auditLogs/maintLogs/activity."""
        table = body.get('table')
        item = body.get('item', {})
        if table not in ('auditLogs','maintLogs','activity'):
            self._send_json({'error': 'unsupported table'}, 400); return
        conn = get_conn()
        try:
            keys = [k for k in item.keys() if k != 'id']
            ph = ','.join('?' * len(keys))
            conn.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({ph})",
                         [item[k] for k in keys])
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            self._send_json({'ok': True, 'id': new_id})
        finally:
            conn.close()

    def _generic_delete(self, body):
        table = body.get('table')
        key = body.get('key')
        keycol = body.get('keycol', 'id')
        allowed = {'inventory':'id','users':'username','auditLogs':'id',
                   'maintLogs':'id','activity':'id'}
        if table not in allowed:
            self._send_json({'error': 'unsupported table'}, 400); return
        conn = get_conn()
        try:
            conn.execute(f"DELETE FROM {table} WHERE {keycol} = ?", (key,))
            conn.commit()
            self._send_json({'ok': True})
        finally:
            conn.close()

    def _generic_clear(self, body):
        table = body.get('table')
        if table not in ('inventory','auditLogs','maintLogs','users','activity'):
            self._send_json({'error': 'unsupported table'}, 400); return
        conn = get_conn()
        try:
            conn.execute(f"DELETE FROM {table}")
            conn.commit()
            self._send_json({'ok': True})
        finally:
            conn.close()


def main():
    init_db()
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print(f"JBSY server running at http://localhost:{PORT}")
    print(f"Database file: {os.path.abspath(DB_FILE)}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == '__main__':
    main()
