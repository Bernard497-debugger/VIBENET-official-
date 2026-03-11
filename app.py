# app.py - VibeNet (Render PostgreSQL Compatible + Sessions)
import os
import uuid
import datetime
import json as _json
from flask import Flask, request, jsonify, send_from_directory, g, render_template_string, session

# ---------- Database Imports ----------
import sqlite3
# Try to import psycopg2 for Render/Postgres. 
# If it fails (local dev without postgres installed), we default to SQLite.
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
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024  
app.config['PORT'] = int(os.environ.get("PORT", 5000))
# IMPORTANT: Render provides DATABASE_URL. If present, we use Postgres.
DATABASE_URL = os.environ.get("DATABASE_URL")
# Secret key for sessions
app.secret_key = os.environ.get("SECRET_KEY", "vibenet_secret_key_change_this_in_production")

# ---------- Database Logic (Hybrid SQLite/Postgres) ----------

def get_db_type():
    """Returns 'postgres' if configured, else 'sqlite'"""
    if DATABASE_URL and HAS_POSTGRES_LIB:
        return 'postgres'
    return 'sqlite'

class PostgresCursorWrapper:
    """
    Translates SQLite syntax (?) to Postgres syntax (%s) on the fly
    so we don't have to rewrite every query in the app.
    """
    def __init__(self, original_cursor):
        self.cursor = original_cursor
        self.lastrowid = None # Postgres uses RETURNING id instead

    def execute(self, sql, args=None):
        # Translate placeholder ? -> %s
        sql = sql.replace('?', '%s')
        
        # Handle auto-increment logic for ID retrieval
        # If it's an INSERT, we append RETURNING id to get the lastrowid equivalent
        is_insert = sql.strip().upper().startswith("INSERT")
        if is_insert:
            sql += " RETURNING id"
        
        if args is None:
            self.cursor.execute(sql)
        else:
            self.cursor.execute(sql, args)
        
        if is_insert:
            # Fetch the new ID
            res = self.cursor.fetchone()
            if res:
                self.lastrowid = res['id']

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()
    
    def __getattr__(self, name):
        return getattr(self.cursor, name)

def get_db():
    if getattr(g, "_db", None) is None:
        if get_db_type() == 'postgres':
            # Connect to Render PostgreSQL
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            g._db = conn
            g._db_type = 'postgres'
        else:
            # Connect to Local SQLite
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            g._db = conn
            g._db_type = 'sqlite'
    return g._db

def get_cursor(db):
    """Returns a cursor that behaves consistently regardless of DB type"""
    if getattr(g, "_db_type", 'sqlite') == 'postgres':
        return PostgresCursorWrapper(db.cursor())
    return db.cursor()

def init_db():
    db = get_db()
    cur = get_cursor(db)
    
    # Define ID syntax based on DB type
    if get_db_type() == 'postgres':
        pk_def = "SERIAL PRIMARY KEY"
    else:
        pk_def = "INTEGER PRIMARY KEY AUTOINCREMENT"

    # Users
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS users (
        id {pk_def},
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        profile_pic TEXT,
        bio TEXT DEFAULT '',
        watch_hours INTEGER DEFAULT 0,
        earnings REAL DEFAULT 0,
        verified INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    # Followers join table
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS followers (
        id {pk_def},
        user_email TEXT,
        follower_email TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    # Posts
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS posts (
        id {pk_def},
        author_email TEXT,
        author_name TEXT,
        profile_pic TEXT,
        text TEXT,
        file_url TEXT,
        timestamp TEXT,
        reactions_json TEXT DEFAULT '{{}}',
        comments_count INTEGER DEFAULT 0
    )""")
    # user_reactions
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS user_reactions (
        id {pk_def},
        user_email TEXT,
        post_id INTEGER,
        emoji TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_email, post_id)
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
    # Ads
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS ads (
        id {pk_def},
        title TEXT,
        owner_email TEXT,
        budget REAL DEFAULT 0,
        impressions INTEGER DEFAULT 0,
        clicks INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Comments
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS comments (
        id {pk_def},
        post_id INTEGER,
        author_email TEXT,
        author_name TEXT,
        profile_pic TEXT,
        text TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Verified Requests
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS verified_requests (
        id {pk_def},
        user_email TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Payout Requests
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS payout_requests (
        id {pk_def},
        user_email TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Reports
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS reports (
        id {pk_def},
        reporter_email TEXT,
        post_id INTEGER,
        reason TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
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

# ---------- Init DB ----------
with app.app_context():
    init_db()

# ---------- Static uploads ----------
# NOTE: On Render free tier, uploaded files vanish on restart. 
# For production, you should use AWS S3 or similar.
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# ---------- Frontend ----------
HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>VibeNet — Local Demo</title>
<style>
:root{--bg:#07101a;--card:#0e1620;--accent:#00bfff;--muted:#9fb0c6}
*{box-sizing:border-box}
body{margin:0;background:linear-gradient(180deg,#041022,#07101a);font-family:Inter,Arial,sans-serif;color:#e6f7ff}
.container{max-width:1000px;margin:18px auto;padding:12px}
.header{display:flex;justify-content:space-between;align-items:center}
.brand{display:flex;gap:10px;align-items:center}
.brand h1{margin:0;color:var(--accent)}
.controls{display:flex;gap:8px;align-items:center}
.card{background:var(--card);padding:12px;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.6)}
.input,textarea{width:100%;padding:10px;margin-top:8px;border-radius:8px;border:0;background:#081221;color:#fff}
.btn{background:var(--accent);border:0;padding:8px 12px;border-radius:8px;color:#001;cursor:pointer}
.nav{display:flex;gap:8px;margin-top:12px}
.nav button{flex:1;padding:10px;border-radius:8px;border:0;background:#081827;color:#fff;cursor:pointer}
.nav button.active{background:linear-gradient(90deg,#0aa,#06d);color:#001}
.row{display:flex;gap:12px;align-items:flex-start}
.col{flex:1}
.sidebar{width:300px}
.post{background:#061221;padding:12px;border-radius:10px;margin-bottom:12px}
.post-header{display:flex;justify-content:space-between;align-items:center}
.post-meta{display:flex;gap:10px;align-items:center}
.profile-pic{width:48px;height:48px;border-radius:50%;object-fit:cover;background:#0b1220}
.timestamp{font-size:12px;color:var(--muted)}
.reaction-bar{display:flex;gap:8px;margin-top:8px}
.reaction-button{background:#081827;border:0;padding:6px 10px;border-radius:8px;color:#fff;cursor:pointer}
.reaction-button.active{background:var(--accent);color:#001}
.follow-btn{background:#102430;border:0;padding:6px 10px;border-radius:8px;color:#fff;cursor:pointer}
.small{font-size:13px;color:var(--muted)}
.video{width:100%;border-radius:8px;background:#000;margin-top:8px}
.icon{font-size:18px;margin-right:6px}
.badge{background:#ff6b6b;color:#fff;padding:2px 8px;border-radius:999px}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="brand">
      <h1>VibeNet</h1>
      <div class="small">Cloud Ready</div>
    </div>
    <div class="controls" id="topControls">
      </div>
  </div>

  <div id="authCard" class="card">
    <h3>Join or Login</h3>
    <div style="display:flex;gap:12px">
      <div style="flex:1">
        <input id="signupName" class="input" placeholder="Full name" />
        <input id="signupEmail" class="input" placeholder="Email" />
        <input id="signupPassword" class="input" type="password" placeholder="Password" />
        <label class="small">Profile picture (optional)</label>
        <input id="signupPic" type="file" accept="image/*" class="input" />
        <button class="btn" onclick="signup()">Sign up</button>
      </div>
      <div style="flex:1">
        <h4>Login</h4>
        <input id="loginEmail" class="input" placeholder="Email" />
        <input id="loginPassword" class="input" type="password" placeholder="Password" />
        <button class="btn" onclick="login()">Login</button>
      </div>
    </div>
  </div>

  <div id="app" style="display:none" class="card">
    <div class="row">
      <div class="col">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <h2 style="margin:0">Feed</h2>
            <div class="small">Share videos & images — watch to earn</div>
          </div>
          <div>
            <button class="btn" onclick="logout()">Logout</button>
          </div>
        </div>

        <div class="nav">
          <button id="navFeed" class="active" onclick="showTab('feed')">🏠 Feed</button>
          <button id="navMessages" onclick="showTab('messages')">📁 Messages</button>
          <button id="navNotifs" onclick="showTab('notifications')">🔔 Notifications <span id="notifCount" class="badge" style="display:none"></span></button>
          <button id="navMonet" onclick="showTab('monet')">💲 Monetization</button>
          <button id="navProfile" onclick="showTab('profile')">👤 Profile</button>
        </div>

        <div id="feed" class="tab">
          <div style="display:flex;gap:12px;align-items:flex-start">
            <textarea id="postText" class="input" rows="2" placeholder="What's on your mind?"></textarea>
            <div style="min-width:220px">
              <input id="fileUpload" type="file" accept="image/*,video/*" class="input" />
              <button class="btn" onclick="addPost()">Post</button>
            </div>
          </div>
          <div id="feedList" style="margin-top:12px"></div>
        </div>

        <div id="messages" class="tab" style="display:none">
          <input id="msgTo" class="input" placeholder="Send to (email)" />
          <textarea id="msgText" class="input" rows="3" placeholder="Type message..."></textarea>
          <button class="btn" onclick="sendMessage()">Send</button>
          <h4 style="margin-top:12px">Inbox</h4>
          <div id="msgList"></div>
        </div>

        <div id="notifications" class="tab" style="display:none">
          <h4>Notifications</h4>
          <div id="notifList"></div>
        </div>

        <div id="monet" class="tab" style="display:none">
          <h4>Monetization Dashboard</h4>
          <p>Followers: <strong id="monFollowers">0</strong></p>
          <p>Watch Hours: <strong id="monWatch">0</strong></p>
          <p>Status: <strong id="monStatus">Not Eligible</strong></p>
          <p>Earnings: <strong id="monEarnings">0.00</strong> credits</p>
          <hr />
          <h4>Ad Placement</h4>
          <input id="adTitle" class="input" placeholder="Ad title" />
          <input id="adBudget" class="input" placeholder="Budget (credits)" />
          <button class="btn" onclick="createAd()">Create Ad</button>
          <div id="adsList" style="margin-top:8px"></div>
        </div>

        <div id="profile" class="tab" style="display:none">
          <h4>Profile</h4>
          <textarea id="profileBio" class="input" rows="3" placeholder="Update your bio"></textarea>
          <button class="btn" onclick="updateBio()">Save bio</button>
          <h4 style="margin-top:12px">My posts</h4>
          <div id="profilePosts"></div>
        </div>

      </div>

      <div class="sidebar">
        <div class="card" style="padding:10px;margin-bottom:12px">
          <h4 style="margin:0">Quick Monetization</h4>
          <div class="small">Followers: <span id="sideFollowers">0</span></div>
          <div class="small">Watch Hours: <span id="sideWatch">0</span></div>
          <div class="small">Earnings: <span id="sideEarnings">0</span></div>
        </div>

        <div class="card" style="padding:10px">
          <h4 style="margin:0">Shortcuts</h4>
          <div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">
            <button class="btn" onclick="showTab('monet')">Open Monetization</button>
            <button class="btn" onclick="showTab('profile')">Open Profile</button>
          </div>
        </div>
      </div>

    </div>
  </div>

</div>

<script>
const API = '/api';
let currentUser = null;

// Helpers
function byId(id){ return document.getElementById(id); }
function escapeHtml(s){ if(!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]); }

// --- SESSION CHECK ON LOAD ---
window.addEventListener('load', async () => {
    // Attempt to restore session
    try {
        const res = await fetch(API + '/me');
        const j = await res.json();
        if(j.user) {
            currentUser = j.user;
            onLogin();
        }
    } catch(e) { console.log('No session'); }
});

// Auth
async function signup(){
  const name = byId('signupName').value.trim();
  const email = byId('signupEmail').value.trim().toLowerCase();
  const password = byId('signupPassword').value;
  if(!name||!email||!password){ alert('Fill all fields'); return; }
  const pic = byId('signupPic').files[0];
  const fd = new FormData();
  fd.append('name', name); fd.append('email', email); fd.append('password', password);
  if(pic) fd.append('file', pic);
  const res = await fetch(API + '/signup', { method:'POST', body: fd });
  const j = await res.json();
  if(j.user){ alert('Signup ok, logged in'); currentUser = j.user; onLogin(); } else { alert(j.error || j.message); }
}

async function login(){
  const email = byId('loginEmail').value.trim().toLowerCase();
  const password = byId('loginPassword').value;
  if(!email||!password){ alert('Fill login'); return; }
  const res = await fetch(API + '/login', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ email, password })});
  const j = await res.json();
  if(j.user){ currentUser = j.user; onLogin(); } else alert(j.error || 'Invalid credentials');
}

async function logout(){
  await fetch(API + '/logout', { method: 'POST' });
  currentUser = null;
  byId('app').style.display = 'none';
  byId('authCard').style.display = 'block';
  byId('topControls').innerHTML = '';
  if(window._vn_poll) clearInterval(window._vn_poll);
}

// After login UI adjustments
function onLogin(){
  byId('authCard').style.display = 'none';
  byId('app').style.display = 'block';
  const top = byId('topControls'); top.innerHTML = '';
  const not = document.createElement('button'); not.className='btn'; not.innerHTML='🔔'; not.onclick = ()=> showTab('notifications');
  const msg = document.createElement('button'); msg.className='btn'; msg.innerHTML='📁'; msg.onclick = ()=> showTab('messages');
  const money = document.createElement('button'); money.className='btn'; money.innerHTML='💲'; money.onclick = ()=> showTab('monet');
  top.append(not,msg,money);
  refreshAll();
  window._vn_poll = setInterval(()=>{ if(currentUser){ loadNotifications(); loadMonetization(); } }, 4000);
}

// Tabs
function showTab(tab){
  ['feed','messages','notifications','monet','profile'].forEach(t => byId(t).style.display = 'none');
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
  byId(tab).style.display = 'block';
  Array.from(document.querySelectorAll('.nav button')).find(b=>b.onclick && b.textContent.toLowerCase().includes(tab[0]))?.classList.add('active');
  if(tab === 'feed'){ byId('navFeed').classList.add('active'); }
  if(tab === 'messages'){ byId('navMessages').classList.add('active'); }
  if(tab === 'notifications'){ byId('navNotifs').classList.add('active'); }
  if(tab === 'monet'){ byId('navMonet').classList.add('active'); }
  if(tab === 'profile'){ byId('navProfile').classList.add('active'); }
}

// Upload helper
async function uploadFile(file){
  const fd = new FormData(); fd.append('file', file);
  const res = await fetch(API + '/upload', { method:'POST', body: fd });
  const j = await res.json();
  return j.url || '';
}

// POSTS
async function addPost(){
  if(!currentUser){ alert('Login first'); return; }
  const text = byId('postText').value.trim();
  const fileEl = byId('fileUpload');
  let url = '';
  if(fileEl.files[0]) url = await uploadFile(fileEl.files[0]);
  if(!text && !url) return;
  const res = await fetch(API + '/posts', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
    author_email: currentUser.email, author_name: currentUser.name, profile_pic: currentUser.profile_pic||'', text, file_url: url
  })});
  const j = await res.json();
  byId('postText').value=''; fileEl.value='';
  await loadFeed(); await loadProfilePosts(); await loadMonetization();
}

// Create post element
function createPostElement(p){
  const div = document.createElement('div'); div.className='post';
  const header = document.createElement('div'); header.className='post-header';
  const meta = document.createElement('div'); meta.className='post-meta';
  const img = document.createElement('img'); img.className='profile-pic'; img.src = p.profile_pic || '/uploads/default.png';
  img.onerror = ()=> img.src = '/uploads/default.png';
  const info = document.createElement('div'); info.innerHTML = `<strong>${escapeHtml(p.author_name || 'Unknown')}</strong><div class="timestamp">${escapeHtml(p.timestamp)}</div>`;
  meta.append(img, info);
  header.append(meta);

  // follow button (if not self)
  if(currentUser && currentUser.email !== p.author_email){
    const fb = document.createElement('button'); fb.className='follow-btn'; fb.textContent='Follow';
    fb.onclick = async ()=>{
      const res = await fetch(API + '/follow', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ follower_email: currentUser.email, target_email: p.author_email })});
      const j = await res.json();
      if(j.success){ fb.classList.toggle('active'); fb.textContent = (fb.classList.contains('active') ? 'Following' : 'Follow'); loadMonetization(); loadSideMonet(); }
    };
    // check follow status
    (async ()=>{
      const r = await fetch(API + `/is_following?f=${encodeURIComponent(currentUser.email)}&t=${encodeURIComponent(p.author_email)}`);
      const jj = await r.json();
      if(jj.following){ fb.classList.add('active'); fb.textContent='Following'; }
    })();
    header.append(fb);
  }

  div.append(header);

  if(p.text){ const t=document.createElement('div'); t.style.marginTop='8px'; t.textContent = p.text; div.append(t); }

  if(p.file_url){
    if(p.file_url.endsWith('.mp4') || p.file_url.endsWith('.webm')){
      const v = document.createElement('video'); v.src = p.file_url; v.controls = true; v.className='video';
      v.dataset.postId = p.id;
      // when ended, call watch
      v.addEventListener('ended', async ()=>{
        await fetch(API + '/watch', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ viewer: currentUser ? currentUser.email : '', post_id: p.id })});
        await fetch(API + '/ads/impression', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ post_id: p.id, viewer: currentUser ? currentUser.email : '' })});
        loadMonetization(); loadSideMonet();
      });
      div.append(v);
    } else {
      const im = document.createElement('img'); im.src = p.file_url; im.style.maxWidth='100%'; div.append(im);
    }
  }

  // reactions
  const bar = document.createElement('div'); bar.className='reaction-bar';
  ['👍','❤️','😂'].forEach(em=>{
    const btn = document.createElement('button'); btn.className='reaction-button'; btn.dataset.emoji = em; btn.textContent = `${em} ${p.reactions && p.reactions[em] ? p.reactions[em] : 0}`;
    if(p.user_reaction && currentUser && p.user_reaction === em) btn.classList.add('active');
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      if(!currentUser){ alert('Login to react'); return; }
      const res = await fetch(API + '/react', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ post_id: p.id, emoji: em, user_email: currentUser.email })});
      const j = await res.json();
      if(j.success){
        // update counts for this post only
        const postEl = div;
        Array.from(postEl.querySelectorAll('.reaction-button')).forEach(rb=>{
          const e = rb.dataset.emoji;
          rb.textContent = `${e} ${ j.reactions && j.reactions[e] !== undefined ? j.reactions[e] : (p.reactions && p.reactions[e] ? p.reactions[e] : 0) }`;
          rb.classList.remove('active');
        });
        // mark clicked
        const clicked = postEl.querySelector(`.reaction-button[data-emoji="${em}"]`);
        if(clicked) clicked.classList.add('active');
      } else alert(j.error || 'React failed');
    };
    bar.append(btn);
  });
  div.append(bar);

  // comments summary
  const cm = document.createElement('div'); cm.className='small'; cm.style.marginTop='6px'; cm.textContent = `${p.comments_count || 0} comments`;
  div.append(cm);

  return div;
}

// Load feed
async function loadFeed(){
  const res = await fetch(API + '/posts');
  const list = await res.json();
  const feed = byId('feedList'); feed.innerHTML = '';
  list.forEach(p => feed.appendChild(createPostElement(p)));
  observeVideos();
}

// observe videos to auto-pause when scrolled out
function observeVideos(){
  if(window._vn_obs) window._vn_obs.disconnect();
  const options = { threshold: 0.25 };
  const observer = new IntersectionObserver((entries)=>{
    entries.forEach(entry=>{
      const v = entry.target;
      if(entry.intersectionRatio < 0.25){ if(!v.paused) v.pause(); }
    });
  }, options);
  document.querySelectorAll('video').forEach(v => observer.observe(v));
  window._vn_obs = observer;
}

// send message
async function sendMessage(){
  if(!currentUser){ alert('Login'); return; }
  const to = byId('msgTo').value.trim(); const text = byId('msgText').value.trim();
  if(!to||!text) return;
  await fetch(API + '/messages', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ from: currentUser.email, to, text })});
  byId('msgText').value=''; loadMessages();
}

// load messages
async function loadMessages(){
  if(!currentUser) return;
  const r = await fetch(API + '/messages/' + encodeURIComponent(currentUser.email));
  const list = await r.json();
  const el = byId('msgList'); el.innerHTML = '';
  list.forEach(m=>{
    const d = document.createElement('div'); d.className='post'; d.innerHTML = `<strong>${escapeHtml(m.sender)}</strong>: ${escapeHtml(m.text)} <div class="timestamp">${escapeHtml(m.timestamp)}</div>`; el.appendChild(d);
  });
}

// notifications
async function loadNotifications(){
  if(!currentUser) return;
  const r = await fetch(API + '/notifications/' + encodeURIComponent(currentUser.email));
  const list = await r.json();
  const el = byId('notifList'); el.innerHTML = '';
  const countEl = byId('notifCount');
  if(list.length){ countEl.style.display='inline-block'; countEl.textContent = list.length; } else countEl.style.display='none';
  list.forEach(n=>{
    const d = document.createElement('div'); d.className='post'; d.innerHTML = `${escapeHtml(n.text)} <div class="timestamp">${escapeHtml(n.timestamp)}</div>`; el.appendChild(d);
  });
}

// follow check
async function isFollowing(follower, followee){
  const r = await fetch(API + `/is_following?f=${encodeURIComponent(follower)}&t=${encodeURIComponent(followee)}`);
  return (await r.json()).following;
}

// profile posts
async function loadProfilePosts(){
  if(!currentUser) return;
  const r = await fetch(API + '/profile/' + encodeURIComponent(currentUser.email));
  const j = await r.json();
  byId('profileBio').value = j.bio || '';
  const el = byId('profilePosts'); el.innerHTML = '';
  (j.posts || []).forEach(p=>{
    const d = document.createElement('div'); d.className='post'; d.innerHTML = `<strong>${escapeHtml(p.author_name)}</strong> <div class="timestamp">${escapeHtml(p.timestamp)}</div><p>${escapeHtml(p.text)}</p>`; if(p.file_url){ if(p.file_url.endsWith('.mp4')) d.innerHTML += `<video src="${p.file_url}" controls style="max-width:100%"></video>`; else d.innerHTML += `<img src="${p.file_url}" style="max-width:100%">`; } el.appendChild(d);
  });
}

// update bio
async function updateBio(){
  if(!currentUser) return;
  const bio = byId('profileBio').value.trim();
  await fetch(API + '/update_bio', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ email: currentUser.email, bio })});
  alert('Bio saved');
}

// monetization
async function loadMonetization(){
  if(!currentUser) return;
  const r = await fetch(API + '/monetization/' + encodeURIComponent(currentUser.email));
  const j = await r.json();
  byId('monFollowers').textContent = j.followers;
  byId('monWatch').textContent = j.watch_hours;
  byId('monWatch') && (byId('monWatch').textContent = j.watch_hours);
  byId('monEarnings').textContent = (j.earnings || 0).toFixed(2);
  byId('sideFollowers').textContent = j.followers;
  byId('sideWatch').textContent = j.watch_hours;
  byId('sideEarnings').textContent = (j.earnings || 0).toFixed(2);
}

// create ad
async function createAd(){
  const title = byId('adTitle').value.trim(); const budget = parseFloat(byId('adBudget').value.trim()||0);
  if(!title || !budget){ alert('Title and budget'); return; }
  const r = await fetch(API + '/ads', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ title, budget, owner: currentUser.email })});
  const j = await r.json();
  alert(j.message || 'Ad created'); loadAds();
}

// load ads
async function loadAds(){
  const r = await fetch(API + '/ads');
  const list = await r.json();
  const el = byId('adsList'); el.innerHTML = '';
  list.forEach(a=>{
    const d = document.createElement('div'); d.className='small'; d.textContent = `${a.title} - budget:${a.budget} - impressions:${a.impressions} clicks:${a.clicks}`; el.appendChild(d);
  });
}

// follow endpoint
async function followUser(follower, target){
  const r = await fetch(API + '/follow', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ follower_email: follower, target_email: target })});
  return r.json();
}

// load side monet quick
async function loadSideMonet(){ await loadMonetization(); loadAds(); }

// refresh everything
async function refreshAll(){ await loadFeed(); await loadMessages(); await loadNotifications(); await loadProfilePosts(); await loadMonetization(); await loadAds(); }

</script>
</body>
</html>
"""

from flask import render_template_string
@app.route("/")
def index():
    return render_template_string(HTML)

# ---------- API: Auth / users ----------
@app.route("/api/signup", methods=["POST"])
def api_signup():
    db = get_db()
    cur = get_cursor(db)
    name = request.form.get("name")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password")
    profile_pic = ""
    if 'file' in request.files:
        f = request.files['file']
        if f and f.filename:
            fn = f"{uuid.uuid4().hex}_{f.filename}"
            path = os.path.join(UPLOAD_DIR, fn)
            f.save(path)
            profile_pic = f"/uploads/{fn}"
    if not email or not password:
        return jsonify({"error":"email+password required"}), 400
    try:
        cur.execute("INSERT INTO users (name,email,password,profile_pic) VALUES (?,?,?,?)", (name, email, password, profile_pic))
        db.commit()
    except Exception as e:
        # Simple catch-all to handle unique constraint violation on both DBs
        if "unique" in str(e).lower():
            return jsonify({"error":"User exists"}), 400
        return jsonify({"error": str(e)}), 500
    
    user = {"name": name, "email": email, "profile_pic": profile_pic, "bio": "", "watch_hours": 0, "earnings": 0}
    session['user_email'] = email
    return jsonify({"user": user})

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password")
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT name,email,profile_pic,bio,watch_hours,earnings FROM users WHERE email=? AND password=?", (email, password))
    r = cur.fetchone()
    if not r:
        return jsonify({"error":"Invalid credentials"}), 401
    user = dict(r)
    session['user_email'] = email
    return jsonify({"user": user})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"status": "logged out"})

@app.route("/api/me", methods=["GET"])
def api_me():
    email = session.get('user_email')
    if not email:
        return jsonify({"user": None})
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT name,email,profile_pic,bio,watch_hours,earnings FROM users WHERE email=?", (email,))
    r = cur.fetchone()
    if r:
        return jsonify({"user": dict(r)})
    return jsonify({"user": None})

# ---------- Upload handling ----------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    if 'file' not in request.files:
        return jsonify({"error":"No file"}), 400
    f = request.files['file']
    if f.filename == "":
        return jsonify({"error":"No filename"}), 400
    fn = f"{uuid.uuid4().hex}_{f.filename}"
    path = os.path.join(UPLOAD_DIR, fn)
    f.save(path)
    return jsonify({"url": f"/uploads/{fn}"})

# ---------- Posts ----------
@app.route("/api/posts", methods=["GET","POST"])
def api_posts():
    db = get_db()
    cur = get_cursor(db)
    if request.method == "GET":
        cur.execute("SELECT * FROM posts ORDER BY id DESC")
        rows = cur.fetchall()
        out = []
        for r in rows:
            rec = dict(r)
            try: rec['reactions'] = _json.loads(rec.get('reactions_json','{}'))
            except: rec['reactions'] = {'👍':0,'❤️':0,'😂':0}
            rec['user_reaction'] = None
            rec['comments_count'] = rec.get('comments_count',0)
            out.append(rec)
        return jsonify(out)
    else:
        data = request.get_json() or {}
        author_email = data.get('author_email')
        author_name = data.get('author_name')
        profile_pic = data.get('profile_pic','')
        text = data.get('text','')
        file_url = data.get('file_url','')
        ts = now_ts()
        reactions_json = _json.dumps({'👍':0,'❤️':0,'😂':0})
        cur.execute("INSERT INTO posts (author_email,author_name,profile_pic,text,file_url,timestamp,reactions_json,comments_count) VALUES (?,?,?,?,?,?,?,?)", (author_email,author_name,profile_pic,text,file_url,ts,reactions_json,0))
        db.commit()
        
        # Get the ID of the new post
        post_id = cur.lastrowid
        cur.execute("SELECT * FROM posts WHERE id=?", (post_id,))
        r = cur.fetchone()
        rec = dict(r)
        rec['reactions'] = _json.loads(rec['reactions_json'])
        rec['user_reaction'] = None
        return jsonify(rec)

# ---------- React ----------
@app.route("/api/react", methods=["POST"])
def api_react_post():
    data = request.get_json() or {}
    post_id = data.get("post_id")
    emoji = data.get("emoji")
    user_email = data.get("user_email")
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT id,reactions_json,author_email FROM posts WHERE id=?", (post_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({"error":"Post not found"}), 404
    reactions = _json.loads(row['reactions_json'] or '{}')
    cur.execute("SELECT emoji FROM user_reactions WHERE user_email=? AND post_id=?", (user_email, post_id))
    prev = cur.fetchone()
    prev_emoji = prev['emoji'] if prev else None
    if prev_emoji == emoji:
        return jsonify({"success":True, "reactions": reactions})
    if prev_emoji:
        reactions[prev_emoji] = max(0, reactions.get(prev_emoji,0)-1)
        cur.execute("DELETE FROM user_reactions WHERE user_email=? AND post_id=?", (user_email, post_id))
    
    # Using INSERT ... ON CONFLICT (Postgres) or REPLACE (SQLite) logic is tricky cross-db.
    # We will use simple Try/Except or Check/Insert logic handled by the "check prev" above + Insert
    try:
        cur.execute("INSERT INTO user_reactions (user_email,post_id,emoji) VALUES (?,?,?)", (user_email, post_id, emoji))
    except:
        # Fallback for unique constraint race condition
        pass
        
    reactions[emoji] = reactions.get(emoji,0) + 1
    cur.execute("UPDATE posts SET reactions_json=? WHERE id=?", (_json.dumps(reactions), post_id))
    db.commit()
    post_author = row['author_email']
    if post_author != user_email:
        cur.execute("INSERT INTO notifications (user_email,text,timestamp) VALUES (?,?,?)", (post_author, f"{emoji} reaction on your post", now_ts()))
        db.commit()
    return jsonify({"success":True, "reactions": reactions})

# ---------- Messages ----------
@app.route("/api/messages", methods=["POST"])
def api_messages_post():
    data = request.get_json() or {}
    sender = data.get("from")
    recipient = data.get("to")
    text = data.get("text")
    ts = now_ts()
    db = get_db()
    cur = get_cursor(db)
    cur.execute("INSERT INTO messages (sender, recipient, text, timestamp) VALUES (?,?,?,?)", (sender, recipient, text, ts))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/messages/<email>")
def api_messages_get(email):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT * FROM messages WHERE recipient=? OR sender=? ORDER BY id DESC", (email, email))
    rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- Notifications ----------
@app.route("/api/notifications/<email>")
def api_notifications_get(email):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT * FROM notifications WHERE user_email=? ORDER BY id DESC", (email,))
    rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- Monetization / Profile ----------
@app.route("/api/monetization/<email>")
def api_monetization_get(email):
    db = get_db()
    cur = get_cursor(db)
    # Count followers
    cur.execute("SELECT COUNT(*) as cnt FROM followers WHERE user_email=?", (email,))
    res = cur.fetchone()
    followers = res['cnt'] if res else 0
    # Get user details for watch/earnings
    cur.execute("SELECT watch_hours, earnings FROM users WHERE email=?", (email,))
    u = cur.fetchone()
    if u:
        return jsonify({"followers": followers, "watch_hours": u['watch_hours'], "earnings": u['earnings']})
    return jsonify({"followers": 0, "watch_hours": 0, "earnings": 0})

@app.route("/api/profile/<email>")
def api_profile_get(email):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT bio FROM users WHERE email=?", (email,))
    u = cur.fetchone()
    cur.execute("SELECT * FROM posts WHERE author_email=? ORDER BY id DESC", (email,))
    posts = [dict(r) for r in cur.fetchall()]
    return jsonify({"bio": u['bio'] if u else "", "posts": posts})

@app.route("/api/update_bio", methods=["POST"])
def api_update_bio():
    data = request.get_json() or {}
    email = data.get("email")
    bio = data.get("bio")
    db = get_db()
    cur = get_cursor(db)
    cur.execute("UPDATE users SET bio=? WHERE email=?", (bio, email))
    db.commit()
    return jsonify({"success": True})

# ---------- Following ----------
@app.route("/api/follow", methods=["POST"])
def api_follow():
    data = request.get_json() or {}
    follower = data.get("follower_email")
    target = data.get("target_email")
    db = get_db()
    cur = get_cursor(db)
    # Check if exists
    cur.execute("SELECT id FROM followers WHERE user_email=? AND follower_email=?", (target, follower))
    if cur.fetchone():
        # Unfollow
        cur.execute("DELETE FROM followers WHERE user_email=? AND follower_email=?", (target, follower))
        db.commit()
        return jsonify({"success": True, "status": "unfollowed"})
    else:
        # Follow
        cur.execute("INSERT INTO followers (user_email, follower_email) VALUES (?,?)", (target, follower))
        # Notif
        cur.execute("INSERT INTO notifications (user_email, text, timestamp) VALUES (?,?,?)", (target, f"{follower} followed you", now_ts()))
        db.commit()
        return jsonify({"success": True, "status": "followed"})

@app.route("/api/is_following")
def api_is_following():
    f = request.args.get("f")
    t = request.args.get("t")
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT id FROM followers WHERE user_email=? AND follower_email=?", (t, f))
    return jsonify({"following": True if cur.fetchone() else False})

# ---------- Watch / Ads ----------
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

@app.route("/api/ads", methods=["GET","POST"])
def api_ads():
    db = get_db()
    cur = get_cursor(db)
    if request.method == "POST":
        data = request.get_json() or {}
        cur.execute("INSERT INTO ads (title, owner_email, budget) VALUES (?,?,?)", (data.get('title'), data.get('owner'), data.get('budget')))
        db.commit()
        return jsonify({"message": "Ad created"})
    else:
        cur.execute("SELECT * FROM ads ORDER BY id DESC")
        return jsonify([dict(r) for r in cur.fetchall()])

@app.route("/api/ads/impression", methods=["POST"])
def api_ads_impression():
    # Placeholder for ad logic
    return jsonify({"success": True})

# ---------- Comments ----------
@app.route("/api/comments", methods=["GET","POST"])
def api_comments():
    db = get_db()
    cur = get_cursor(db)
    if request.method == "GET":
        post_id = request.args.get("post_id")
        cur.execute("SELECT * FROM comments WHERE post_id=? ORDER BY id DESC", (post_id,))
        return jsonify([dict(r) for r in cur.fetchall()])
    else:
        data = request.get_json() or {}
        post_id = data.get("post_id")
        author_email = data.get("author_email")
        author_name = data.get("author_name")
        profile_pic = data.get("profile_pic","")
        text = data.get("text","")
        cur.execute("INSERT INTO comments (post_id,author_email,author_name,profile_pic,text) VALUES (?,?,?,?,?)", 
                   (post_id,author_email,author_name,profile_pic,text))
        cur.execute("UPDATE posts SET comments_count=comments_count+1 WHERE id=?", (post_id,))
        db.commit()
        return jsonify({"success":True})

# ---------- Verified Badges ----------
@app.route("/api/verified-badge/request", methods=["POST"])
def request_verified():
    data = request.get_json() or {}
    user_email = data.get("user_email")
    db = get_db()
    cur = get_cursor(db)
    cur.execute("INSERT INTO verified_requests (user_email) VALUES (?)", (user_email,))
    db.commit()
    return jsonify({"success":True, "message":"Verified badge request submitted. Admin will review."})

@app.route("/api/verified-status")
def verified_status():
    email = session.get("user_email")
    if not email:
        return jsonify({"verified":False})
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT verified FROM users WHERE email=?", (email,))
    r = cur.fetchone()
    verified = bool(r['verified']) if r else False
    return jsonify({"verified":verified})

# ---------- Payouts ----------
@app.route("/api/payout-request", methods=["POST"])
def payout_request():
    data = request.get_json() or {}
    user_email = data.get("user_email")
    amount = data.get("amount")
    if not amount or amount < 10:
        return jsonify({"error":"Minimum payout is P10"}), 400
    db = get_db()
    cur = get_cursor(db)
    cur.execute("INSERT INTO payout_requests (user_email, amount) VALUES (?,?)", (user_email, amount))
    cur.execute("UPDATE users SET earnings=earnings-? WHERE email=?", (amount, user_email))
    db.commit()
    return jsonify({"success":True, "message":"Payout request submitted"})

# ---------- Reports ----------
@app.route("/api/report", methods=["POST"])
def api_report():
    data = request.get_json() or {}
    reporter_email = data.get("reporter_email")
    post_id = data.get("post_id")
    reason = data.get("reason")
    db = get_db()
    cur = get_cursor(db)
    cur.execute("INSERT INTO reports (reporter_email, post_id, reason) VALUES (?,?,?)", (reporter_email, post_id, reason))
    db.commit()
    return jsonify({"success":True, "message":"Report submitted"})

# ---------- Admin Dashboard ----------
@app.route("/admin")
def admin_dashboard():
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    if session.get("user_email") != admin_email:
        return jsonify({"error":"Unauthorized"}), 403
    
    db = get_db()
    cur = get_cursor(db)
    
    # Stats
    cur.execute("SELECT COUNT(*) as count FROM users")
    total_users = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) as count FROM posts")
    total_posts = cur.fetchone()['count']
    
    cur.execute("SELECT SUM(earnings) as total FROM users")
    total_earnings = cur.fetchone()['total'] or 0
    
    # Pending requests
    cur.execute("SELECT * FROM verified_requests WHERE status='pending'")
    pending_verified = [dict(r) for r in cur.fetchall()]
    
    cur.execute("SELECT * FROM payout_requests WHERE status='pending'")
    pending_payouts = [dict(r) for r in cur.fetchall()]
    
    cur.execute("SELECT * FROM reports WHERE status='pending'")
    pending_reports = [dict(r) for r in cur.fetchall()]
    
    return jsonify({
        "stats": {
            "total_users": total_users,
            "total_posts": total_posts,
            "total_earnings": total_earnings
        },
        "pending": {
            "verified": pending_verified,
            "payouts": pending_payouts,
            "reports": pending_reports
        }
    })

@app.route("/api/admin/verified/<int:req_id>/approve", methods=["POST"])
def approve_verified(req_id):
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    if session.get("user_email") != admin_email:
        return jsonify({"error":"Unauthorized"}), 403
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT user_email FROM verified_requests WHERE id=?", (req_id,))
    r = cur.fetchone()
    if not r:
        return jsonify({"error":"Not found"}), 404
    
    user_email = r['user_email']
    cur.execute("UPDATE verified_requests SET status='approved' WHERE id=?", (req_id,))
    cur.execute("UPDATE users SET verified=1 WHERE email=?", (user_email,))
    db.commit()
    return jsonify({"success":True})

@app.route("/api/admin/payout/<int:payout_id>/approve", methods=["POST"])
def approve_payout(payout_id):
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    if session.get("user_email") != admin_email:
        return jsonify({"error":"Unauthorized"}), 403
    
    db = get_db()
    cur = get_cursor(db)
    cur.execute("UPDATE payout_requests SET status='approved' WHERE id=?", (payout_id,))
    db.commit()
    return jsonify({"success":True})

if __name__ == "__main__":
    # Local development
    app.run(host="0.0.0.0", port=app.config['PORT'], debug=True)