# vibenet.py - VibeNet Full-Featured (Render PostgreSQL Compatible + Sessions)
import os
import uuid
import datetime
import json as _json
from flask import Flask, request, jsonify, send_from_directory, g, render_template_string, session, redirect
import hashlib

# ---------- Database Imports ----------
import sqlite3
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES_LIB = True
except ImportError:
    HAS_POSTGRES_LIB = False

# ---------- Config ----------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "vibenet.db")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['PORT'] = int(os.environ.get("PORT", 5000))
DATABASE_URL = os.environ.get("DATABASE_URL")
app.secret_key = os.environ.get("SECRET_KEY", "vibenet_secret_key_change_this_in_production")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")

# ---------- Database Logic (Hybrid SQLite/Postgres) ----------

def get_db_type():
    """Returns 'postgres' if configured, else 'sqlite'"""
    if DATABASE_URL and HAS_POSTGRES_LIB:
        return 'postgres'
    return 'sqlite'

class PostgresCursorWrapper:
    """Translates SQLite syntax (?) to Postgres syntax (%s) on the fly"""
    def __init__(self, original_cursor):
        self.cursor = original_cursor
        self.lastrowid = None

    def execute(self, sql, args=None):
        sql = sql.replace('?', '%s')
        is_insert = sql.strip().upper().startswith("INSERT")
        if is_insert:
            sql += " RETURNING id"
        
        if args is None:
            self.cursor.execute(sql)
        else:
            self.cursor.execute(sql, args)
        
        if is_insert:
            res = self.cursor.fetchone()
            if res:
                self.lastrowid = res['id'] if isinstance(res, dict) else res[0]

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()
    
    def __getattr__(self, name):
        return getattr(self.cursor, name)

def get_db():
    if getattr(g, "_db", None) is None:
        if get_db_type() == 'postgres':
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            g._db = conn
            g._db_type = 'postgres'
        else:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            g._db = conn
            g._db_type = 'sqlite'
    return g._db

def get_cursor(db):
    if getattr(g, "_db_type", 'sqlite') == 'postgres':
        return PostgresCursorWrapper(db.cursor())
    return db.cursor()

def init_db():
    db = get_db()
    cur = get_cursor(db)
    
    if get_db_type() == 'postgres':
        pk_def = "SERIAL PRIMARY KEY"
    else:
        pk_def = "INTEGER PRIMARY KEY AUTOINCREMENT"

    # Users table with all fields
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS users (
        id {pk_def},
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        profile_pic TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        watch_hours INTEGER DEFAULT 0,
        earnings REAL DEFAULT 0.0,
        verified INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        email_verified INTEGER DEFAULT 0,
        phone TEXT DEFAULT '',
        phone_verified INTEGER DEFAULT 0,
        last_active TEXT DEFAULT '',
        age_verified INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Followers
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS followers (
        id {pk_def},
        user_email TEXT,
        follower_email TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Posts with all fields
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS posts (
        id {pk_def},
        author_email TEXT,
        author_name TEXT,
        profile_pic TEXT DEFAULT '',
        text TEXT DEFAULT '',
        file_url TEXT DEFAULT '',
        file_mime TEXT DEFAULT '',
        thumbnail_url TEXT DEFAULT '',
        timestamp TEXT,
        reactions_json TEXT DEFAULT '{{"👍":0,"❤️":0,"😂":0}}',
        comments_count INTEGER DEFAULT 0
    )""")
    
    # User reactions
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS user_reactions (
        id {pk_def},
        user_email TEXT,
        post_id INTEGER,
        emoji TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_email, post_id)
    )""")
    
    # Comments
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS comments (
        id {pk_def},
        post_id INTEGER,
        user_email TEXT,
        user_name TEXT,
        profile_pic TEXT DEFAULT '',
        text TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Messages
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS messages (
        id {pk_def},
        sender TEXT,
        recipient TEXT,
        text TEXT,
        timestamp TEXT
    )""")
    
    # Notifications
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS notifications (
        id {pk_def},
        user_email TEXT,
        text TEXT,
        timestamp TEXT,
        seen INTEGER DEFAULT 0
    )""")
    
    # Verified badge requests
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS verified_requests (
        id {pk_def},
        user_email TEXT UNIQUE,
        user_name TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Reports (content moderation)
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS reports (
        id {pk_def},
        reporter_email TEXT,
        target_type TEXT,
        target_id INTEGER,
        reason TEXT,
        status TEXT DEFAULT 'pending',
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Payout requests
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS payout_requests (
        id {pk_def},
        user_email TEXT,
        om_number TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Ad campaigns
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS ads (
        id {pk_def},
        title TEXT,
        owner_email TEXT,
        budget REAL DEFAULT 0,
        whatsapp TEXT DEFAULT '',
        impressions INTEGER DEFAULT 0,
        clicks INTEGER DEFAULT 0,
        approved INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT
    )""")
    
    db.commit()

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()

# ---------- Utilities ----------
def now_ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def require_admin():
    return session.get("email") == ADMIN_EMAIL

# ---------- Init DB ----------
with app.app_context():
    init_db()

# ---------- Static uploads ----------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"}), 200

# ---------- Auth Routes ----------
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json() or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")
    name = data.get("name", "").strip()
    
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    if cur.fetchone():
        return jsonify({"error": "Email already registered"}), 400
    
    pwd_hash = hash_password(password)
    cur.execute("INSERT INTO users (email, password, name) VALUES (?,?,?)", (email, pwd_hash, name))
    db.commit()
    
    session["email"] = email
    return jsonify({"success": True, "email": email})

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")
    
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT id, password FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    
    if not user or user['password'] != hash_password(password):
        return jsonify({"error": "Invalid credentials"}), 401
    
    session["email"] = email
    return jsonify({"success": True, "email": email})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("email", None)
    return jsonify({"success": True})

@app.route("/api/user")
def api_user():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT id, name, email, profile_pic, bio, watch_hours, earnings, verified, banned, email_verified, age_verified FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "id": user['id'],
        "name": user['name'],
        "email": user['email'],
        "profile_pic": user['profile_pic'] or "",
        "bio": user['bio'] or "",
        "watch_hours": user['watch_hours'],
        "earnings": user['earnings'],
        "verified": bool(user['verified']),
        "banned": bool(user['banned']),
        "email_verified": bool(user['email_verified']),
        "age_verified": bool(user['age_verified'])
    })

@app.route("/api/user/update", methods=["POST"])
def api_user_update():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    db = get_db()
    cur = get_cursor(db)
    
    if 'name' in data:
        cur.execute("UPDATE users SET name=? WHERE email=?", (data['name'], email))
    if 'bio' in data:
        cur.execute("UPDATE users SET bio=? WHERE email=?", (data['bio'], email))
    if 'profile_pic' in data:
        cur.execute("UPDATE users SET profile_pic=? WHERE email=?", (data['profile_pic'], email))
    
    db.commit()
    return jsonify({"success": True})

# ---------- Posts ----------
@app.route("/api/posts", methods=["GET", "POST"])
def api_posts():
    db = get_db()
    cur = get_cursor(db)
    
    if request.method == "GET":
        page = request.args.get("page", 1, type=int)
        per_page = 20
        offset = (page - 1) * per_page
        
        cur.execute("SELECT * FROM posts ORDER BY id DESC LIMIT ? OFFSET ?", (per_page, offset))
        rows = cur.fetchall()
        out = []
        for r in rows:
            rec = dict(r)
            try:
                rec['reactions'] = _json.loads(rec.get('reactions_json', '{}'))
            except:
                rec['reactions'] = {'👍': 0, '❤️': 0, '😂': 0}
            rec['user_reaction'] = None
            out.append(rec)
        return jsonify(out)
    
    else:
        email = session.get("email")
        if not email:
            return jsonify({"error": "Not logged in"}), 401
        
        data = request.get_json() or {}
        cur.execute("SELECT name, profile_pic FROM users WHERE email=?", (email,))
        user = cur.fetchone()
        
        author_name = user['name'] if user else ""
        profile_pic = user['profile_pic'] if user else ""
        text = data.get('text', '')
        file_url = data.get('file_url', '')
        file_mime = data.get('file_mime', '')
        thumbnail_url = data.get('thumbnail_url', '')
        ts = now_ts()
        reactions_json = _json.dumps({'👍': 0, '❤️': 0, '😂': 0})
        
        cur.execute("INSERT INTO posts (author_email, author_name, profile_pic, text, file_url, file_mime, thumbnail_url, timestamp, reactions_json) VALUES (?,?,?,?,?,?,?,?,?)",
                   (email, author_name, profile_pic, text, file_url, file_mime, thumbnail_url, ts, reactions_json))
        db.commit()
        
        post_id = cur.lastrowid
        cur.execute("SELECT * FROM posts WHERE id=?", (post_id,))
        r = cur.fetchone()
        rec = dict(r)
        rec['reactions'] = _json.loads(rec['reactions_json'])
        return jsonify(rec)

@app.route("/api/posts/<int:post_id>")
def api_post_get(post_id):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT * FROM posts WHERE id=?", (post_id,))
    post = cur.fetchone()
    
    if not post:
        return jsonify({"error": "Post not found"}), 404
    
    rec = dict(post)
    try:
        rec['reactions'] = _json.loads(rec.get('reactions_json', '{}'))
    except:
        rec['reactions'] = {'👍': 0, '❤️': 0, '😂': 0}
    
    return jsonify(rec)

# ---------- Reactions ----------
@app.route("/api/react", methods=["POST"])
def api_react_post():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    post_id = data.get("post_id")
    emoji = data.get("emoji")
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT reactions_json, author_email FROM posts WHERE id=?", (post_id,))
    row = cur.fetchone()
    
    if not row:
        return jsonify({"error": "Post not found"}), 404
    
    reactions = _json.loads(row['reactions_json'] or '{}')
    cur.execute("SELECT emoji FROM user_reactions WHERE user_email=? AND post_id=?", (email, post_id))
    prev = cur.fetchone()
    prev_emoji = prev['emoji'] if prev else None
    
    if prev_emoji == emoji:
        return jsonify({"success": True, "reactions": reactions})
    
    if prev_emoji:
        reactions[prev_emoji] = max(0, reactions.get(prev_emoji, 0) - 1)
        cur.execute("DELETE FROM user_reactions WHERE user_email=? AND post_id=?", (email, post_id))
    
    try:
        cur.execute("INSERT INTO user_reactions (user_email, post_id, emoji) VALUES (?,?,?)", (email, post_id, emoji))
    except:
        pass
    
    reactions[emoji] = reactions.get(emoji, 0) + 1
    cur.execute("UPDATE posts SET reactions_json=? WHERE id=?", (_json.dumps(reactions), post_id))
    db.commit()
    
    post_author = row['author_email']
    if post_author != email:
        cur.execute("INSERT INTO notifications (user_email, text, timestamp) VALUES (?,?,?)", (post_author, f"{emoji} reaction on your post", now_ts()))
        db.commit()
    
    return jsonify({"success": True, "reactions": reactions})

# ---------- Comments ----------
@app.route("/api/comments/<int:post_id>", methods=["GET"])
def api_comments_get(post_id):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT * FROM comments WHERE post_id=? ORDER BY id DESC", (post_id,))
    rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/comments", methods=["POST"])
def api_comments_post():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    post_id = data.get("post_id")
    text = data.get("text")
    
    db = get_db()
    cur = get_cursor(db)
    
    cur.execute("SELECT name, profile_pic FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    user_name = user['name'] if user else ""
    profile_pic = user['profile_pic'] if user else ""
    
    cur.execute("INSERT INTO comments (post_id, user_email, user_name, profile_pic, text, timestamp) VALUES (?,?,?,?,?,?)",
               (post_id, email, user_name, profile_pic, text, now_ts()))
    db.commit()
    
    cur.execute("UPDATE posts SET comments_count = comments_count + 1 WHERE id=?", (post_id,))
    db.commit()
    
    cur.execute("SELECT author_email FROM posts WHERE id=?", (post_id,))
    post = cur.fetchone()
    if post and post['author_email'] != email:
        cur.execute("INSERT INTO notifications (user_email, text, timestamp) VALUES (?,?,?)", (post['author_email'], f"{user_name} commented on your post", now_ts()))
        db.commit()
    
    return jsonify({"success": True})

# ---------- Notifications ----------
@app.route("/api/notifications")
def api_notifications():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT * FROM notifications WHERE user_email=? ORDER BY id DESC", (email,))
    rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/notifications/<int:notif_id>/mark-read", methods=["POST"])
def api_mark_notif_read(notif_id):
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("UPDATE notifications SET seen=1 WHERE id=? AND user_email=?", (notif_id, email))
    db.commit()
    return jsonify({"success": True})

# ---------- Following ----------
@app.route("/api/follow", methods=["POST"])
def api_follow():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    target = data.get("target_email")
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT id FROM followers WHERE user_email=? AND follower_email=?", (target, email))
    
    if cur.fetchone():
        cur.execute("DELETE FROM followers WHERE user_email=? AND follower_email=?", (target, email))
        db.commit()
        return jsonify({"success": True, "status": "unfollowed"})
    else:
        cur.execute("INSERT INTO followers (user_email, follower_email) VALUES (?,?)", (target, email))
        cur.execute("INSERT INTO notifications (user_email, text, timestamp) VALUES (?,?,?)", (target, f"{email} followed you", now_ts()))
        db.commit()
        return jsonify({"success": True, "status": "followed"})

@app.route("/api/is-following")
def api_is_following():
    f = request.args.get("f")
    t = request.args.get("t")
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT id FROM followers WHERE user_email=? AND follower_email=?", (t, f))
    return jsonify({"following": True if cur.fetchone() else False})

@app.route("/api/followers/<email>")
def api_followers(email):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT COUNT(*) as cnt FROM followers WHERE user_email=?", (email,))
    res = cur.fetchone()
    return jsonify({"count": res['cnt'] if res else 0})

# ---------- Profile ----------
@app.route("/api/profile/<email>")
def api_profile(email):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT name, bio, profile_pic, watch_hours, earnings, verified FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    cur.execute("SELECT * FROM posts WHERE author_email=? ORDER BY id DESC LIMIT 50", (email,))
    posts = [dict(r) for r in cur.fetchall()]
    
    cur.execute("SELECT COUNT(*) as cnt FROM followers WHERE user_email=?", (email,))
    followers = cur.fetchone()['cnt'] if cur.fetchone() else 0
    
    return jsonify({
        "name": user['name'],
        "bio": user['bio'] or "",
        "profile_pic": user['profile_pic'] or "",
        "watch_hours": user['watch_hours'],
        "earnings": user['earnings'],
        "verified": bool(user['verified']),
        "followers": followers,
        "posts": posts
    })

# ---------- Verified Badge ----------
@app.route("/api/verified-request", methods=["POST"])
def api_verified_request():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT name FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    cur.execute("SELECT id FROM verified_requests WHERE user_email=?", (email,))
    if cur.fetchone():
        return jsonify({"error": "Request already exists"}), 400
    
    cur.execute("INSERT INTO verified_requests (user_email, user_name) VALUES (?,?)", (email, user['name']))
    db.commit()
    return jsonify({"success": True})

# ---------- Age Verification ----------
@app.route("/api/age-verify", methods=["POST"])
def api_age_verify():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    dob = data.get("dob")
    
    if not dob:
        return jsonify({"error": "Date of birth required"}), 400
    
    try:
        birth = datetime.datetime.strptime(dob, "%Y-%m-%d")
        age = (datetime.datetime.utcnow() - birth).days // 365
        
        if age < 13:
            return jsonify({"error": "Must be 13 or older"}), 403
        
        db = get_db()
        cur = get_cursor(db)
        cur.execute("UPDATE users SET age_verified=1 WHERE email=?", (email,))
        db.commit()
        return jsonify({"success": True, "age": age})
    except:
        return jsonify({"error": "Invalid date format"}), 400

# ---------- Content Moderation ----------
@app.route("/api/report", methods=["POST"])
def api_report():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    target_type = data.get("target_type")  # "post" or "comment"
    target_id = data.get("target_id")
    reason = data.get("reason")
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("INSERT INTO reports (reporter_email, target_type, target_id, reason) VALUES (?,?,?,?)",
               (email, target_type, target_id, reason))
    db.commit()
    return jsonify({"success": True})

# ---------- Monetization ----------
@app.route("/api/watch", methods=["POST"])
def api_watch():
    data = request.get_json() or {}
    viewer = data.get("viewer")
    post_id = data.get("post_id")
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT author_email FROM posts WHERE id=?", (post_id,))
    row = cur.fetchone()
    
    if row:
        author = row['author_email']
        if author != viewer:
            cur.execute("UPDATE users SET watch_hours=watch_hours+1, earnings=earnings+0.1 WHERE email=?", (author,))
            db.commit()
    
    return jsonify({"success": True})

@app.route("/api/monetization/<email>")
def api_monetization(email):
    db = get_db()
    cur = get_cursor(db)
    
    cur.execute("SELECT COUNT(*) as cnt FROM followers WHERE user_email=?", (email,))
    followers = cur.fetchone()['cnt'] if cur.fetchone() else 0
    
    cur.execute("SELECT watch_hours, earnings FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    
    if user:
        return jsonify({
            "followers": followers,
            "watch_hours": user['watch_hours'],
            "earnings": user['earnings']
        })
    return jsonify({"followers": 0, "watch_hours": 0, "earnings": 0})

# ---------- Payouts ----------
@app.route("/api/payout-request", methods=["POST"])
def api_payout_request():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    om_number = data.get("om_number")
    amount = data.get("amount")
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("INSERT INTO payout_requests (user_email, om_number, amount) VALUES (?,?,?)", (email, om_number, amount))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/payout-requests")
def api_payout_requests():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT * FROM payout_requests WHERE user_email=? ORDER BY id DESC", (email,))
    return jsonify([dict(r) for r in cur.fetchall()])

# ---------- Ads / Campaigns ----------
@app.route("/api/ads", methods=["GET", "POST"])
def api_ads():
    db = get_db()
    cur = get_cursor(db)
    
    if request.method == "GET":
        cur.execute("SELECT * FROM ads WHERE approved=1 ORDER BY id DESC")
        return jsonify([dict(r) for r in cur.fetchall()])
    
    else:
        email = session.get("email")
        if not email:
            return jsonify({"error": "Not logged in"}), 401
        
        data = request.get_json() or {}
        title = data.get("title")
        budget = data.get("budget", 0)
        whatsapp = data.get("whatsapp", "")
        expires_at = data.get("expires_at")
        
        cur.execute("INSERT INTO ads (title, owner_email, budget, whatsapp, expires_at) VALUES (?,?,?,?,?)",
                   (title, email, budget, whatsapp, expires_at))
        db.commit()
        return jsonify({"success": True})

# ---------- File Upload ----------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    
    f = request.files['file']
    if f.filename == "":
        return jsonify({"error": "No filename"}), 400
    
    fn = f"{uuid.uuid4().hex}_{f.filename}"
    path = os.path.join(UPLOAD_DIR, fn)
    f.save(path)
    return jsonify({"url": f"/uploads/{fn}"})

# ---------- Admin Dashboard ----------
def render_admin_page():
    if not require_admin():
        return "Unauthorized", 403
    
    db = get_db()
    cur = get_cursor(db)
    
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    total_users = cur.fetchone()['cnt']
    
    cur.execute("SELECT COUNT(*) as cnt FROM posts")
    total_posts = cur.fetchone()['cnt']
    
    cur.execute("SELECT COUNT(*) as cnt FROM ads WHERE approved=0")
    pending_ads = cur.fetchone()['cnt']
    
    cur.execute("SELECT COUNT(*) as cnt FROM payout_requests WHERE status='pending'")
    pending_payouts = cur.fetchone()['cnt']
    
    cur.execute("SELECT COUNT(*) as cnt FROM reports WHERE status='pending'")
    pending_reports = cur.fetchone()['cnt']
    
    cur.execute("SELECT SUM(budget) as total FROM ads")
    total_earnings = cur.fetchone()['total'] or 0
    
    # Users table
    cur.execute("SELECT id, name, email, created_at FROM users LIMIT 100")
    users = cur.fetchall()
    user_rows = ""
    for u in users:
        user_rows += f"<tr><td style='padding:8px;border-bottom:1px solid rgba(255,255,255,0.1)'>{u['id']}</td><td>{u['name']}</td><td>{u['email']}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td><a href='/api/admin/user/ban' style='color:#4DF0C0'>Ban</a></td></tr>"
    
    # Ads table
    cur.execute("SELECT id, title, owner_email, budget FROM ads WHERE approved=0 LIMIT 50")
    ads = cur.fetchall()
    ad_rows = ""
    for a in ads:
        ad_rows += f"<tr><td style='padding:8px'>{a['id']}</td><td>{a['title']}</td><td>{a['owner_email']}</td><td>P{a['budget']}</td><td>-</td><td>-</td><td>Pending</td><td><a href='#' style='color:#4DF0C0'>Approve</a></td></tr>"
    
    # Payouts table
    cur.execute("SELECT id, user_email, om_number, amount FROM payout_requests WHERE status='pending' LIMIT 50")
    payouts = cur.fetchall()
    payout_rows = ""
    for p in payouts:
        payout_rows += f"<tr><td style='padding:8px'>{p['id']}</td><td>{p['user_email']}</td><td>{p['om_number']}</td><td>P{p['amount']}</td><td>Pending</td><td>-</td><td><a href='#' style='color:#4DF0C0'>Mark Paid</a></td></tr>"
    
    # Verified requests table
    cur.execute("SELECT id, user_name, user_email, status FROM verified_requests LIMIT 50")
    vreqs = cur.fetchall()
    vreq_rows = ""
    for v in vreqs:
        vreq_rows += f"<tr><td style='padding:8px'>{v['id']}</td><td>{v['user_name']}</td><td>{v['user_email']}</td><td>{v['status']}</td><td>-</td><td><a href='#' style='color:#4DF0C0'>Approve</a></td></tr>"
    
    # Reports table
    cur.execute("SELECT id, reporter_email, target_type, target_id, reason FROM reports WHERE status='pending' LIMIT 50")
    reports = cur.fetchall()
    report_rows = ""
    for r in reports:
        report_rows += f"<tr><td style='padding:8px'>{r['id']}</td><td>{r['reporter_email']}</td><td>-</td><td>{r['target_type']}#{r['target_id']}</td><td>{r['reason']}</td><td>-</td><td>Pending</td><td><a href='#' style='color:#4DF0C0'>Dismiss</a></td></tr>"
    
    TABLE = "width:100%;border-collapse:collapse;color:#e8f0ff;font-size:13px"
    TH = "background:#161b27;padding:10px;text-align:left;font-weight:600;border-bottom:2px solid #4DF0C0"
    
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VibeNet Admin</title>
<style>
:root{{--bg:#07101a;--accent:#4DF0C0}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);font-family:Inter,Arial,sans-serif;color:#e8f0ff;padding:20px}}
h1{{color:var(--accent);margin:0 0 8px}}
h2{{font-size:14px;color:#5a6a85;margin:0 0 24px}}
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:underline}}
.card{{background:#0d1117;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:20px;margin-bottom:24px}}
.stats{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
.stat{{background:#0d1117;border:1px solid rgba(77,240,192,0.15);border-radius:10px;padding:16px 20px;min-width:120px}}
.stat-val{{font-size:28px;font-weight:800;color:#4DF0C0}}.stat-label{{font-size:12px;color:#5a6a85;margin-top:4px}}
.section-title{{font-size:16px;font-weight:700;color:#e8f0ff;margin-bottom:16px}}
.overflow{{overflow-x:auto}}</style></head><body>
<h1>⚡ VibeNet Admin</h1>
<h2>Signed in as {ADMIN_EMAIL} · <a href="/" style="color:#4DF0C0">← Back to app</a></h2>

<div class="stats">
  <div class="stat"><div class="stat-val">{total_users}</div><div class="stat-label">Users</div></div>
  <div class="stat"><div class="stat-val">{total_posts}</div><div class="stat-label">Posts</div></div>
  <div class="stat"><div class="stat-val">{pending_ads}</div><div class="stat-label">Pending Ads</div></div>
  <div class="stat"><div class="stat-val">{pending_payouts}</div><div class="stat-label">Pending Payouts</div></div>
  <div class="stat"><div class="stat-val" style="color:{'#f06a4d' if pending_reports > 0 else '#4DF0C0'}">{pending_reports}</div><div class="stat-label">Pending Reports</div></div>
  <div class="stat"><div class="stat-val">P{total_earnings:.2f}</div><div class="stat-label">Total Budget</div></div>
</div>

<div class="card"><div class="section-title">👥 Users</div><div class="overflow"><table style="{TABLE}">
  <tr><th style="{TH}">ID</th><th style="{TH}">Name</th><th style="{TH}">Email</th><th style="{TH}">Posts</th>
  <th style="{TH}">Reactions</th><th style="{TH}">Followers</th><th style="{TH}">Watch Hrs</th>
  <th style="{TH}">Earnings</th><th style="{TH}">Last Active</th><th style="{TH}">Actions</th></tr>
  {user_rows}</table></div></div>

<div class="card"><div class="section-title">📢 Ad Campaigns</div><div class="overflow"><table style="{TABLE}">
  <tr><th style="{TH}">ID</th><th style="{TH}">Title</th><th style="{TH}">Owner</th>
  <th style="{TH}">Budget</th><th style="{TH}">WhatsApp</th><th style="{TH}">Expires</th><th style="{TH}">Status</th><th style="{TH}">Actions</th></tr>
  {ad_rows}</table></div></div>

<div class="card"><div class="section-title">💸 Payout Requests</div><div class="overflow"><table style="{TABLE}">
  <tr><th style="{TH}">ID</th><th style="{TH}">Email</th><th style="{TH}">OM Number</th>
  <th style="{TH}">Amount</th><th style="{TH}">Status</th><th style="{TH}">Date</th><th style="{TH}">Action</th></tr>
  {payout_rows}</table></div></div>

<div class="card"><div class="section-title">✦ Verified Badge Requests</div><div class="overflow"><table style="{TABLE}">
  <tr><th style="{TH}">ID</th><th style="{TH}">Name</th><th style="{TH}">Email</th>
  <th style="{TH}">Status</th><th style="{TH}">Date</th><th style="{TH}">Action</th></tr>
  {vreq_rows}</table></div></div>

<div class="card"><div class="section-title">⚑ Content Moderation Queue</div><div class="overflow"><table style="{TABLE}">
  <tr><th style="{TH}">ID</th><th style="{TH}">Reporter</th><th style="{TH}">Target</th>
  <th style="{TH}">Content</th><th style="{TH}">Reason</th><th style="{TH}">Date</th>
  <th style="{TH}">Status</th><th style="{TH}">Actions</th></tr>
  {report_rows}</table></div></div>
</body></html>"""
    
    return html

@app.route("/admin")
def admin():
    return render_admin_page()

@app.route("/api/admin/user/ban", methods=["POST"])
def api_admin_ban():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    
    data = request.get_json() or {}
    email = data.get("email")
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT banned FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    if not user:
        return jsonify({"error": "Not found"}), 404
    
    cur.execute("UPDATE users SET banned=? WHERE email=?", (0 if user['banned'] else 1, email))
    db.commit()
    return jsonify({"success": True})

# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"Starting VibeNet on port {app.config['PORT']}")
    print(f"Database type: {get_db_type().upper()}")
    print(f"Admin email: {ADMIN_EMAIL}")
    app.run(host="0.0.0.0", port=app.config['PORT'], debug=False)
