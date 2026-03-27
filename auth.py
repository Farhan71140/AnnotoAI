"""
AnnotoAI Authentication & Usage Tracking System
- Student login with username/password
- Admin dashboard to manage users
- Usage tracking (sessions, hours, tasks)
- Only authorized users can access the tool
"""

import json
import os
import hashlib
import secrets
import datetime

AUTH_FILE = os.path.join('/tmp', 'auth_data.json')

# ── Admin credentials ──
ADMIN_1_USERNAME = "farhan"
ADMIN_1_PASSWORD = "annoto@admin2026"

ADMIN_2_USERNAME = "Thaslim"
ADMIN_2_PASSWORD = "annoto@admin2026"

# Primary admin username (used for removal protection)
PROTECTED_ADMINS = [ADMIN_1_USERNAME, ADMIN_2_USERNAME]

def _hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def clear_all_sessions():
    """Called on server startup — wipes all active sessions so stale
    browser tokens are rejected and users must log in again."""
    if not os.path.exists(AUTH_FILE):
        return
    try:
        with open(AUTH_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data["sessions"] = {}
        with open(AUTH_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("[*] All sessions cleared on startup")
    except Exception as e:
        print(f"[!] Could not clear sessions: {e}")

def _load_data():
    if not os.path.exists(AUTH_FILE):
        # Create default data file with both admins
        data = {
            "users": {
                ADMIN_1_USERNAME: {
                    "password": _hash_password(ADMIN_1_PASSWORD),
                    "role": "admin",
                    "name": "Md Farhan Uddin",
                    "created": datetime.datetime.now().isoformat(),
                    "active": True
                },
                ADMIN_2_USERNAME: {
                    "password": _hash_password(ADMIN_2_PASSWORD),
                    "role": "admin",
                    "name": "Thaslim",
                    "created": datetime.datetime.now().isoformat(),
                    "active": True
                }
            },
            "sessions": {},
            "usage_log": []
        }
        _save_data(data)
        return data
    with open(AUTH_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _save_data(data):
    with open(AUTH_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def login(username, password):
    """Authenticate user. Returns session token or None."""
    data = _load_data()
    user = data["users"].get(username)
    if not user:
        return {"error": "Invalid username or password"}
    if not user.get("active", True):
        return {"error": "Your account has been disabled. Contact admin."}
    if user["password"] != _hash_password(password):
        return {"error": "Invalid username or password"}

    # Create session token
    token = secrets.token_hex(32)
    data["sessions"][token] = {
        "username": username,
        "name":     user.get("name", username),
        "role":     user.get("role", "student"),
        "login_time": datetime.datetime.now().isoformat(),
        "last_active": datetime.datetime.now().isoformat(),
        "tasks_done": 0,
        "transcriptions": 0,
        "annotations": 0
    }

    # Log login
    data["usage_log"].append({
        "event":    "login",
        "username": username,
        "name":     user.get("name", username),
        "time":     datetime.datetime.now().isoformat()
    })

    _save_data(data)
    return {
        "status": "ok",
        "token":  token,
        "name":   user.get("name", username),
        "role":   user.get("role", "student")
    }

def logout(token):
    """End session and record usage."""
    data = _load_data()
    session = data["sessions"].get(token)
    if not session:
        return {"status": "ok"}

    # Calculate session duration
    login_time = datetime.datetime.fromisoformat(session["login_time"])
    duration   = (datetime.datetime.now() - login_time).total_seconds() / 3600

    # Log logout
    data["usage_log"].append({
        "event":        "logout",
        "username":     session["username"],
        "name":         session["name"],
        "time":         datetime.datetime.now().isoformat(),
        "duration_hrs": round(duration, 2),
        "tasks_done":   session.get("tasks_done", 0),
        "transcriptions": session.get("transcriptions", 0),
        "annotations":  session.get("annotations", 0)
    })

    del data["sessions"][token]
    _save_data(data)
    return {"status": "ok"}

def verify_token(token):
    """Check if token is valid. Returns user info or None."""
    if not token:
        return None
    data = _load_data()
    session = data["sessions"].get(token)
    if not session:
        return None

    # Update last active
    session["last_active"] = datetime.datetime.now().isoformat()
    data["sessions"][token] = session
    _save_data(data)
    return session

def record_action(token, action):
    """Record a user action (transcription/annotation)."""
    data = _load_data()
    session = data["sessions"].get(token)
    if not session:
        return

    if action == "transcription":
        session["transcriptions"] = session.get("transcriptions", 0) + 1
    elif action == "annotation":
        session["annotations"]  = session.get("annotations", 0) + 1
        session["tasks_done"]   = session.get("tasks_done", 0) + 1

    # Log action
    data["usage_log"].append({
        "event":    action,
        "username": session["username"],
        "name":     session["name"],
        "time":     datetime.datetime.now().isoformat()
    })

    data["sessions"][token] = session
    _save_data(data)

def add_user(username, password, name, role="student"):
    """Add a new user (admin only)."""
    data = _load_data()
    if username in data["users"]:
        return {"error": f"User '{username}' already exists"}
    data["users"][username] = {
        "password": _hash_password(password),
        "role":     role,
        "name":     name,
        "created":  datetime.datetime.now().isoformat(),
        "active":   True
    }
    data["usage_log"].append({
        "event":    "user_created",
        "username": username,
        "name":     name,
        "time":     datetime.datetime.now().isoformat()
    })
    _save_data(data)
    return {"status": "ok", "message": f"User '{username}' created successfully"}

def remove_user(username):
    """Remove a user."""
    data = _load_data()
    if username not in data["users"]:
        return {"error": "User not found"}
    if username in PROTECTED_ADMINS:
        return {"error": "Cannot remove admin accounts"}
    del data["users"][username]
    # Invalidate their sessions
    to_delete = [t for t, s in data["sessions"].items() if s["username"] == username]
    for t in to_delete:
        del data["sessions"][t]
    _save_data(data)
    return {"status": "ok", "message": f"User '{username}' removed"}

def toggle_user(username, active):
    """Enable or disable a user."""
    data = _load_data()
    if username not in data["users"]:
        return {"error": "User not found"}
    if username in PROTECTED_ADMINS and not active:
        return {"error": "Cannot disable admin accounts"}
    data["users"][username]["active"] = active
    _save_data(data)
    return {"status": "ok"}

def reset_password(username, new_password):
    """Reset a user's password."""
    data = _load_data()
    if username not in data["users"]:
        return {"error": "User not found"}
    data["users"][username]["password"] = _hash_password(new_password)
    _save_data(data)
    return {"status": "ok", "message": f"Password reset for '{username}'"}

def get_dashboard_data():
    """Get full dashboard data for admin."""
    data = _load_data()
    now  = datetime.datetime.now()

    # Active sessions
    active_sessions = []
    for token, session in data["sessions"].items():
        login_time = datetime.datetime.fromisoformat(session["login_time"])
        duration   = (now - login_time).total_seconds() / 3600
        last_active = datetime.datetime.fromisoformat(session["last_active"])
        idle_mins   = (now - last_active).total_seconds() / 60
        active_sessions.append({
            "username":    session["username"],
            "name":        session["name"],
            "login_time":  session["login_time"],
            "duration_hrs": round(duration, 2),
            "idle_mins":   round(idle_mins, 1),
            "tasks_done":  session.get("tasks_done", 0),
            "transcriptions": session.get("transcriptions", 0),
            "annotations": session.get("annotations", 0)
        })

    # Per-user stats from log
    user_stats = {}
    for entry in data["usage_log"]:
        uname = entry.get("username","")
        if uname not in user_stats:
            user_stats[uname] = {
                "username": uname,
                "name":     entry.get("name", uname),
                "total_sessions": 0,
                "total_hours":    0,
                "total_tasks":    0,
                "last_seen":      ""
            }
        if entry["event"] == "logout":
            user_stats[uname]["total_sessions"] += 1
            user_stats[uname]["total_hours"]    += entry.get("duration_hrs", 0)
            user_stats[uname]["total_tasks"]    += entry.get("tasks_done", 0)
            user_stats[uname]["last_seen"]       = entry["time"]

    # Today's stats
    today_str  = now.date().isoformat()
    today_log  = [e for e in data["usage_log"] if e.get("time","").startswith(today_str)]
    today_logins = len([e for e in today_log if e["event"] == "login"])
    today_tasks  = sum(e.get("tasks_done",0) for e in today_log if e["event"]=="logout")
    today_annotations = len([e for e in today_log if e["event"]=="annotation"])

    # All users list (exclude both admins from student table)
    users_list = []
    for uname, udata in data["users"].items():
        stats = user_stats.get(uname, {})
        users_list.append({
            "username":       uname,
            "name":           udata.get("name", uname),
            "role":           udata.get("role", "student"),
            "active":         udata.get("active", True),
            "created":        udata.get("created", ""),
            "total_sessions": stats.get("total_sessions", 0),
            "total_hours":    round(stats.get("total_hours", 0), 2),
            "total_tasks":    stats.get("total_tasks", 0),
            "last_seen":      stats.get("last_seen", "Never")
        })

    return {
        "summary": {
            "total_users":       len([u for u in data["users"].values() if u.get("role") != "admin"]),
            "active_now":        len(active_sessions),
            "today_logins":      today_logins,
            "today_tasks":       today_tasks,
            "today_annotations": today_annotations,
            "total_log_entries": len(data["usage_log"])
        },
        "active_sessions": active_sessions,
        "users":           users_list,
        "recent_log":      list(reversed(data["usage_log"]))[:50]
    }