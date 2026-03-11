# VibeNet - No SQLAlchemy (Pure Flask + In-Memory Storage)
import os
import uuid
import json
from datetime import datetime
from flask import Flask, request, jsonify, session, render_template_string

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", "vibenet_secret_dev")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

# ========== IN-MEMORY STORAGE ==========
USERS = {}  # email -> {id, name, email, password, profile_pic, bio, watch_hours, earnings, verified, banned, created_at}
POSTS = {}  # post_id -> {id, author_email, author_name, text, file_url, timestamp, reactions, comments_count}
COMMENTS = {}  # comment_id -> {id, post_id, author_email, author_name, text, timestamp}
FOLLOWERS = {}  # (user_email, follower_email) -> True
REACTIONS = {}  # (user_email, post_id) -> emoji
NOTIFICATIONS = {}  # notif_id -> {id, user_email, text, timestamp, seen}
VERIFIED_REQUESTS = {}  # req_id -> {id, user_email, status, created_at}
PAYOUTS = {}  # payout_id -> {id, user_email, amount, status, payment_method, created_at}
CAMPAIGNS = {}  # campaign_id -> {id, advertiser_email, title, budget, impressions, clicks, status, created_at}
PAYMENTS = {}  # payment_id -> {id, user_email, campaign_id, amount, status, created_at}

# Counters
POST_ID = 1
COMMENT_ID = 1
NOTIF_ID = 1
REQ_ID = 1
PAYOUT_ID = 1
CAMPAIGN_ID = 1
PAYMENT_ID = 1

def now_ts():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

# ========== AUTH ==========
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    
    if email in USERS:
        return jsonify({"error": "User already exists"}), 400
    
    USERS[email] = {
        "id": len(USERS) + 1,
        "name": name,
        "email": email,
        "password": password,
        "profile_pic": "",
        "bio": "",
        "watch_hours": 0,
        "earnings": 0.0,
        "verified": False,
        "banned": False,
        "created_at": now_ts()
    }
    
    session["user_email"] = email
    return jsonify({"success": True, "user": USERS[email]}), 201

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    
    user = USERS.get(email)
    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401
    
    if user.get("banned"):
        return jsonify({"error": "Account banned"}), 403
    
    session["user_email"] = email
    return jsonify({"user": user})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "logged out"})

@app.route("/api/me")
def api_me():
    email = session.get("user_email")
    if not email or email not in USERS:
        return jsonify({"user": None})
    return jsonify({"user": USERS[email]})

# ========== POSTS ==========
@app.route("/api/posts", methods=["GET", "POST"])
def api_posts():
    global POST_ID
    
    if request.method == "GET":
        posts = list(POSTS.values())
        return jsonify(sorted(posts, key=lambda x: x["timestamp"], reverse=True))
    
    data = request.get_json() or {}
    author_email = data.get("author_email")
    author_name = data.get("author_name")
    text = data.get("text", "")
    file_url = data.get("file_url", "")
    
    if not author_email:
        return jsonify({"error": "Not logged in"}), 401
    
    post = {
        "id": POST_ID,
        "author_email": author_email,
        "author_name": author_name,
        "text": text,
        "file_url": file_url,
        "timestamp": now_ts(),
        "reactions": {"👍": 0, "❤️": 0, "😂": 0},
        "comments_count": 0,
        "verified": USERS.get(author_email, {}).get("verified", False)
    }
    
    POSTS[POST_ID] = post
    POST_ID += 1
    
    return jsonify(post), 201

@app.route("/api/posts/<int:post_id>", methods=["DELETE"])
def delete_post(post_id):
    if post_id not in POSTS:
        return jsonify({"error": "Post not found"}), 404
    
    post = POSTS[post_id]
    email = session.get("user_email")
    
    if post["author_email"] != email:
        return jsonify({"error": "Unauthorized"}), 403
    
    del POSTS[post_id]
    return jsonify({"success": True})

# ========== COMMENTS ==========
@app.route("/api/posts/<int:post_id>/comments", methods=["GET", "POST"])
def api_comments(post_id):
    global COMMENT_ID
    
    if request.method == "GET":
        return jsonify([c for c in COMMENTS.values() if c["post_id"] == post_id])
    
    data = request.get_json() or {}
    author_email = data.get("author_email")
    author_name = data.get("author_name")
    text = data.get("text", "")
    
    if not author_email:
        return jsonify({"error": "Not logged in"}), 401
    
    if post_id not in POSTS:
        return jsonify({"error": "Post not found"}), 404
    
    comment = {
        "id": COMMENT_ID,
        "post_id": post_id,
        "author_email": author_email,
        "author_name": author_name,
        "text": text,
        "timestamp": now_ts()
    }
    
    COMMENTS[COMMENT_ID] = comment
    POSTS[post_id]["comments_count"] = POSTS[post_id].get("comments_count", 0) + 1
    COMMENT_ID += 1
    
    return jsonify(comment), 201

# ========== REACTIONS ==========
@app.route("/api/react", methods=["POST"])
def api_react():
    data = request.get_json() or {}
    post_id = data.get("post_id")
    emoji = data.get("emoji")
    user_email = data.get("user_email")
    
    if post_id not in POSTS:
        return jsonify({"error": "Post not found"}), 404
    
    key = (user_email, post_id)
    old_emoji = REACTIONS.get(key)
    
    if old_emoji:
        POSTS[post_id]["reactions"][old_emoji] = max(0, POSTS[post_id]["reactions"][old_emoji] - 1)
    
    REACTIONS[key] = emoji
    POSTS[post_id]["reactions"][emoji] = POSTS[post_id]["reactions"].get(emoji, 0) + 1
    
    return jsonify({"success": True, "reactions": POSTS[post_id]["reactions"]})

# ========== FOLLOW ==========
@app.route("/api/follow", methods=["POST"])
def api_follow():
    data = request.get_json() or {}
    user_email = data.get("user_email")
    follower_email = data.get("follower_email")
    
    key = (user_email, follower_email)
    
    if key in FOLLOWERS:
        del FOLLOWERS[key]
        return jsonify({"status": "unfollowed"})
    else:
        FOLLOWERS[key] = True
        return jsonify({"status": "followed"})

@app.route("/api/is_following")
def is_following():
    user = request.args.get("user")
    follower = request.args.get("follower")
    following = (user, follower) in FOLLOWERS
    return jsonify({"following": following})

# ========== PROFILE ==========
@app.route("/api/profile/<email>")
def profile(email):
    user = USERS.get(email)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user)

@app.route("/api/update_bio", methods=["POST"])
def update_bio():
    email = session.get("user_email")
    if not email or email not in USERS:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    bio = data.get("bio", "")
    
    USERS[email]["bio"] = bio
    return jsonify({"success": True, "user": USERS[email]})

# ========== NOTIFICATIONS ==========
@app.route("/api/notifications/<email>")
def get_notifications(email):
    if session.get("user_email") != email:
        return jsonify({"error": "Unauthorized"}), 403
    
    notifs = [n for n in NOTIFICATIONS.values() if n["user_email"] == email]
    return jsonify(sorted(notifs, key=lambda x: x["timestamp"], reverse=True))

@app.route("/api/notifications/<int:notif_id>/mark_seen", methods=["POST"])
def mark_seen(notif_id):
    if notif_id in NOTIFICATIONS:
        NOTIFICATIONS[notif_id]["seen"] = True
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

# ========== MONETIZATION ==========
@app.route("/api/watch", methods=["POST"])
def watch_video():
    data = request.get_json() or {}
    author_email = data.get("author_email")
    watch_seconds = data.get("watch_seconds", 0)
    
    if author_email and author_email in USERS:
        watch_hours = watch_seconds / 3600
        USERS[author_email]["watch_hours"] += watch_hours
        USERS[author_email]["earnings"] += watch_hours * 0.10  # P0.10 per hour
        
        return jsonify({"success": True, "earnings": USERS[author_email]["earnings"]})
    
    return jsonify({"error": "User not found"}), 404

@app.route("/api/earnings/<email>")
def get_earnings(email):
    if session.get("user_email") != email:
        return jsonify({"error": "Unauthorized"}), 403
    
    user = USERS.get(email)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "watch_hours": user["watch_hours"],
        "earnings": user["earnings"],
        "verified": user["verified"]
    })

# ========== VERIFIED BADGES ==========
@app.route("/api/verified-badge/request", methods=["POST"])
def request_verified():
    global REQ_ID
    
    email = session.get("user_email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    if USERS.get(email, {}).get("verified"):
        return jsonify({"error": "Already verified"}), 400
    
    existing = [r for r in VERIFIED_REQUESTS.values() if r["user_email"] == email and r["status"] == "pending"]
    if existing:
        return jsonify({"error": "Already requested"}), 400
    
    VERIFIED_REQUESTS[REQ_ID] = {
        "id": REQ_ID,
        "user_email": email,
        "status": "pending",
        "created_at": now_ts()
    }
    REQ_ID += 1
    
    return jsonify({"success": True, "message": "Verified badge request submitted"})

@app.route("/api/verified-status")
def verified_status():
    email = session.get("user_email")
    if not email:
        return jsonify({"verified": False})
    
    user = USERS.get(email)
    return jsonify({"verified": user.get("verified", False) if user else False})

# ========== PAYOUTS ==========
@app.route("/api/payout-request", methods=["POST"])
def payout_request():
    global PAYOUT_ID
    
    email = session.get("user_email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    amount = data.get("amount")
    orange_money = data.get("orange_money", "")
    
    if not amount or amount < 10:
        return jsonify({"error": "Minimum payout is P10"}), 400
    
    user = USERS.get(email)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    if user["earnings"] < amount:
        return jsonify({"error": "Insufficient earnings"}), 400
    
    PAYOUTS[PAYOUT_ID] = {
        "id": PAYOUT_ID,
        "user_email": email,
        "amount": amount,
        "status": "pending",
        "payment_method": "orange_money",
        "payment_details": orange_money,
        "created_at": now_ts()
    }
    PAYOUT_ID += 1
    
    return jsonify({"success": True, "message": "Payout request submitted"})

@app.route("/api/payout-history")
def payout_history():
    email = session.get("user_email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    payouts = [p for p in PAYOUTS.values() if p["user_email"] == email]
    return jsonify(sorted(payouts, key=lambda x: x["created_at"], reverse=True))

# ========== CAMPAIGNS/ADS ==========
@app.route("/api/campaigns", methods=["GET", "POST"])
def api_campaigns():
    global CAMPAIGN_ID
    
    if request.method == "GET":
        return jsonify(list(CAMPAIGNS.values()))
    
    data = request.get_json() or {}
    advertiser_email = data.get("advertiser_email")
    title = data.get("title", "")
    budget = data.get("budget", 0)
    
    if not advertiser_email:
        return jsonify({"error": "Not logged in"}), 401
    
    CAMPAIGNS[CAMPAIGN_ID] = {
        "id": CAMPAIGN_ID,
        "advertiser_email": advertiser_email,
        "title": title,
        "budget": budget,
        "impressions": 0,
        "clicks": 0,
        "status": "active",
        "created_at": now_ts()
    }
    CAMPAIGN_ID += 1
    
    return jsonify(CAMPAIGNS[CAMPAIGN_ID - 1]), 201

@app.route("/api/campaigns/<int:campaign_id>/impression", methods=["POST"])
def campaign_impression(campaign_id):
    if campaign_id in CAMPAIGNS:
        CAMPAIGNS[campaign_id]["impressions"] += 1
        return jsonify({"success": True})
    return jsonify({"error": "Campaign not found"}), 404

@app.route("/api/campaigns/<int:campaign_id>/click", methods=["POST"])
def campaign_click(campaign_id):
    if campaign_id in CAMPAIGNS:
        CAMPAIGNS[campaign_id]["clicks"] += 1
        return jsonify({"success": True})
    return jsonify({"error": "Campaign not found"}), 404

# ========== ADMIN ==========
@app.route("/admin")
def admin_dashboard():
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    
    if session.get("user_email") != admin_email:
        return jsonify({"error": "Unauthorized"}), 403
    
    total_earnings = sum(u["earnings"] for u in USERS.values())
    pending_verified = [r for r in VERIFIED_REQUESTS.values() if r["status"] == "pending"]
    pending_payouts = [p for p in PAYOUTS.values() if p["status"] == "pending"]
    
    return jsonify({
        "stats": {
            "total_users": len(USERS),
            "total_posts": len(POSTS),
            "total_earnings": total_earnings
        },
        "pending": {
            "verified": pending_verified,
            "payouts": pending_payouts
        }
    })

@app.route("/api/admin/verified/<int:req_id>/approve", methods=["POST"])
def approve_verified(req_id):
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    if session.get("user_email") != admin_email:
        return jsonify({"error": "Unauthorized"}), 403
    
    if req_id in VERIFIED_REQUESTS:
        user_email = VERIFIED_REQUESTS[req_id]["user_email"]
        VERIFIED_REQUESTS[req_id]["status"] = "approved"
        if user_email in USERS:
            USERS[user_email]["verified"] = True
        return jsonify({"success": True})
    
    return jsonify({"error": "Not found"}), 404

@app.route("/api/admin/payout/<int:payout_id>/approve", methods=["POST"])
def approve_payout(payout_id):
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    if session.get("user_email") != admin_email:
        return jsonify({"error": "Unauthorized"}), 403
    
    if payout_id in PAYOUTS:
        PAYOUTS[payout_id]["status"] = "approved"
        return jsonify({"success": True})
    
    return jsonify({"error": "Not found"}), 404

# ========== FAVICON ==========
@app.route("/favicon.ico")
def favicon():
    return "", 204

# ========== MAIN PAGE ==========
@app.route("/")
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>VibeNet</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background: #0d1117;
                color: #c8d8f0;
                padding: 20px;
            }
            .container {
                max-width: 600px;
                margin: 0 auto;
            }
            .auth-form {
                background: #161b22;
                border-radius: 12px;
                padding: 30px;
                border: 1px solid #30363d;
                display: none;
            }
            .auth-form.active { display: block; }
            h1 { text-align: center; margin-bottom: 30px; color: #4DF0C0; }
            .field { margin-bottom: 15px; }
            label {
                display: block;
                font-size: 12px;
                color: #8899b4;
                margin-bottom: 5px;
                font-weight: 600;
            }
            input {
                width: 100%;
                padding: 10px;
                border: 1px solid #30363d;
                border-radius: 8px;
                background: #0d1117;
                color: #c8d8f0;
                font-size: 14px;
            }
            button {
                width: 100%;
                padding: 12px;
                background: #4DF0C0;
                color: #0d1117;
                border: none;
                border-radius: 8px;
                font-weight: 700;
                cursor: pointer;
                margin-top: 10px;
            }
            button:hover { opacity: 0.9; }
            .tabs {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
            }
            .tab-btn {
                flex: 1;
                padding: 12px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                background: transparent;
                color: #8899b4;
            }
            .tab-btn.active {
                background: #4DF0C0;
                color: #0d1117;
            }
            .link { text-align: center; margin-top: 15px; font-size: 12px; }
            .link a { color: #4DF0C0; cursor: pointer; text-decoration: none; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="tabs">
                <button class="tab-btn active" onclick="showTab('signup')">Create Account</button>
                <button class="tab-btn" onclick="showTab('login')">Sign In</button>
            </div>

            <div id="signup-form" class="auth-form active">
                <h1>Create Account</h1>
                <div class="field">
                    <label>Full Name</label>
                    <input type="text" id="signup-name" placeholder="Your name">
                </div>
                <div class="field">
                    <label>Email</label>
                    <input type="email" id="signup-email" placeholder="you@email.com">
                </div>
                <div class="field">
                    <label>Password</label>
                    <input type="password" id="signup-password" placeholder="••••••••">
                </div>
                <button onclick="signup()">Create Account →</button>
                <div class="link">Already have an account? <a onclick="showTab('login')">Sign In</a></div>
            </div>

            <div id="login-form" class="auth-form">
                <h1>Sign In</h1>
                <div class="field">
                    <label>Email</label>
                    <input type="email" id="login-email" placeholder="you@email.com">
                </div>
                <div class="field">
                    <label>Password</label>
                    <input type="password" id="login-password" placeholder="••••••••">
                </div>
                <button onclick="login()">Sign In →</button>
                <div class="link">Don't have an account? <a onclick="showTab('signup')">Create one</a></div>
            </div>
        </div>

        <script>
        const API = '/api';
        
        function showTab(tab) {
            document.querySelectorAll('.auth-form').forEach(f => f.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            
            if (tab === 'signup') {
                document.getElementById('signup-form').classList.add('active');
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
            } else {
                document.getElementById('login-form').classList.add('active');
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
            }
        }

        async function signup() {
            const name = document.getElementById('signup-name').value.trim();
            const email = document.getElementById('signup-email').value.trim().toLowerCase();
            const password = document.getElementById('signup-password').value;
            
            if (!name || !email || !password) {
                alert('Fill all fields');
                return;
            }
            
            const res = await fetch(API + '/signup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name, email, password})
            });
            const j = await res.json();
            
            if (j.success) {
                alert('Account created!');
                window.location.href = '/feed';
            } else {
                alert('Error: ' + (j.error || 'Signup failed'));
            }
        }

        async function login() {
            const email = document.getElementById('login-email').value.trim().toLowerCase();
            const password = document.getElementById('login-password').value;
            
            if (!email || !password) {
                alert('Fill all fields');
                return;
            }
            
            const res = await fetch(API + '/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email, password})
            });
            const j = await res.json();
            
            if (j.user) {
                alert('Logged in!');
                window.location.href = '/feed';
            } else {
                alert('Invalid credentials');
            }
        }
        </script>
    </body>
    </html>
    """)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
