# app.py - VibeNet  (SQLAlchemy ORM  |  SQLite locally  |  PostgreSQL on Render)
import os
import uuid
import datetime
import json as _json
from flask import Flask, request, jsonify, send_from_directory, session, render_template_string

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

# ---------- Config ----------
APP_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
app.config["PORT"] = int(os.environ.get("PORT", 5000))
app.secret_key = os.environ.get("SECRET_KEY", "vibenet_secret_dev")

# SQLAlchemy: prefer DATABASE_URL env var (Render PostgreSQL), fall back to SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):          # Render uses legacy scheme
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    DATABASE_URL if DATABASE_URL
    else f"sqlite:///{os.path.join(APP_DIR, 'data', 'vibenet.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 280,   # keep Render/Postgres connections alive
    "pool_pre_ping": True,
}

os.makedirs(os.path.join(APP_DIR, "data"), exist_ok=True)

db = SQLAlchemy(app)

# ---------- Utilities ----------
def now_ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

# ---------- Models ----------

class User(db.Model):
    __tablename__ = "users"
    id                = db.Column(db.Integer, primary_key=True)
    name              = db.Column(db.Text)
    email             = db.Column(db.Text, unique=True, nullable=False)
    password          = db.Column(db.Text, nullable=False)
    profile_pic       = db.Column(db.Text, default="")
    bio               = db.Column(db.Text, default="")
    watch_hours       = db.Column(db.Integer, default=0)
    earnings          = db.Column(db.Float, default=0.0)
    verified          = db.Column(db.Integer, default=0)   # 1 = VibeNet Verified
    created_at        = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "email": self.email,
            "profile_pic": self.profile_pic, "bio": self.bio,
            "watch_hours": self.watch_hours, "earnings": self.earnings,
            "verified": bool(self.verified),
        }


class UserWallet(db.Model):
    __tablename__ = "user_wallets"
    id                = db.Column(db.Integer, primary_key=True)
    user_email        = db.Column(db.Text, db.ForeignKey("users.email"), nullable=False, unique=True)
    wallet_type       = db.Column(db.Text, default="orange_money")  # orange_money, stripe, paypal, etc.
    account_number    = db.Column(db.Text, nullable=False)  # Orange Money phone number or account ID
    account_holder    = db.Column(db.Text)  # Name of account holder
    verified          = db.Column(db.Integer, default=0)  # 0 = unverified, 1 = verified
    balance           = db.Column(db.Float, default=0.0)  # Current balance
    total_received    = db.Column(db.Float, default=0.0)  # Total earnings received
    created_at        = db.Column(db.Text, default=lambda: now_ts())
    verified_at       = db.Column(db.Text, nullable=True)
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_email": self.user_email,
            "wallet_type": self.wallet_type,
            "account_number": self.account_number,
            "account_holder": self.account_holder,
            "verified": bool(self.verified),
            "balance": round(self.balance, 2),
            "total_received": round(self.total_received, 2),
            "created_at": self.created_at,
            "verified_at": self.verified_at,
        }


class Follower(db.Model):
    __tablename__ = "followers"
    id             = db.Column(db.Integer, primary_key=True)
    user_email     = db.Column(db.Text, nullable=False)   # the person being followed
    follower_email = db.Column(db.Text, nullable=False)   # the person who follows
    created_at     = db.Column(db.Text, default=lambda: now_ts())
    __table_args__ = (
        db.UniqueConstraint("user_email", "follower_email", name="uq_follow"),
    )


class Post(db.Model):
    __tablename__  = "posts"
    id             = db.Column(db.Integer, primary_key=True)
    author_email   = db.Column(db.Text, nullable=False)
    author_name    = db.Column(db.Text)
    profile_pic    = db.Column(db.Text, default="")
    text           = db.Column(db.Text, default="")
    file_url       = db.Column(db.Text, default="")
    timestamp      = db.Column(db.Text, default=lambda: now_ts())
    reactions_json = db.Column(db.Text, default='{"👍":0,"❤️":0,"😂":0}')
    comments_count = db.Column(db.Integer, default=0)

    def reactions(self):
        try:
            return _json.loads(self.reactions_json or "{}")
        except Exception:
            return {"👍": 0, "❤️": 0, "😂": 0}

    def to_dict(self, user_reaction=None, author_verified=False):
        return {
            "id": self.id, "author_email": self.author_email,
            "author_name": self.author_name, "profile_pic": self.profile_pic,
            "text": self.text, "file_url": self.file_url,
            "timestamp": self.timestamp, "reactions": self.reactions(),
            "comments_count": self.comments_count,
            "user_reaction": user_reaction,
            "author_verified": author_verified,
        }


class UserReaction(db.Model):
    __tablename__ = "user_reactions"
    id         = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.Text, nullable=False)
    post_id    = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    emoji      = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.Text, default=lambda: now_ts())
    __table_args__ = (
        db.UniqueConstraint("user_email", "post_id", name="uq_reaction"),
    )


class Notification(db.Model):
    __tablename__ = "notifications"
    id         = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.Text, nullable=False)
    text       = db.Column(db.Text)
    timestamp  = db.Column(db.Text, default=lambda: now_ts())
    seen       = db.Column(db.Integer, default=0)
    seen_at    = db.Column(db.Text, nullable=True)  # Track when notification was seen
    auto_dismiss = db.Column(db.Integer, default=1)  # Auto-dismiss after being seen

    def to_dict(self):
        return {
            "id": self.id,
            "text": self.text,
            "timestamp": self.timestamp,
            "seen": self.seen,
            "seen_at": self.seen_at,
            "auto_dismiss": bool(self.auto_dismiss),
            "ready_to_dismiss": bool(self.seen) and self.auto_dismiss == 1
        }


class Ad(db.Model):
    __tablename__ = "ads"
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.Text)
    owner_email = db.Column(db.Text)
    budget      = db.Column(db.Float, default=0.0)
    impressions = db.Column(db.Integer, default=0)
    clicks      = db.Column(db.Integer, default=0)
    created_at  = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "owner_email": self.owner_email,
            "budget": self.budget, "impressions": self.impressions, "clicks": self.clicks,
        }


class Comment(db.Model):
    __tablename__ = "comments"
    id           = db.Column(db.Integer, primary_key=True)
    post_id      = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    author_email = db.Column(db.Text, nullable=False)
    author_name  = db.Column(db.Text)
    profile_pic  = db.Column(db.Text, default="")
    text         = db.Column(db.Text, nullable=False)
    timestamp    = db.Column(db.Text, default=lambda: now_ts())
    created_at   = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self, author_verified=False):
        return {
            "id": self.id,
            "post_id": self.post_id,
            "author_email": self.author_email,
            "author_name": self.author_name,
            "profile_pic": self.profile_pic,
            "text": self.text,
            "timestamp": self.timestamp,
            "author_verified": author_verified,
        }


class PaidCampaign(db.Model):
    __tablename__ = "paid_campaigns"
    id              = db.Column(db.Integer, primary_key=True)
    owner_email     = db.Column(db.Text, nullable=False)
    title           = db.Column(db.Text, nullable=False)
    description     = db.Column(db.Text, default="")
    budget          = db.Column(db.Float, default=0.0)
    spent           = db.Column(db.Float, default=0.0)
    status          = db.Column(db.Text, default="pending")  # pending, active, paused, completed, expired
    payment_status  = db.Column(db.Text, default="unpaid")   # unpaid, paid, failed, refunded
    impressions     = db.Column(db.Integer, default=0)
    clicks          = db.Column(db.Integer, default=0)
    conversions     = db.Column(db.Integer, default=0)
    target_audience = db.Column(db.Text, default="")  # e.g., "age:18-35, interests:tech"
    cpc             = db.Column(db.Float, default=0.5)  # Cost Per Click
    cpm             = db.Column(db.Float, default=2.0)  # Cost Per Mille (1000 impressions)
    created_at      = db.Column(db.Text, default=lambda: now_ts())
    updated_at      = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        roi = 0.0
        if self.spent > 0 and self.conversions > 0:
            roi = ((self.conversions * 10) - self.spent) / self.spent * 100  # Assume $10 per conversion
        
        return {
            "id": self.id,
            "owner_email": self.owner_email,
            "title": self.title,
            "description": self.description,
            "budget": self.budget,
            "spent": round(self.spent, 2),
            "status": self.status,
            "payment_status": self.payment_status,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "conversions": self.conversions,
            "ctr": round((self.clicks / self.impressions * 100), 2) if self.impressions > 0 else 0,  # Click-Through Rate
            "cpc": self.cpc,
            "cpm": self.cpm,
            "target_audience": self.target_audience,
            "roi": round(roi, 2),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Payment(db.Model):
    __tablename__ = "payments"
    id              = db.Column(db.Integer, primary_key=True)
    user_email      = db.Column(db.Text, nullable=False)
    campaign_id     = db.Column(db.Integer, db.ForeignKey("paid_campaigns.id"), nullable=False)
    amount          = db.Column(db.Float, nullable=False)
    status          = db.Column(db.Text, default="pending")  # pending, completed, failed, refunded
    payment_method  = db.Column(db.Text)  # stripe, paypal, credit_card, etc.
    transaction_id  = db.Column(db.Text, unique=True)  # External payment processor ID
    description     = db.Column(db.Text, default="")
    created_at      = db.Column(db.Text, default=lambda: now_ts())
    completed_at    = db.Column(db.Text, nullable=True)
    refunded_at     = db.Column(db.Text, nullable=True)
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_email": self.user_email,
            "campaign_id": self.campaign_id,
            "amount": round(self.amount, 2),
            "status": self.status,
            "payment_method": self.payment_method,
            "transaction_id": self.transaction_id,
            "description": self.description,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "refunded_at": self.refunded_at,
        }


class OrangeMoneyAccount(db.Model):
    __tablename__ = "orange_money_accounts"
    id              = db.Column(db.Integer, primary_key=True)
    user_email      = db.Column(db.Text, unique=True, nullable=False)
    phone_number    = db.Column(db.Text, nullable=False)  # Orange Money phone number
    account_holder  = db.Column(db.Text, nullable=False)  # Name of account holder
    country         = db.Column(db.Text, default="")  # Country code (e.g., SN, CI, CM, etc.)
    is_verified     = db.Column(db.Integer, default=0)  # 1 = verified account
    created_at      = db.Column(db.Text, default=lambda: now_ts())
    verified_at     = db.Column(db.Text, nullable=True)
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_email": self.user_email,
            "phone_number": self.phone_number,
            "account_holder": self.account_holder,
            "country": self.country,
            "is_verified": bool(self.is_verified),
            "created_at": self.created_at,
            "verified_at": self.verified_at,
        }


class Payout(db.Model):
    __tablename__ = "payouts"
    id                  = db.Column(db.Integer, primary_key=True)
    user_email          = db.Column(db.Text, nullable=False)
    orange_account_id   = db.Column(db.Integer, db.ForeignKey("orange_money_accounts.id"), nullable=False)
    campaign_id         = db.Column(db.Integer, db.ForeignKey("paid_campaigns.id"), nullable=True)  # Optional: from specific campaign
    amount              = db.Column(db.Float, nullable=False)
    status              = db.Column(db.Text, default="pending")  # pending, processing, completed, failed
    payout_type         = db.Column(db.Text, default="campaign_earnings")  # campaign_earnings, withdrawal, bonus, etc.
    transaction_id      = db.Column(db.Text, unique=True)  # Orange Money transaction ID
    description         = db.Column(db.Text, default="")
    created_at          = db.Column(db.Text, default=lambda: now_ts())
    processed_at        = db.Column(db.Text, nullable=True)
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_email": self.user_email,
            "orange_account_id": self.orange_account_id,
            "campaign_id": self.campaign_id,
            "amount": round(self.amount, 2),
            "status": self.status,
            "payout_type": self.payout_type,
            "transaction_id": self.transaction_id,
            "description": self.description,
            "created_at": self.created_at,
            "processed_at": self.processed_at,
        }


class UserEarnings(db.Model):
    __tablename__ = "user_earnings"
    id              = db.Column(db.Integer, primary_key=True)
    user_email      = db.Column(db.Text, unique=True, nullable=False)
    total_earned    = db.Column(db.Float, default=0.0)  # Total from all campaigns
    total_paid_out  = db.Column(db.Float, default=0.0)  # Total paid to Orange Money
    balance         = db.Column(db.Float, default=0.0)  # earned - paid_out
    last_updated    = db.Column(db.Text, default=lambda: now_ts())
    
    def to_dict(self):
        return {
            "user_email": self.user_email,
            "total_earned": round(self.total_earned, 2),
            "total_paid_out": round(self.total_paid_out, 2),
            "balance": round(self.balance, 2),
            "last_updated": self.last_updated,
        }


# ---------- Create tables ----------
with app.app_context():
    db.create_all()

# ---------- Static uploads ----------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------- Frontend ----------
HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>VibeNet</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;1,300&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #060910;
  --surface: #0c1018;
  --card: #101520;
  --card2: #131925;
  --border: rgba(255,255,255,0.06);
  --accent: #4DF0C0;
  --accent2: #7B6EF6;
  --accent3: #F06A4D;
  --text: #E8F0FF;
  --muted: #5A6A85;
  --muted2: #8899B4;
  --danger: #F06A4D;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  font-family: 'DM Sans', sans-serif;
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

body::before {
  content: '';
  position: fixed;
  top: -40%;
  left: -20%;
  width: 70%;
  height: 70%;
  background: radial-gradient(ellipse, rgba(77,240,192,0.04) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}
body::after {
  content: '';
  position: fixed;
  bottom: -30%;
  right: -10%;
  width: 60%;
  height: 60%;
  background: radial-gradient(ellipse, rgba(123,110,246,0.05) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

/* ===== AUTH SCREEN ===== */
#authScreen {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  background: var(--bg);
  padding: 20px;
}

.auth-wrap {
  width: 100%;
  max-width: 900px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
  background: var(--border);
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 40px 120px rgba(0,0,0,0.8);
  animation: fadeUp 0.5s ease both;
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(24px); }
  to   { opacity: 1; transform: translateY(0); }
}

.auth-brand {
  background: linear-gradient(145deg, #0d1826, #080f1a);
  padding: 52px 44px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.auth-brand::before {
  content: 'VN';
  position: absolute;
  bottom: -30px;
  right: -20px;
  font-family: 'Syne', sans-serif;
  font-size: 160px;
  font-weight: 800;
  color: rgba(77,240,192,0.04);
  line-height: 1;
  letter-spacing: -8px;
}

.brand-logo {
  font-family: 'Syne', sans-serif;
  font-size: 38px;
  font-weight: 800;
  color: var(--accent);
  letter-spacing: -1px;
  margin-bottom: 16px;
}

.brand-tag {
  font-size: 15px;
  color: var(--muted2);
  line-height: 1.6;
  max-width: 240px;
}

.brand-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 32px;
}

.pill {
  background: rgba(77,240,192,0.08);
  border: 1px solid rgba(77,240,192,0.15);
  color: var(--accent);
  padding: 5px 12px;
  border-radius: 100px;
  font-size: 12px;
  font-weight: 500;
}

.auth-forms {
  background: var(--card);
  padding: 44px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.auth-section h3 {
  font-family: 'Syne', sans-serif;
  font-size: 17px;
  font-weight: 700;
  margin-bottom: 16px;
  color: var(--text);
  letter-spacing: -0.3px;
}

.field {
  margin-bottom: 10px;
}

.field input {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  transition: border-color 0.2s;
  outline: none;
}

.field input:focus {
  border-color: rgba(77,240,192,0.4);
}

.field input::placeholder { color: var(--muted); }

.field-label {
  font-size: 12px;
  color: var(--muted2);
  margin-bottom: 6px;
  font-weight: 500;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.divider {
  height: 1px;
  background: var(--border);
}

/* Buttons */
.btn-primary {
  background: var(--accent);
  color: #030a0e;
  border: none;
  padding: 11px 22px;
  border-radius: 10px;
  font-family: 'Syne', sans-serif;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  letter-spacing: 0.2px;
}
.btn-primary:hover { background: #6bf5d0; transform: translateY(-1px); }

.btn-ghost {
  background: transparent;
  color: var(--muted2);
  border: 1px solid var(--border);
  padding: 10px 20px;
  border-radius: 10px;
  font-family: 'DM Sans', sans-serif;
  font-weight: 500;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-ghost:hover { border-color: rgba(255,255,255,0.2); color: var(--text); }

.btn-icon {
  background: var(--card2);
  border: 1px solid var(--border);
  color: var(--muted2);
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}
.btn-icon:hover { border-color: var(--accent); color: var(--accent); }

/* ===== MAIN APP ===== */
#mainApp {
  display: none;
  min-height: 100vh;
  position: relative;
  z-index: 1;
}

/* Top Nav */
.topnav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(6,9,16,0.92);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 0 20px;
  height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.nav-brand {
  font-family: 'Syne', sans-serif;
  font-size: 20px;
  font-weight: 800;
  color: var(--accent);
  letter-spacing: -0.5px;
  flex-shrink: 0;
}

.nav-tabs {
  display: flex;
  gap: 2px;
  background: var(--surface);
  padding: 4px;
  border-radius: 12px;
  border: 1px solid var(--border);
  flex-shrink: 0;
}

.nav-tab {
  background: transparent;
  border: none;
  color: var(--muted2);
  padding: 7px 14px;
  border-radius: 9px;
  font-family: 'DM Sans', sans-serif;
  font-weight: 500;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  position: relative;
}

.nav-tab:hover { color: var(--text); background: rgba(255,255,255,0.04); }
.nav-tab.active { background: var(--card2); color: var(--text); }
.nav-tab.active::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 50%;
  transform: translateX(-50%);
  width: 16px;
  height: 2px;
  background: var(--accent);
  border-radius: 2px;
}

.notif-dot {
  background: var(--danger);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 100px;
  line-height: 16px;
  min-width: 16px;
  text-align: center;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.nav-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
  border: 2px solid var(--border);
  cursor: pointer;
}

.nav-signout {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--muted2);
  width: 32px;
  height: 32px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.nav-signout:hover { border-color: rgba(240,106,77,0.5); color: var(--danger); background: rgba(240,106,77,0.07); }

/* ===== USER PANEL (below header, in sidebar) ===== */
.user-panel {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.user-panel-top {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 14px;
}

.user-panel-avatar {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
  border: 2px solid rgba(77,240,192,0.25);
  flex-shrink: 0;
}

.user-panel-name {
  font-family: 'Syne', sans-serif;
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}

.user-panel-email {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}

.user-panel-bio {
  font-size: 13px;
  color: var(--muted2);
  line-height: 1.5;
  margin-bottom: 14px;
  min-height: 18px;
}

.user-panel-actions {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.panel-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--muted2);
  padding: 9px 14px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  font-family: 'DM Sans', sans-serif;
}
.panel-btn:hover { border-color: rgba(77,240,192,0.3); color: var(--accent); background: rgba(77,240,192,0.04); }
.panel-btn.signout { color: var(--muted); }
.panel-btn.signout:hover { border-color: rgba(240,106,77,0.4); color: var(--danger); background: rgba(240,106,77,0.06); }

/* ===== LAYOUT ===== */
.app-layout {
  max-width: 680px;
  margin: 0 auto;
  padding: 28px 16px;
}

.main-col { min-width: 0; }

/* ===== TABS ===== */
.tab { display: none; animation: fadeIn 0.25s ease; }
.tab.visible { display: block; }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ===== POST COMPOSER ===== */
.composer {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 20px;
}

.composer-top {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.composer-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
  flex-shrink: 0;
}

.composer textarea {
  flex: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 16px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14.5px;
  resize: none;
  outline: none;
  transition: border-color 0.2s;
  min-height: 80px;
}
.composer textarea:focus { border-color: rgba(77,240,192,0.3); }
.composer textarea::placeholder { color: var(--muted); }

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.composer-actions { display: flex; gap: 8px; align-items: center; }

.attach-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted2);
  font-size: 13px;
  cursor: pointer;
  padding: 7px 12px;
  border-radius: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  transition: all 0.2s;
}
.attach-label:hover { border-color: rgba(77,240,192,0.3); color: var(--accent); }
.attach-label input { display: none; }

/* ===== POSTS ===== */
.post-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 16px;
  transition: border-color 0.2s;
}
.post-card:hover { border-color: rgba(255,255,255,0.1); }

.post-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.post-author {
  display: flex;
  gap: 10px;
  align-items: center;
}

.post-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
}

.post-author-info strong {
  display: block;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--text);
}

.post-ts {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}

.post-text {
  font-size: 15px;
  line-height: 1.65;
  color: #cad8f0;
  margin-bottom: 12px;
}

.post-media {
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 12px;
}
.post-media img, .post-media video {
  width: 100%;
  display: block;
  max-height: 460px;
  object-fit: cover;
  background: #000;
}

.post-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.reaction-bar { display: flex; gap: 6px; }

.react-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--muted2);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 4px;
}
.react-btn:hover { border-color: rgba(255,255,255,0.2); color: var(--text); }
.react-btn.active { background: rgba(77,240,192,0.1); border-color: rgba(77,240,192,0.3); color: var(--accent); }

.follow-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted2);
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  font-family: 'Syne', sans-serif;
  letter-spacing: 0.3px;
}
.follow-btn:hover { border-color: var(--accent); color: var(--accent); }
.follow-btn.active { background: rgba(77,240,192,0.12); border-color: var(--accent); color: var(--accent); }

.comment-count {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 4px;
}


/* Post owner action buttons */
.post-actions {
  display: flex;
  gap: 6px;
}

.action-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  width: 30px;
  height: 30px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.18s;
  flex-shrink: 0;
}
.action-btn:hover { color: var(--text); border-color: rgba(255,255,255,0.2); }
.action-btn.delete:hover { color: var(--danger); border-color: var(--danger); background: rgba(240,106,77,0.08); }
.action-btn.edit-btn:hover { color: var(--accent); border-color: var(--accent); background: rgba(77,240,192,0.08); }

/* Edit modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.72);
  backdrop-filter: blur(6px);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s ease;
}

.modal-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 28px;
  width: 100%;
  max-width: 520px;
  box-shadow: 0 40px 100px rgba(0,0,0,0.8);
  animation: fadeUp 0.25s ease;
}

.modal-title {
  font-family: 'Syne', sans-serif;
  font-size: 18px;
  font-weight: 800;
  margin-bottom: 18px;
  letter-spacing: -0.3px;
}

.modal-footer {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

/* Video wrapper for autoplay UI */
.video-wrap {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
}
.video-wrap video { width: 100%; display: block; max-height: 460px; object-fit: cover; }
.play-hint {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,0.32);
  pointer-events: none;
  transition: opacity 0.3s;
}
.play-hint span { font-size: 44px; filter: drop-shadow(0 2px 10px rgba(0,0,0,0.7)); }
.video-wrap.playing .play-hint { opacity: 0; }

.vbadge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #4DF0C0, #7B6EF6);
  color: #030a0e;
  font-size: 10px;
  font-weight: 900;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  margin-left: 4px;
  vertical-align: middle;
  line-height: 1;
}

/* ===== SECTION HEADER ===== */
.section-header {
  margin-bottom: 20px;
}
.section-header h2 {
  font-family: 'Syne', sans-serif;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.5px;
}
.section-header p {
  color: var(--muted2);
  font-size: 13.5px;
  margin-top: 4px;
}

/* ===== NOTIFICATIONS ===== */
.notif-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.notif-item:last-child { border-bottom: none; }

.notif-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(77,240,192,0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.notif-text { font-size: 14px; color: var(--muted2); line-height: 1.5; }
.notif-time { font-size: 12px; color: var(--muted); margin-top: 3px; }

/* ===== MONETIZATION ===== */
.monet-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}

.monet-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
}

.monet-card-label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted2);
  font-weight: 600;
  margin-bottom: 8px;
}

.monet-card-value {
  font-family: 'Syne', sans-serif;
  font-size: 28px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -1px;
}

.monet-card-value.green { color: var(--accent); }

.monet-section-title {
  font-family: 'Syne', sans-serif;
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.ad-form {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 16px;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 10px;
  align-items: end;
}

.form-field { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 12px; color: var(--muted2); font-weight: 500; text-transform: uppercase; letter-spacing: 0.3px; }
.form-input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 13px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}
.form-input:focus { border-color: rgba(77,240,192,0.4); }
.form-input::placeholder { color: var(--muted); }

.ad-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ad-item-name { font-size: 14px; font-weight: 500; }
.ad-item-stats { font-size: 12px; color: var(--muted2); display: flex; gap: 12px; }
.ad-stat { display: flex; align-items: center; gap: 4px; }

/* ===== PROFILE ===== */
.profile-header {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 20px;
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.profile-avatar-wrap { position: relative; flex-shrink: 0; }
.profile-avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
  border: 3px solid var(--border);
}

.profile-info { flex: 1; }
.profile-name {
  font-family: 'Syne', sans-serif;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.5px;
  margin-bottom: 4px;
}
.profile-email { font-size: 13px; color: var(--muted2); margin-bottom: 14px; }

.bio-area {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  width: 100%;
  resize: none;
  outline: none;
  transition: border-color 0.2s;
}
.bio-area:focus { border-color: rgba(77,240,192,0.4); }
.bio-area::placeholder { color: var(--muted); }

.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: var(--muted2);
}
.empty-state .empty-icon { font-size: 36px; margin-bottom: 12px; }
.empty-state p { font-size: 14px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }

/* File name display */
#fileNameDisplay {
  font-size: 12px;
  color: var(--accent);
  margin-top: 4px;
}

@media (max-width: 600px) {
  .auth-wrap { grid-template-columns: 1fr; }
  .auth-brand { display: none; }
  .topnav { padding: 0 10px; gap: 6px; }
  .nav-brand { font-size: 17px; }
  .nav-tabs { padding: 3px; gap: 1px; }
  .nav-tab { padding: 6px 8px; font-size: 11px; gap: 3px; }
  .tab-label { display: none; }
  .monet-grid { grid-template-columns: 1fr; }
  .form-row { grid-template-columns: 1fr; }
  .app-layout { padding: 16px 10px; }
}
</style>
</head>
<body>

<!-- ===== AUTH SCREEN ===== -->
<div id="authScreen">
  <div class="auth-wrap">
    <div class="auth-brand">
      <div class="brand-logo">VibeNet</div>
      <div class="brand-tag">Share moments, grow your audience, and earn from your content.</div>
      <div class="brand-pills">
        <span class="pill">📹 Video</span>
        <span class="pill">💰 Earn</span>
        <span class="pill">📈 Grow</span>
        <span class="pill">🌐 Connect</span>
      </div>
    </div>

    <div class="auth-forms">
      <div class="auth-section">
        <h3>Create account</h3>
        <div class="field">
          <div class="field-label">Full Name</div>
          <input id="signupName" placeholder="Your name" />
        </div>
        <div class="field">
          <div class="field-label">Email</div>
          <input id="signupEmail" type="email" placeholder="you@email.com" />
        </div>
        <div class="field">
          <div class="field-label">Password</div>
          <input id="signupPassword" type="password" placeholder="••••••••" />
        </div>
        <div class="field">
          <div class="field-label">Profile photo (optional)</div>
          <input id="signupPic" type="file" accept="image/*" style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 14px;color:var(--muted2);width:100%;font-size:13px;" />
        </div>
        <button class="btn-primary" onclick="signup()" style="width:100%;margin-top:4px;">Create Account →</button>
      </div>

      <div class="divider"></div>

      <div class="auth-section">
        <h3>Sign in</h3>
        <div class="field">
          <div class="field-label">Email</div>
          <input id="loginEmail" type="email" placeholder="you@email.com" />
        </div>
        <div class="field">
          <div class="field-label">Password</div>
          <input id="loginPassword" type="password" placeholder="••••••••" />
        </div>
        <button class="btn-ghost" onclick="login()" style="width:100%;">Sign In</button>
      </div>
    </div>
  </div>
</div>

<!-- ===== MAIN APP ===== -->
<div id="mainApp">
  <!-- Top Nav -->
  <nav class="topnav">
    <div class="nav-brand">VibeNet</div>

    <div class="nav-tabs">
      <button class="nav-tab active" id="navFeed" onclick="showTab('feed')">
        <span>🏠</span><span class="tab-label"> Feed</span>
      </button>
      <button class="nav-tab" id="navNotifs" onclick="showTab('notifications')">
        <span>🔔</span><span class="tab-label"> Alerts</span>
        <span id="notifCount" class="notif-dot" style="display:none"></span>
      </button>
      <button class="nav-tab" id="navMonet" onclick="showTab('monet')">
        <span>💰</span><span class="tab-label"> Earn</span>
      </button>
      <button class="nav-tab" id="navProfile" onclick="showTab('profile')">
        <span>👤</span><span class="tab-label"> Profile</span>
      </button>
    </div>

    <div class="nav-right">
      <img class="nav-avatar" id="topAvatar" src="" onerror="this.style.display='none'" />
      <button class="nav-signout" onclick="logout()" title="Sign out">&#8594;</button>
    </div>
  </nav>

  <!-- Layout -->
  <div class="app-layout">
    <!-- Main column -->
    <div class="main-col">

      <!-- Feed Tab -->
      <div id="feed" class="tab visible">
        <div class="composer">
          <div class="composer-top">
            <img class="composer-avatar" id="composerAvatar" src="" onerror="this.style.display='none'" />
            <textarea id="postText" rows="3" placeholder="What's on your mind?"></textarea>
          </div>
          <div class="composer-footer">
            <div class="composer-actions">
              <label class="attach-label">
                📎 Attach media
                <input id="fileUpload" type="file" accept="image/*,video/*" onchange="showFileName(this)" />
              </label>
              <span id="fileNameDisplay"></span>
            </div>
            <button class="btn-primary" onclick="addPost()">Post →</button>
          </div>
        </div>
        <div id="feedList"></div>
      </div>

      <!-- Notifications Tab -->
      <div id="notifications" class="tab">
        <div class="section-header">
          <h2>Notifications</h2>
          <p>Stay up to date with your community</p>
        </div>
        <div class="post-card" style="padding:0 20px;">
          <div id="notifList"></div>
        </div>
      </div>

      <!-- Monetization / Payments Tab -->
      <div id="monet" class="tab">
        <div class="section-header">
          <h2>Earnings &amp; Payments</h2>
          <p>Grow your revenue, run ads, and get verified</p>
        </div>

        <!-- Stats row -->
        <div class="monet-grid">
          <div class="monet-card">
            <div class="monet-card-label">Followers</div>
            <div class="monet-card-value" id="monFollowers">0</div>
          </div>
          <div class="monet-card">
            <div class="monet-card-label">Watch Hours</div>
            <div class="monet-card-value" id="monWatch">0</div>
          </div>
          <div class="monet-card">
            <div class="monet-card-label">Status</div>
            <div class="monet-card-value" id="monStatus" style="font-size:16px;margin-top:4px;">—</div>
          </div>
          <div class="monet-card">
            <div class="monet-card-label">Total Earnings</div>
            <div class="monet-card-value green">$<span id="monEarnings">0.00</span></div>
          </div>
        </div>

        <!-- Ad Campaign -->
        <div style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px;margin-bottom:20px">
          <div class="monet-section-title" style="margin-bottom:14px">Create Ad Campaign</div>
          <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
            <div style="flex:1;min-width:160px">
              <div class="form-label" style="margin-bottom:6px">Campaign Title</div>
              <input id="adTitle" class="form-input" placeholder="My awesome campaign" style="width:100%" />
            </div>
            <div style="width:120px">
              <div class="form-label" style="margin-bottom:6px">Budget</div>
              <input id="adBudget" class="form-input" type="number" min="1" placeholder="50" style="width:100%" />
            </div>
            <button class="btn-primary" onclick="createAd()">Launch</button>
          </div>
        </div>

        <div class="monet-section-title">Active Campaigns</div>
        <div id="adsList"></div>
      <!-- Profile Tab -->
      <div id="profile" class="tab">
        <div class="section-header">
          <h2>My Profile</h2>
          <p>Manage your identity and content</p>
        </div>

        <div class="profile-header">
          <div class="profile-avatar-wrap">
            <img class="profile-avatar" id="profileAvatar" src="" onerror="this.style.background='var(--surface)'" />
          </div>
          <div class="profile-info">
            <div class="profile-name" id="profileName">—</div>
            <div class="profile-email" id="profileEmail">—</div>
            <textarea id="profileBio" class="bio-area" rows="2" placeholder="Write something about yourself..."></textarea>
            <button class="btn-primary" onclick="updateBio()" style="margin-top:10px;">Save Bio</button>
          </div>
        </div>

        <div class="monet-section-title">My Posts</div>
        <div id="profilePosts"></div>
      </div>

    </div><!-- /main-col -->


  </div><!-- /app-layout -->

<!-- Edit Post Modal -->
<div id="editModal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closeEditModal()">
  <div class="modal-box">
    <div class="modal-title">Edit Post</div>
    <textarea id="editPostText" class="bio-area" rows="5" placeholder="Update your post..."></textarea>
    <div class="modal-footer">
      <button class="btn-ghost" onclick="closeEditModal()">Cancel</button>
      <button class="btn-primary" onclick="saveEditPost()">Save Changes</button>
    </div>
  </div>
</div>

</div><!-- /mainApp -->

<script>
const API = '/api';
let currentUser = null;

function byId(id){ return document.getElementById(id); }
function escapeHtml(s){ if(!s) return ''; return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]); }

function showFileName(input){
  const d = byId('fileNameDisplay');
  d.textContent = input.files[0] ? input.files[0].name : '';
}

window.addEventListener('load', async () => {
  try {
    const res = await fetch(API + '/me');
    const j = await res.json();
    if(j.user){ currentUser = j.user; onLogin(); }
  } catch(e) {}
});

async function signup(){
  const name = byId('signupName').value.trim();
  const email = byId('signupEmail').value.trim().toLowerCase();
  const password = byId('signupPassword').value;
  if(!name||!email||!password){ alert('Please fill all required fields.'); return; }
  const pic = byId('signupPic').files[0];
  const fd = new FormData();
  fd.append('name', name); fd.append('email', email); fd.append('password', password);
  if(pic) fd.append('file', pic);
  const res = await fetch(API + '/signup', { method:'POST', body: fd });
  const j = await res.json();
  if(j.user){ currentUser = j.user; onLogin(); } else alert(j.error || j.message);
}

async function login(){
  const email = byId('loginEmail').value.trim().toLowerCase();
  const password = byId('loginPassword').value;
  if(!email||!password){ alert('Please fill in your login details.'); return; }
  const res = await fetch(API + '/login', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email, password})});
  const j = await res.json();
  if(j.user){ currentUser = j.user; onLogin(); } else alert(j.error || 'Invalid credentials');
}

async function logout(){
  await fetch(API + '/logout', {method:'POST'});
  currentUser = null;
  byId('mainApp').style.display = 'none';
  byId('authScreen').style.display = 'flex';
  if(window._vn_poll) clearInterval(window._vn_poll);
}

function onLogin(){
  byId('authScreen').style.display = 'none';
  byId('mainApp').style.display = 'block';

  // Top nav avatar
  const av = byId('topAvatar');
  if(currentUser.profile_pic){ av.src = currentUser.profile_pic; av.style.display = 'block'; }

  // Composer avatar
  const ca = byId('composerAvatar');
  if(currentUser.profile_pic){ ca.src = currentUser.profile_pic; ca.style.display = ''; }

  // Profile tab section
  byId('profileName').textContent = currentUser.name || '—';
  byId('profileEmail').textContent = currentUser.email;
  const pa = byId('profileAvatar');
  if(currentUser.profile_pic){ pa.src = currentUser.profile_pic; }

  refreshAll();
  window._vn_poll = setInterval(()=>{ if(currentUser){ loadNotifications(); loadMonetization(); } }, 5000);
}

// Tabs
function showTab(tab){
  const tabs = ['feed','notifications','monet','profile'];
  const navMap = { feed:'navFeed', notifications:'navNotifs', monet:'navMonet', profile:'navProfile' };
  tabs.forEach(t => {
    byId(t).classList.remove('visible');
    byId(t).style.display = 'none';
  });
  document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
  byId(tab).style.display = 'block';
  byId(tab).classList.add('visible');
  if(navMap[tab]) byId(navMap[tab]).classList.add('active');

  if(tab === 'profile') loadProfilePosts();
  if(tab === 'notifications') loadNotifications();
  if(tab === 'monet'){ loadMonetization(); loadAds();  }
}

async function uploadFile(file){
  const fd = new FormData(); fd.append('file', file);
  const res = await fetch(API + '/upload', {method:'POST', body: fd});
  const j = await res.json();
  return j.url || '';
}

async function addPost(){
  if(!currentUser){ alert('Please login first.'); return; }
  const text = byId('postText').value.trim();
  const fileEl = byId('fileUpload');
  let url = '';
  if(fileEl.files[0]) url = await uploadFile(fileEl.files[0]);
  if(!text && !url) return;
  await fetch(API + '/posts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
    author_email: currentUser.email, author_name: currentUser.name, profile_pic: currentUser.profile_pic||'', text, file_url: url
  })});
  byId('postText').value=''; fileEl.value=''; byId('fileNameDisplay').textContent='';
  await loadFeed(); await loadProfilePosts(); await loadMonetization();
}

function createPostElement(p){
  const div = document.createElement('div'); div.className='post-card';

  const header = document.createElement('div'); header.className='post-header';
  const authorWrap = document.createElement('div'); authorWrap.className='post-author';
  const img = document.createElement('img'); img.className='post-avatar'; img.src = p.profile_pic || '';
  img.onerror = ()=> { img.style.background='var(--surface)'; img.src=''; };
  const info = document.createElement('div'); info.className='post-author-info';
  const verifiedBadge = p.author_verified ? ' <span class="vbadge" title="VibeNet Verified">✦</span>' : '';
  info.innerHTML = `<strong>${escapeHtml(p.author_name || 'Unknown')}${verifiedBadge}</strong><div class="post-ts">${escapeHtml(p.timestamp)}</div>`;
  authorWrap.append(img, info);
  header.append(authorWrap);

  if(currentUser && currentUser.email === p.author_email){
    // Owner: edit + delete buttons
    const actions = document.createElement('div'); actions.className='post-actions';
    const editBtn = document.createElement('button'); editBtn.className='action-btn edit-btn'; editBtn.title='Edit'; editBtn.textContent='✏️';
    editBtn.onclick = ()=> openEditModal(p.id, p.text);
    const delBtn = document.createElement('button'); delBtn.className='action-btn delete'; delBtn.title='Delete'; delBtn.textContent='🗑';
    delBtn.onclick = async ()=>{
      if(!confirm('Delete this post?')) return;
      const r = await fetch(API+'/posts/'+p.id, {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email: currentUser.email})});
      const j = await r.json();
      if(j.success){ div.style.transition='opacity 0.3s,transform 0.3s'; div.style.opacity='0'; div.style.transform='scale(0.97)'; setTimeout(()=>{ div.remove(); loadMonetization(); }, 300); }
    };
    actions.append(editBtn, delBtn);
    header.append(actions);
  } else if(currentUser){
    const fb = document.createElement('button'); fb.className='follow-btn'; fb.textContent='+ Follow';
    fb.onclick = async ()=>{
      const res = await fetch(API+'/follow',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({follower_email:currentUser.email,target_email:p.author_email})});
      const j = await res.json();
      if(j.success){ fb.classList.toggle('active'); fb.textContent=fb.classList.contains('active')?'✓ Following':'+ Follow'; loadMonetization(); }
    };
    (async()=>{
      const r = await fetch(API+`/is_following?f=${encodeURIComponent(currentUser.email)}&t=${encodeURIComponent(p.author_email)}`);
      const jj = await r.json();
      if(jj.following){ fb.classList.add('active'); fb.textContent='✓ Following'; }
    })();
    header.append(fb);
  }

  div.append(header);

  const postTextEl = document.createElement('div');
  if(p.text){ postTextEl.className='post-text'; postTextEl.textContent=p.text; div.append(postTextEl); }
  div._postTextEl = postTextEl;

  if(p.file_url){
    const media = document.createElement('div'); media.className='post-media';
    if(p.file_url.endsWith('.mp4')||p.file_url.endsWith('.webm')||p.file_url.includes('video')){
      const wrap = document.createElement('div'); wrap.className='video-wrap';
      const v = document.createElement('video');
      v.src = p.file_url; v.controls = true; v.muted = true; v.loop = false;
      v.setAttribute('playsinline','');
      const hint = document.createElement('div'); hint.className='play-hint';
      hint.innerHTML='<span>▶</span>';
      v.addEventListener('play', ()=>{ wrap.classList.add('playing'); });
      v.addEventListener('pause', ()=>{ wrap.classList.remove('playing'); });
      v.addEventListener('ended', async()=>{
        wrap.classList.remove('playing');
        await fetch(API+'/watch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({viewer:currentUser?currentUser.email:'',post_id:p.id})});
        await fetch(API+'/ads/impression',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({post_id:p.id,viewer:currentUser?currentUser.email:''})});
        loadMonetization();
      });
      wrap.append(v, hint);
      media.append(wrap);
    } else {
      const im=document.createElement('img'); im.src=p.file_url; media.append(im);
    }
    div.append(media);
  }

  const footer = document.createElement('div'); footer.className='post-footer';
  const bar = document.createElement('div'); bar.className='reaction-bar';
  ['👍','❤️','😂'].forEach(em=>{
    const btn=document.createElement('button'); btn.className='react-btn'; btn.dataset.emoji=em;
    btn.innerHTML=`${em} <span>${p.reactions&&p.reactions[em]?p.reactions[em]:0}</span>`;
    if(p.user_reaction&&currentUser&&p.user_reaction===em) btn.classList.add('active');
    btn.onclick=async(ev)=>{
      ev.stopPropagation();
      if(!currentUser){ alert('Login to react'); return; }
      const res=await fetch(API+'/react',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({post_id:p.id,emoji:em,user_email:currentUser.email})});
      const j=await res.json();
      if(j.success){
        div.querySelectorAll('.react-btn').forEach(rb=>{
          const e=rb.dataset.emoji;
          rb.innerHTML=`${e} <span>${j.reactions&&j.reactions[e]!==undefined?j.reactions[e]:(p.reactions&&p.reactions[e]?p.reactions[e]:0)}</span>`;
          rb.classList.remove('active');
        });
        const clicked=div.querySelector(`.react-btn[data-emoji="${em}"]`);
        if(clicked) clicked.classList.add('active');
      }
    };
    bar.append(btn);
  });

  const cc=document.createElement('div'); cc.className='comment-count'; cc.innerHTML=`💬 ${p.comments_count||0}`;
  footer.append(bar, cc);
  div.append(footer);
  return div;
}

async function loadFeed(){
  const res = await fetch(API+'/posts');
  const list = await res.json();
  const feed = byId('feedList'); feed.innerHTML='';
  if(!list.length){
    feed.innerHTML='<div class="empty-state"><div class="empty-icon">📭</div><p>No posts yet. Be the first to share something!</p></div>';
    return;
  }
  list.forEach(p=>feed.appendChild(createPostElement(p)));
  observeVideos();
}

function observeVideos(){
  if(window._vn_obs) window._vn_obs.disconnect();
  let currentlyPlaying = null;

  const obs = new IntersectionObserver(entries=>{
    entries.forEach(entry=>{
      const v = entry.target;
      const ratio = entry.intersectionRatio;

      if(ratio >= 0.6){
        // Autoplay: pause anything else first
        if(currentlyPlaying && currentlyPlaying !== v){
          currentlyPlaying.pause();
        }
        if(v.paused){
          v.muted = true;
          v.play().then(()=>{ currentlyPlaying = v; }).catch(()=>{});
        }
      } else if(ratio < 0.25){
        if(!v.paused){ v.pause(); }
        if(currentlyPlaying === v) currentlyPlaying = null;
      }
    });
  }, { threshold: [0, 0.25, 0.5, 0.6, 0.75, 1.0] });

  document.querySelectorAll('video').forEach(v=>obs.observe(v));
  window._vn_obs = obs;
}

async function loadNotifications(){
  if(!currentUser) return;
  const r=await fetch(API+'/notifications/'+encodeURIComponent(currentUser.email));
  const list=await r.json();
  const el=byId('notifList'); el.innerHTML='';
  const countEl=byId('notifCount');
  if(list.length){ countEl.style.display='inline-block'; countEl.textContent=list.length; } else countEl.style.display='none';
  if(!list.length){
    el.innerHTML='<div class="empty-state" style="padding:32px"><div class="empty-icon">🎉</div><p>All caught up!</p></div>';
    return;
  }
  list.forEach(n=>{
    const d=document.createElement('div'); d.className='notif-item';
    const icon=n.text.includes('reaction')?'⚡':n.text.includes('follow')?'👋':'🔔';
    d.innerHTML=`<div class="notif-icon">${icon}</div><div><div class="notif-text">${escapeHtml(n.text)}</div><div class="notif-time">${escapeHtml(n.timestamp)}</div></div>`;
    el.appendChild(d);
  });
}

async function loadProfilePosts(){
  if(!currentUser) return;
  const r=await fetch(API+'/profile/'+encodeURIComponent(currentUser.email));
  const j=await r.json();
  byId('profileBio').value=j.bio||'';
  const el=byId('profilePosts'); el.innerHTML='';
  if(!j.posts||!j.posts.length){
    el.innerHTML='<div class="empty-state"><div class="empty-icon">✏️</div><p>No posts yet.</p></div>';
    return;
  }
  j.posts.forEach(p=>{
    const d=document.createElement('div'); d.className='post-card';
    d.innerHTML=`<div class="post-text">${escapeHtml(p.text||'')}</div><div class="post-ts">${escapeHtml(p.timestamp)}</div>`;
    if(p.file_url){
      if(p.file_url.endsWith('.mp4')||p.file_url.endsWith('.webm')){
        d.innerHTML+=`<div class="post-media"><video src="${p.file_url}" controls></video></div>`;
      } else {
        d.innerHTML+=`<div class="post-media"><img src="${p.file_url}"></div>`;
      }
    }
    el.appendChild(d);
  });
}

async function updateBio(){
  if(!currentUser) return;
  const bio = byId('profileBio').value.trim();
  await fetch(API+'/update_bio',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:currentUser.email,bio})});
  const saved=document.createElement('span');
  saved.style.cssText='color:var(--accent);font-size:13px;margin-left:10px;';
  saved.textContent='Saved ✓';
  const btn=document.querySelector('[onclick="updateBio()"]');
  btn.parentNode.insertBefore(saved, btn.nextSibling);
  setTimeout(()=>saved.remove(), 2000);
}

async function loadMonetization(){
  if(!currentUser) return;
  const r=await fetch(API+'/monetization/'+encodeURIComponent(currentUser.email));
  const j=await r.json();
  byId('monFollowers').textContent=j.followers;
  byId('monWatch').textContent=j.watch_hours;
  byId('monEarnings').textContent=(j.earnings||0).toFixed(2);
  byId('monStatus').textContent=j.followers>=1000&&j.watch_hours>=4000?'✅ Eligible':'⏳ Growing';
}

async function createAd(){
  const title=byId('adTitle').value.trim(); const budget=parseFloat(byId('adBudget').value||0);
  if(!title||!budget){ alert('Please enter a title and budget.'); return; }
  await fetch(API+'/ads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,budget,owner:currentUser.email})});
  byId('adTitle').value=''; byId('adBudget').value='';
  loadAds();
}

async function loadAds(){
  const r=await fetch(API+'/ads');
  const list=await r.json();
  const el=byId('adsList'); el.innerHTML='';
  if(!list.length){
    el.innerHTML='<div class="empty-state"><div class="empty-icon">📢</div><p>No campaigns yet. Launch your first one above!</p></div>';
    return;
  }
  list.forEach(a=>{
    const d=document.createElement('div'); d.className='ad-item';
    d.innerHTML=`<div class="ad-item-name">${escapeHtml(a.title)}</div><div class="ad-item-stats"><span class="ad-stat">💰 ${a.budget}</span><span class="ad-stat">👁 ${a.impressions}</span><span class="ad-stat">🖱 ${a.clicks}</span></div>`;
    el.appendChild(d);
  });
}


// Edit modal
let _editPostId = null;
function openEditModal(postId, currentText){
  _editPostId = postId;
  byId('editPostText').value = currentText || '';
  byId('editModal').style.display = 'flex';
  setTimeout(()=>byId('editPostText').focus(), 80);
}
function closeEditModal(){
  byId('editModal').style.display = 'none';
  _editPostId = null;
}
async function saveEditPost(){
  if(!_editPostId || !currentUser) return;
  const text = byId('editPostText').value.trim();
  if(!text){ alert('Post cannot be empty.'); return; }
  const res = await fetch(API+'/posts/'+_editPostId, {
    method: 'PATCH',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email: currentUser.email, text})
  });
  const j = await res.json();
  if(j.success){
    closeEditModal();
    // Update in-place in feed
    const cards = document.querySelectorAll('.post-card');
    cards.forEach(card=>{
      if(card._postId == _editPostId && card._postTextEl){
        card._postTextEl.textContent = text;
      }
    });
    await loadFeed();
  } else {
    alert(j.error || 'Edit failed');
  }
}




async function refreshAll(){ await loadFeed(); await loadNotifications(); await loadProfilePosts(); await loadMonetization(); await loadAds(); }
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

# ---------- API: Auth ----------
@app.route("/api/signup", methods=["POST"])
def api_signup():
    name     = request.form.get("name", "").strip()
    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not email or not password:
        return jsonify({"error": "email + password required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "User already exists"}), 400

    profile_pic = ""
    if "file" in request.files:
        f = request.files["file"]
        if f and f.filename:
            fn = f"{uuid.uuid4().hex}_{f.filename}"
            f.save(os.path.join(UPLOAD_DIR, fn))
            profile_pic = f"/uploads/{fn}"

    user = User(name=name, email=email, password=password, profile_pic=profile_pic)
    db.session.add(user)
    db.session.commit()
    session["user_email"] = email
    return jsonify({"user": user.to_dict()})


@app.route("/api/login", methods=["POST"])
def api_login():
    data     = request.get_json() or {}
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")
    user     = User.query.filter_by(email=email, password=password).first()
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401
    session["user_email"] = email
    return jsonify({"user": user.to_dict()})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"status": "logged out"})


@app.route("/api/me")
def api_me():
    email = session.get("user_email")
    if not email:
        return jsonify({"user": None})
    user = User.query.filter_by(email=email).first()
    return jsonify({"user": user.to_dict() if user else None})


# ---------- Upload ----------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No filename"}), 400
    fn = f"{uuid.uuid4().hex}_{f.filename}"
    f.save(os.path.join(UPLOAD_DIR, fn))
    return jsonify({"url": f"/uploads/{fn}"})


# ---------- Posts ----------
@app.route("/api/posts", methods=["GET", "POST"])
def api_posts():
    if request.method == "GET":
        posts = Post.query.order_by(Post.id.desc()).all()
        # Build a verified lookup map
        emails = list({p.author_email for p in posts})
        verified_map = {}
        if emails:
            users = User.query.filter(User.email.in_(emails)).all()
            verified_map = {u.email: bool(u.verified) for u in users}
        return jsonify([p.to_dict(author_verified=verified_map.get(p.author_email, False)) for p in posts])

    data = request.get_json() or {}
    post = Post(
        author_email=data.get("author_email"),
        author_name=data.get("author_name"),
        profile_pic=data.get("profile_pic", ""),
        text=data.get("text", ""),
        file_url=data.get("file_url", ""),
    )
    db.session.add(post)
    db.session.commit()
    return jsonify(post.to_dict())


@app.route("/api/posts/<int:post_id>", methods=["DELETE", "PATCH"])
def api_post_modify(post_id):
    data  = request.get_json() or {}
    email = data.get("email")
    post  = Post.query.get_or_404(post_id)
    if post.author_email != email:
        return jsonify({"error": "Unauthorized"}), 403

    if request.method == "DELETE":
        UserReaction.query.filter_by(post_id=post_id).delete()
        Comment.query.filter_by(post_id=post_id).delete()
        db.session.delete(post)
        db.session.commit()
        return jsonify({"success": True})

    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Text required"}), 400
    post.text = text
    db.session.commit()
    return jsonify({"success": True})


# ---------- Comments ----------
@app.route("/api/posts/<int:post_id>/comments", methods=["GET", "POST"])
def api_comments(post_id):
    """Get all comments for a post or create a new comment"""
    if request.method == "GET":
        comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.id.asc()).all()
        
        # Build verified lookup map
        emails = list({c.author_email for c in comments})
        verified_map = {}
        if emails:
            users = User.query.filter(User.email.in_(emails)).all()
            verified_map = {u.email: bool(u.verified) for u in users}
        
        return jsonify([c.to_dict(author_verified=verified_map.get(c.author_email, False)) for c in comments])

    # POST: Create new comment
    post = Post.query.get_or_404(post_id)
    data = request.get_json() or {}
    
    comment = Comment(
        post_id=post_id,
        author_email=data.get("author_email"),
        author_name=data.get("author_name"),
        profile_pic=data.get("profile_pic", ""),
        text=data.get("text", "").strip(),
    )
    
    if not comment.text:
        return jsonify({"error": "Comment text required"}), 400
    
    db.session.add(comment)
    
    # Update post comment count
    post.comments_count += 1
    
    # Notify post author of new comment (if not the commenter)
    if post.author_email != data.get("author_email"):
        notif = Notification(
            user_email=post.author_email,
            text=f"{data.get('author_name', 'Someone')} commented on your post"
        )
        db.session.add(notif)
    
    db.session.commit()
    
    author_verified = User.query.filter_by(email=data.get("author_email")).first()
    author_verified = bool(author_verified.verified) if author_verified else False
    
    return jsonify({
        "success": True,
        "comment": comment.to_dict(author_verified=author_verified)
    }), 201


@app.route("/api/comments/<int:comment_id>", methods=["DELETE", "PATCH"])
def api_comment_modify(comment_id):
    """Delete or edit a comment"""
    data = request.get_json() or {}
    email = data.get("email")
    comment = Comment.query.get_or_404(comment_id)
    
    if comment.author_email != email:
        return jsonify({"error": "Unauthorized"}), 403

    if request.method == "DELETE":
        post = Post.query.get(comment.post_id)
        if post:
            post.comments_count = max(0, post.comments_count - 1)
        db.session.delete(comment)
        db.session.commit()
        return jsonify({"success": True})

    # PATCH: Edit comment
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Comment text required"}), 400
    comment.text = text
    db.session.commit()
    return jsonify({"success": True})


# ---------- React ----------
@app.route("/api/react", methods=["POST"])
def api_react_post():
    data       = request.get_json() or {}
    post_id    = data.get("post_id")
    emoji      = data.get("emoji")
    user_email = data.get("user_email")

    post = Post.query.get(post_id)
    if not post:
        return jsonify({"error": "Post not found"}), 404

    reactions  = post.reactions()
    prev_react = UserReaction.query.filter_by(user_email=user_email, post_id=post_id).first()
    prev_emoji = prev_react.emoji if prev_react else None

    if prev_emoji == emoji:
        return jsonify({"success": True, "reactions": reactions})

    if prev_react:
        reactions[prev_emoji] = max(0, reactions.get(prev_emoji, 0) - 1)
        db.session.delete(prev_react)

    new_react = UserReaction(user_email=user_email, post_id=post_id, emoji=emoji)
    db.session.add(new_react)
    reactions[emoji] = reactions.get(emoji, 0) + 1
    post.reactions_json = _json.dumps(reactions)

    if post.author_email != user_email:
        notif = Notification(user_email=post.author_email,
                             text=f"{emoji} reaction on your post")
        db.session.add(notif)

    db.session.commit()
    return jsonify({"success": True, "reactions": reactions})


# ---------- Notifications ----------
@app.route("/api/notifications/<email>")
def api_notifications_get(email):
    notifs = Notification.query.filter_by(user_email=email).order_by(Notification.id.desc()).all()
    return jsonify([n.to_dict() for n in notifs])


@app.route("/api/notifications/<int:notif_id>/mark_seen", methods=["POST"])
def api_notification_mark_seen(notif_id):
    """Mark a notification as seen and track when it was seen"""
    notif = Notification.query.get_or_404(notif_id)
    notif.seen = 1
    notif.seen_at = now_ts()
    db.session.commit()
    return jsonify({"success": True, "ready_to_dismiss": notif.to_dict()["ready_to_dismiss"]})


@app.route("/api/notifications/<int:notif_id>/dismiss", methods=["DELETE"])
def api_notification_dismiss(notif_id):
    """Dismiss a notification (only if it's been seen and auto_dismiss is enabled)"""
    notif = Notification.query.get_or_404(notif_id)
    if notif.seen and notif.auto_dismiss:
        db.session.delete(notif)
        db.session.commit()
        return jsonify({"success": True, "message": "Notification dismissed"})
    return jsonify({"error": "Notification cannot be dismissed"}), 400


# ---------- Monetization / Profile ----------
@app.route("/api/monetization/<email>")
def api_monetization_get(email):
    followers = Follower.query.filter_by(user_email=email).count()
    user      = User.query.filter_by(email=email).first()
    if user:
        return jsonify({"followers": followers, "watch_hours": user.watch_hours, "earnings": user.earnings})
    return jsonify({"followers": 0, "watch_hours": 0, "earnings": 0})


# ---------- Wallet / Orange Money ----------
@app.route("/api/wallet/<email>", methods=["GET", "POST"])
def api_wallet(email):
    """Get user wallet or create/update Orange Money account"""
    if request.method == "GET":
        wallet = UserWallet.query.filter_by(user_email=email).first()
        if not wallet:
            return jsonify({"wallet": None, "message": "No wallet configured"})
        return jsonify({"wallet": wallet.to_dict()})

    # POST: Create or update wallet
    data = request.get_json() or {}
    
    wallet = UserWallet.query.filter_by(user_email=email).first()
    if not wallet:
        wallet = UserWallet(user_email=email)
    
    # Update wallet details
    wallet.wallet_type = data.get("wallet_type", "orange_money")
    wallet.account_number = data.get("account_number", "")  # Orange Money phone number
    wallet.account_holder = data.get("account_holder", "")
    
    if not wallet.account_number:
        return jsonify({"error": "Account number (phone) required"}), 400
    
    db.session.add(wallet)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "wallet": wallet.to_dict(),
        "message": "Wallet configured successfully"
    }), 201


@app.route("/api/wallet/<email>/verify", methods=["POST"])
def api_wallet_verify(email):
    """Verify Orange Money account (simulated)"""
    wallet = UserWallet.query.filter_by(user_email=email).first()
    if not wallet:
        return jsonify({"error": "Wallet not found"}), 404
    
    data = request.get_json() or {}
    verification_code = data.get("verification_code")
    
    if not verification_code:
        return jsonify({"error": "Verification code required"}), 400
    
    # In production, verify with Orange Money API
    # For now, simulate verification
    if len(verification_code) >= 4:  # Simple check
        wallet.verified = 1
        wallet.verified_at = now_ts()
        db.session.commit()
        
        return jsonify({
            "success": True,
            "wallet": wallet.to_dict(),
            "message": "Wallet verified successfully"
        })
    
    return jsonify({"error": "Invalid verification code"}), 400


@app.route("/api/earnings/<email>", methods=["GET"])
def api_earnings_summary(email):
    """Get earnings summary from all campaigns"""
    payouts = Payout.query.filter_by(creator_email=email).all()
    wallet = UserWallet.query.filter_by(user_email=email).first()
    user = User.query.filter_by(email=email).first()
    
    total_earned = sum(p.amount for p in payouts if p.status == "completed")
    pending_payouts = sum(p.amount for p in payouts if p.status == "pending")
    processing_payouts = sum(p.amount for p in payouts if p.status == "processing")
    
    return jsonify({
        "user_email": email,
        "total_earned": round(total_earned, 2),
        "pending_payouts": round(pending_payouts, 2),
        "processing_payouts": round(processing_payouts, 2),
        "wallet_balance": wallet.balance if wallet else 0.0,
        "watch_hours": user.watch_hours if user else 0,
        "system_earnings": user.earnings if user else 0.0,
        "payout_count": len(payouts),
        "payouts": [p.to_dict() for p in payouts]
    })


@app.route("/api/profile/<email>")
def api_profile_get(email):
    user  = User.query.filter_by(email=email).first()
    posts = Post.query.filter_by(author_email=email).order_by(Post.id.desc()).all()
    return jsonify({
        "bio":   user.bio if user else "",
        "posts": [p.to_dict() for p in posts],
    })


@app.route("/api/update_bio", methods=["POST"])
def api_update_bio():
    data  = request.get_json() or {}
    user  = User.query.filter_by(email=data.get("email")).first()
    if user:
        user.bio = data.get("bio", "")
        db.session.commit()
    return jsonify({"success": True})


# ---------- Following ----------
@app.route("/api/follow", methods=["POST"])
def api_follow():
    data     = request.get_json() or {}
    follower = data.get("follower_email")
    target   = data.get("target_email")

    existing = Follower.query.filter_by(user_email=target, follower_email=follower).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"success": True, "status": "unfollowed"})

    db.session.add(Follower(user_email=target, follower_email=follower))
    db.session.add(Notification(user_email=target, text=f"{follower} followed you"))
    db.session.commit()
    return jsonify({"success": True, "status": "followed"})


@app.route("/api/is_following")
def api_is_following():
    f = request.args.get("f")
    t = request.args.get("t")
    exists = Follower.query.filter_by(user_email=t, follower_email=f).first() is not None
    return jsonify({"following": exists})


# ---------- Watch / Ads ----------
@app.route("/api/watch", methods=["POST"])
def api_watch():
    data    = request.get_json() or {}
    viewer  = data.get("viewer")
    post_id = data.get("post_id")
    post    = Post.query.get(post_id)
    if post and post.author_email != viewer:
        author = User.query.filter_by(email=post.author_email).first()
        if author:
            author.watch_hours += 1
            author.earnings    += 0.1
            db.session.commit()
    return jsonify({"success": True})


@app.route("/api/ads", methods=["GET", "POST"])
def api_ads():
    if request.method == "POST":
        data = request.get_json() or {}
        ad   = Ad(title=data.get("title"), owner_email=data.get("owner"), budget=data.get("budget", 0))
        db.session.add(ad)
        db.session.commit()
        return jsonify({"message": "Ad created"})
    ads = Ad.query.order_by(Ad.id.desc()).all()
    return jsonify([a.to_dict() for a in ads])


@app.route("/api/ads/impression", methods=["POST"])
def api_ads_impression():
    return jsonify({"success": True})


# ---------- Paid Campaigns ----------
@app.route("/api/campaigns", methods=["GET", "POST"])
def api_campaigns():
    """Get all campaigns or create a new campaign"""
    if request.method == "GET":
        owner = request.args.get("owner")
        if owner:
            campaigns = PaidCampaign.query.filter_by(owner_email=owner).order_by(PaidCampaign.id.desc()).all()
        else:
            campaigns = PaidCampaign.query.order_by(PaidCampaign.id.desc()).all()
        return jsonify([c.to_dict() for c in campaigns])

    # POST: Create new campaign
    data = request.get_json() or {}
    
    campaign = PaidCampaign(
        owner_email=data.get("owner_email"),
        title=data.get("title", ""),
        description=data.get("description", ""),
        budget=data.get("budget", 0.0),
        target_audience=data.get("target_audience", ""),
        cpc=data.get("cpc", 0.5),
        cpm=data.get("cpm", 2.0),
        status="pending",  # Start as pending until payment is made
        payment_status="unpaid"
    )
    
    if not campaign.title:
        return jsonify({"error": "Campaign title required"}), 400
    
    if campaign.budget <= 0:
        return jsonify({"error": "Campaign budget must be greater than 0"}), 400
    
    db.session.add(campaign)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "campaign": campaign.to_dict(),
        "message": "Campaign created. Please make a payment to activate it."
    }), 201


@app.route("/api/campaigns/<int:campaign_id>", methods=["GET", "PATCH", "DELETE"])
def api_campaign_detail(campaign_id):
    """Get, update, or delete a specific campaign"""
    campaign = PaidCampaign.query.get_or_404(campaign_id)
    
    if request.method == "GET":
        return jsonify(campaign.to_dict())

    data = request.get_json() or {}
    email = data.get("email")
    
    # Only owner can modify
    if campaign.owner_email != email:
        return jsonify({"error": "Unauthorized"}), 403

    if request.method == "DELETE":
        db.session.delete(campaign)
        db.session.commit()
        return jsonify({"success": True, "message": "Campaign deleted"})

    # PATCH: Update campaign
    campaign.title = data.get("title", campaign.title)
    campaign.description = data.get("description", campaign.description)
    campaign.budget = data.get("budget", campaign.budget)
    campaign.status = data.get("status", campaign.status)
    campaign.target_audience = data.get("target_audience", campaign.target_audience)
    campaign.cpc = data.get("cpc", campaign.cpc)
    campaign.cpm = data.get("cpm", campaign.cpm)
    campaign.updated_at = now_ts()
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "campaign": campaign.to_dict()
    })


@app.route("/api/campaigns/<int:campaign_id>/impression", methods=["POST"])
def api_campaign_impression(campaign_id):
    """Record an impression and update spent amount"""
    campaign = PaidCampaign.query.get_or_404(campaign_id)
    
    data = request.get_json() or {}
    count = data.get("count", 1)
    
    campaign.impressions += count
    cost = (count * campaign.cpm) / 1000
    campaign.spent += cost
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "campaign": campaign.to_dict()
    })


@app.route("/api/campaigns/<int:campaign_id>/click", methods=["POST"])
def api_campaign_click(campaign_id):
    """Record a click and update spent amount"""
    campaign = PaidCampaign.query.get_or_404(campaign_id)
    
    campaign.clicks += 1
    campaign.spent += campaign.cpc
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "campaign": campaign.to_dict()
    })


@app.route("/api/campaigns/<int:campaign_id>/conversion", methods=["POST"])
def api_campaign_conversion(campaign_id):
    """Record a conversion"""
    campaign = PaidCampaign.query.get_or_404(campaign_id)
    
    campaign.conversions += 1
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "campaign": campaign.to_dict()
    })


@app.route("/api/campaigns/<int:campaign_id>/analytics", methods=["GET"])
def api_campaign_analytics(campaign_id):
    """Get detailed analytics for a campaign"""
    campaign = PaidCampaign.query.get_or_404(campaign_id)
    
    ctr = (campaign.clicks / campaign.impressions * 100) if campaign.impressions > 0 else 0
    cost_per_conversion = campaign.spent / campaign.conversions if campaign.conversions > 0 else 0
    
    return jsonify({
        "campaign_id": campaign_id,
        "title": campaign.title,
        "status": campaign.status,
        "payment_status": campaign.payment_status,
        "budget": campaign.budget,
        "spent": round(campaign.spent, 2),
        "remaining": round(campaign.budget - campaign.spent, 2),
        "impressions": campaign.impressions,
        "clicks": campaign.clicks,
        "conversions": campaign.conversions,
        "ctr": round(ctr, 2),
        "cpc": campaign.cpc,
        "cpm": campaign.cpm,
        "cost_per_conversion": round(cost_per_conversion, 2),
        "roi": campaign.to_dict()["roi"],
    })


# ---------- Orange Money Accounts ----------
@app.route("/api/orange-money/account", methods=["GET", "POST"])
def api_orange_money_account():
    """Get or create Orange Money account for user"""
    if request.method == "GET":
        user_email = request.args.get("user_email")
        if not user_email:
            return jsonify({"error": "user_email required"}), 400
        
        account = OrangeMoneyAccount.query.filter_by(user_email=user_email).first()
        return jsonify(account.to_dict() if account else None)

    # POST: Create/update Orange Money account
    data = request.get_json() or {}
    user_email = data.get("user_email")
    phone_number = data.get("phone_number")
    account_holder = data.get("account_holder")
    country = data.get("country", "")

    if not all([user_email, phone_number, account_holder]):
        return jsonify({"error": "Missing required fields: user_email, phone_number, account_holder"}), 400

    # Validate phone number format (basic validation)
    if len(phone_number) < 8 or not phone_number.replace("+", "").replace(" ", "").isdigit():
        return jsonify({"error": "Invalid phone number format"}), 400

    # Check if account already exists
    account = OrangeMoneyAccount.query.filter_by(user_email=user_email).first()
    
    if account:
        # Update existing account
        account.phone_number = phone_number
        account.account_holder = account_holder
        account.country = country
    else:
        # Create new account
        account = OrangeMoneyAccount(
            user_email=user_email,
            phone_number=phone_number,
            account_holder=account_holder,
            country=country,
            is_verified=0  # Requires verification
        )
        db.session.add(account)

    db.session.commit()

    return jsonify({
        "success": True,
        "account": account.to_dict(),
        "message": "Orange Money account configured. Awaiting verification."
    }), 201


@app.route("/api/orange-money/account/verify", methods=["POST"])
def api_verify_orange_money():
    """Verify Orange Money account (admin or automated)"""
    data = request.get_json() or {}
    user_email = data.get("user_email")
    verification_code = data.get("verification_code")  # Optional: could be used for verification
    
    account = OrangeMoneyAccount.query.filter_by(user_email=user_email).first()
    if not account:
        return jsonify({"error": "Orange Money account not found"}), 404

    account.is_verified = 1
    account.verified_at = now_ts()
    db.session.commit()

    return jsonify({
        "success": True,
        "account": account.to_dict(),
        "message": "Orange Money account verified successfully"
    })


# ---------- User Earnings ----------
@app.route("/api/earnings/<user_email>", methods=["GET"])
def api_user_earnings(user_email):
    """Get user's total earnings and balance"""
    earnings = UserEarnings.query.filter_by(user_email=user_email).first()
    
    if not earnings:
        # Create initial earnings record if doesn't exist
        earnings = UserEarnings(user_email=user_email)
        db.session.add(earnings)
        db.session.commit()
    
    return jsonify(earnings.to_dict())


# ---------- Payouts ----------
@app.route("/api/payouts", methods=["GET", "POST"])
def api_payouts():
    """Get all payouts or request a new payout"""
    if request.method == "GET":
        user_email = request.args.get("user_email")
        if user_email:
            payouts = Payout.query.filter_by(user_email=user_email).order_by(Payout.id.desc()).all()
        else:
            payouts = Payout.query.order_by(Payout.id.desc()).all()
        return jsonify([p.to_dict() for p in payouts])

    # POST: Request a payout
    data = request.get_json() or {}
    user_email = data.get("user_email")
    amount = data.get("amount")

    if not user_email or not amount:
        return jsonify({"error": "Missing required fields: user_email, amount"}), 400

    # Check Orange Money account exists and is verified
    account = OrangeMoneyAccount.query.filter_by(user_email=user_email).first()
    if not account:
        return jsonify({"error": "Orange Money account not configured"}), 400
    
    if not account.is_verified:
        return jsonify({"error": "Orange Money account not verified"}), 400

    # Check user has sufficient balance
    earnings = UserEarnings.query.filter_by(user_email=user_email).first()
    if not earnings or earnings.balance < amount:
        return jsonify({"error": "Insufficient balance"}), 400

    # Create payout request
    payout = Payout(
        user_email=user_email,
        orange_account_id=account.id,
        amount=amount,
        status="pending",
        payout_type="withdrawal",
        description=f"Withdrawal to Orange Money {account.phone_number}"
    )

    db.session.add(payout)
    db.session.commit()

    return jsonify({
        "success": True,
        "payout": payout.to_dict(),
        "message": "Payout request submitted. Processing..."
    }), 201


@app.route("/api/payouts/<int:payout_id>/process", methods=["POST"])
def api_process_payout(payout_id):
    """Process a payout to Orange Money"""
    payout = Payout.query.get_or_404(payout_id)
    data = request.get_json() or {}
    
    # In production, call Orange Money API here
    success = data.get("success", True)
    
    if success:
        payout.status = "processing"
        payout.transaction_id = f"OM_{uuid.uuid4().hex[:12].upper()}"
        
        # Update user earnings
        earnings = UserEarnings.query.filter_by(user_email=payout.user_email).first()
        if earnings:
            earnings.total_paid_out += payout.amount
            earnings.balance -= payout.amount
            earnings.last_updated = now_ts()
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "payout": payout.to_dict(),
            "message": "Payout processing to Orange Money",
            "transaction_id": payout.transaction_id
        })
    else:
        payout.status = "failed"
        db.session.commit()
        
        return jsonify({
            "success": False,
            "payout": payout.to_dict(),
            "error": "Payout processing failed"
        }), 400


@app.route("/api/payouts/<int:payout_id>/complete", methods=["POST"])
def api_complete_payout(payout_id):
    """Mark payout as completed (after Orange Money confirms)"""
    payout = Payout.query.get_or_404(payout_id)
    
    payout.status = "completed"
    payout.processed_at = now_ts()
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "payout": payout.to_dict(),
        "message": "Payout completed successfully"
    })


@app.route("/api/payouts/<int:payout_id>", methods=["GET"])
def api_payout_detail(payout_id):
    """Get payout details"""
    payout = Payout.query.get_or_404(payout_id)
    return jsonify(payout.to_dict())


# ---------- Campaign Earnings (Auto-credit to user balance) ----------
@app.route("/api/campaigns/<int:campaign_id>/complete", methods=["POST"])
def api_complete_campaign(campaign_id):
    """
    Mark campaign as completed and credit earnings to user
    Called when campaign budget is exhausted or admin completes it
    """
    campaign = PaidCampaign.query.get_or_404(campaign_id)
    data = request.get_json() or {}
    user_email = data.get("user_email")

    if campaign.owner_email != user_email:
        return jsonify({"error": "Unauthorized"}), 403

    # Calculate earnings based on platform percentage (e.g., 70% to advertiser, 30% platform)
    # This would be the amount paid back after campaign runs
    earnings_amount = campaign.spent * 0.70  # 70% back to platform (for VibeNet ecosystem)

    campaign.status = "completed"
    campaign.updated_at = now_ts()

    # Update user earnings
    user_earnings = UserEarnings.query.filter_by(user_email=user_email).first()
    if not user_earnings:
        user_earnings = UserEarnings(user_email=user_email)
        db.session.add(user_earnings)

    user_earnings.total_earned += earnings_amount
    user_earnings.balance += earnings_amount
    user_earnings.last_updated = now_ts()

    # Create payout record for this campaign earnings
    account = OrangeMoneyAccount.query.filter_by(user_email=user_email).first()
    if account:
        campaign_earning = Payout(
            user_email=user_email,
            orange_account_id=account.id,
            campaign_id=campaign_id,
            amount=earnings_amount,
            status="completed",
            payout_type="campaign_earnings",
            transaction_id=f"CE_{uuid.uuid4().hex[:12].upper()}",
            description=f"Earnings from campaign: {campaign.title}",
            processed_at=now_ts()
        )
        db.session.add(campaign_earning)

    db.session.commit()

    return jsonify({
        "success": True,
        "campaign": campaign.to_dict(),
        "earnings_credited": round(earnings_amount, 2),
        "message": f"Campaign completed. ${round(earnings_amount, 2)} credited to your balance"
    })


@app.route("/api/earnings/<user_email>/payout-history", methods=["GET"])
def api_payout_history(user_email):
    """Get user's complete payout history"""
    payouts = Payout.query.filter_by(user_email=user_email).order_by(Payout.id.desc()).all()
    earnings = UserEarnings.query.filter_by(user_email=user_email).first()
    
    return jsonify({
        "user_email": user_email,
        "earnings_summary": earnings.to_dict() if earnings else None,
        "payout_history": [p.to_dict() for p in payouts]
    })


# ---------- Payments ----------
@app.route("/api/payments", methods=["GET", "POST"])
def api_payments():
    """Get all payments or create a new payment request"""
    if request.method == "GET":
        user_email = request.args.get("user_email")
        if user_email:
            payments = Payment.query.filter_by(user_email=user_email).order_by(Payment.id.desc()).all()
        else:
            payments = Payment.query.order_by(Payment.id.desc()).all()
        return jsonify([p.to_dict() for p in payments])

    # POST: Create a payment for a campaign
    data = request.get_json() or {}
    user_email = data.get("user_email")
    campaign_id = data.get("campaign_id")
    amount = data.get("amount")
    payment_method = data.get("payment_method", "stripe")  # stripe, paypal, etc.

    if not user_email or not campaign_id or not amount:
        return jsonify({"error": "Missing required fields: user_email, campaign_id, amount"}), 400

    campaign = PaidCampaign.query.get_or_404(campaign_id)
    
    # Verify user owns this campaign
    if campaign.owner_email != user_email:
        return jsonify({"error": "Unauthorized"}), 403

    # Verify payment amount doesn't exceed budget
    if amount > campaign.budget:
        return jsonify({"error": "Payment amount exceeds campaign budget"}), 400

    payment = Payment(
        user_email=user_email,
        campaign_id=campaign_id,
        amount=amount,
        payment_method=payment_method,
        description=f"Payment for campaign: {campaign.title}",
        status="pending"
    )

    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "success": True,
        "payment": payment.to_dict(),
        "message": "Payment initiated. Please complete payment."
    }), 201


@app.route("/api/payments/<int:payment_id>/process", methods=["POST"])
def api_process_payment(payment_id):
    """Process a payment (simulate payment gateway)"""
    payment = Payment.query.get_or_404(payment_id)
    data = request.get_json() or {}
    
    # In production, this would call Stripe/PayPal API
    # For now, we simulate successful payment
    success = data.get("success", True)
    
    if success:
        payment.status = "completed"
        payment.completed_at = now_ts()
        payment.transaction_id = f"TXN_{uuid.uuid4().hex[:12].upper()}"
        
        # Update campaign payment status
        campaign = PaidCampaign.query.get(payment.campaign_id)
        if campaign:
            campaign.payment_status = "paid"
            campaign.status = "active"  # Activate campaign after payment
            campaign.updated_at = now_ts()
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "payment": payment.to_dict(),
            "message": "Payment completed successfully",
            "campaign_activated": True
        })
    else:
        payment.status = "failed"
        db.session.commit()
        
        return jsonify({
            "success": False,
            "payment": payment.to_dict(),
            "error": "Payment failed"
        }), 400


@app.route("/api/payments/<int:payment_id>/refund", methods=["POST"])
def api_refund_payment(payment_id):
    """Refund a payment"""
    payment = Payment.query.get_or_404(payment_id)
    data = request.get_json() or {}
    user_email = data.get("user_email")

    # Only the user who made the payment can refund it
    if payment.user_email != user_email:
        return jsonify({"error": "Unauthorized"}), 403

    # Can only refund completed payments
    if payment.status != "completed":
        return jsonify({"error": f"Cannot refund payment with status: {payment.status}"}), 400

    payment.status = "refunded"
    payment.refunded_at = now_ts()

    # Update campaign payment status
    campaign = PaidCampaign.query.get(payment.campaign_id)
    if campaign:
        campaign.payment_status = "refunded"
        campaign.status = "pending"  # Pause campaign after refund
        campaign.updated_at = now_ts()

    db.session.commit()

    return jsonify({
        "success": True,
        "payment": payment.to_dict(),
        "message": "Refund processed successfully"
    })


@app.route("/api/payments/<int:payment_id>", methods=["GET"])
def api_payment_detail(payment_id):
    """Get payment details"""
    payment = Payment.query.get_or_404(payment_id)
    return jsonify(payment.to_dict())


@app.route("/api/campaigns/<int:campaign_id>/payment-status", methods=["GET"])
def api_campaign_payment_status(campaign_id):
    """Check payment status for a campaign"""
    campaign = PaidCampaign.query.get_or_404(campaign_id)
    payment = Payment.query.filter_by(campaign_id=campaign_id).first()
    
    return jsonify({
        "campaign_id": campaign_id,
        "campaign_status": campaign.status,
        "payment_status": campaign.payment_status,
        "has_payment": payment is not None,
        "payment": payment.to_dict() if payment else None
    })



# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config["PORT"], debug=True)
