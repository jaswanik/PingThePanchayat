from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from database import get_db_connection, init_db
from logic import detect_severity, calculate_health_score, get_recommendation
import os
import random
import string
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
from report_generator import generate_pdf_report, generate_weekly_report, generate_monthly_report

frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))
app = Flask(__name__, static_folder=frontend_dir, static_url_path='')
CORS(app)

# Initialize DB on start
init_db()

# In-memory OTP store: { email: { otp, expires } }
otp_store = {}

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

def format_ref(complaint_id):
    return f"PTP-{datetime.now().year}-{str(complaint_id).zfill(4)}"

def gen_report_id(report_type):
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    prefix = {'Weekly': 'WEEK', 'Monthly': 'MON', 'Custom': 'CUST'}.get(report_type, 'RPT')
    return f"RPT-{prefix}-{ts}"

@app.route('/api')
@app.route('/api/')
def api_status():
    return jsonify({
        "status": "online",
        "service": "PingThePanchayat API",
        "version": "3.0"
    })

# ─── AUTH ENDPOINTS ──────────────────────────────────────────────────────────


@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    try:
        conn = get_db_connection()
        existing_phone = conn.execute(
            "SELECT * FROM users WHERE contact_info = ?", (data['contact'],)
        ).fetchone()
        if existing_phone:
            conn.close()
            return jsonify({"status": "error", "message": "Contact number already registered"}), 400

        existing_email = conn.execute(
            "SELECT * FROM users WHERE email = ?", (data['email'],)
        ).fetchone()
        if existing_email:
            conn.close()
            return jsonify({"status": "error", "message": "Email address already registered"}), 400

        conn.execute(
            "INSERT INTO users (name, email, password, contact_info, security_question, security_answer) VALUES (?, ?, ?, ?, ?, ?)",
            (data['name'], data['email'], data['password'], data['contact'],
             data.get('security_question', ''), data.get('security_answer', ''))
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ? AND password = ?",
        (data['email'], data['password'])
    ).fetchone()
    conn.close()
    if user:
        return jsonify({"status": "success", "user": dict(user)})
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401


@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    try:
        conn = get_db_connection()
        admin = conn.execute(
            "SELECT * FROM admins WHERE username = ? AND password = ?",
            (username, password)
        ).fetchone()
        conn.close()
        if admin:
            return jsonify({"status": "success", "admin": dict(admin)})
    except Exception as e:
        print("DB admin login check failed:", e)

    # Fail-safe default admin fallback
    if username == 'admin' and password == 'admin123':
        return jsonify({"status": "success", "admin": {"admin_id": 1, "username": "admin"}})

    return jsonify({"status": "error", "message": "Invalid admin credentials"}), 401



# ─── PASSWORD RECOVERY: SECURITY QUESTION ────────────────────────────────────

@app.route('/api/auth/recover-question', methods=['GET'])
def get_security_question():
    email = request.args.get('email', '').strip()
    if not email:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    conn = get_db_connection()
    user = conn.execute(
        "SELECT security_question FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    if not user or not user['security_question']:
        return jsonify({"status": "error", "message": "No account found or no security question set"}), 404
    return jsonify({"status": "success", "question": user['security_question']})


@app.route('/api/auth/recover-question', methods=['POST'])
def verify_security_question():
    data = request.json
    email = data.get('email', '').strip()
    answer = data.get('answer', '').strip().lower()
    if not email or not answer:
        return jsonify({"status": "error", "message": "Email and answer are required"}), 400
    conn = get_db_connection()
    user = conn.execute(
        "SELECT security_answer FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    if not user:
        return jsonify({"status": "error", "message": "Account not found"}), 404
    if user['security_answer'].lower() != answer:
        return jsonify({"status": "error", "message": "Incorrect answer"}), 401
    return jsonify({"status": "success", "message": "Answer verified"})


@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password_by_question():
    data = request.json
    email = data.get('email', '').strip()
    answer = data.get('answer', '').strip().lower()
    new_password = data.get('new_password', '').strip()
    if not all([email, answer, new_password]):
        return jsonify({"status": "error", "message": "All fields required"}), 400
    conn = get_db_connection()
    user = conn.execute(
        "SELECT security_answer FROM users WHERE email = ?", (email,)
    ).fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "Account not found"}), 404
    if user['security_answer'].lower() != answer:
        conn.close()
        return jsonify({"status": "error", "message": "Incorrect answer"}), 401
    conn.execute("UPDATE users SET password = ? WHERE email = ?", (new_password, email))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Password reset successfully"})


# ─── PASSWORD RECOVERY: OTP ───────────────────────────────────────────────────

@app.route('/api/auth/recover-otp', methods=['POST'])
def send_otp():
    data = request.json
    email = data.get('email', '').strip()
    if not email:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    conn = get_db_connection()
    user = conn.execute("SELECT user_id, name FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    if not user:
        return jsonify({"status": "error", "message": "No account found with this email"}), 404

    otp = ''.join(random.choices(string.digits, k=6))
    expires = datetime.now() + timedelta(minutes=10)
    otp_store[email] = {"otp": otp, "expires": expires}
    print(f"[SIMULATED OTP] To: {email} | OTP: {otp} | Expires: {expires}")

    return jsonify({
        "status": "success",
        "message": f"OTP sent to your registered mobile number (Simulated OTP: {otp})",
        "simulated_otp": otp
    })


@app.route('/api/auth/reset-password-otp', methods=['POST'])
def reset_password_otp():
    data = request.json
    email = data.get('email', '').strip()
    otp = data.get('otp', '').strip()
    new_password = data.get('new_password', '').strip()

    if not all([email, otp, new_password]):
        return jsonify({"status": "error", "message": "All fields required"}), 400

    record = otp_store.get(email)
    if not record:
        return jsonify({"status": "error", "message": "No OTP requested for this email"}), 400
    if datetime.now() > record['expires']:
        del otp_store[email]
        return jsonify({"status": "error", "message": "OTP has expired. Please request a new one"}), 400
    if record['otp'] != otp:
        return jsonify({"status": "error", "message": "Invalid OTP"}), 401

    conn = get_db_connection()
    conn.execute("UPDATE users SET password = ? WHERE email = ?", (new_password, email))
    conn.commit()
    conn.close()
    del otp_store[email]
    return jsonify({"status": "success", "message": "Password reset successfully"})


# ─── PROFILE ──────────────────────────────────────────────────────────────────

@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT user_id, name, email, contact_info, security_question FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404
    return jsonify({"status": "success", "user": dict(user)})


@app.route('/api/users/<int:user_id>', methods=['PATCH'])
def update_user_profile(user_id):
    data = request.json
    try:
        conn = get_db_connection()
        if 'name' in data:
            conn.execute("UPDATE users SET name = ? WHERE user_id = ?", (data['name'], user_id))
        if 'contact_info' in data:
            conn.execute("UPDATE users SET contact_info = ? WHERE user_id = ?", (data['contact_info'], user_id))
        if 'security_question' in data:
            conn.execute("UPDATE users SET security_question = ? WHERE user_id = ?", (data['security_question'], user_id))
        if 'security_answer' in data:
            conn.execute("UPDATE users SET security_answer = ? WHERE user_id = ?", (data['security_answer'], user_id))
        conn.commit()
        user = conn.execute("SELECT user_id, name, email, contact_info, security_question FROM users WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()
        return jsonify({"status": "success", "user": dict(user)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/users/<int:user_id>/change-password', methods=['POST'])
def change_password(user_id):
    data = request.json
    current = data.get('current_password', '')
    new_pwd = data.get('new_password', '')
    conn = get_db_connection()
    user = conn.execute("SELECT password FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"}), 404
    if user['password'] != current:
        conn.close()
        return jsonify({"status": "error", "message": "Current password is incorrect"}), 401
    conn.execute("UPDATE users SET password = ? WHERE user_id = ?", (new_pwd, user_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Password changed successfully"})


# ─── COMPLAINTS ───────────────────────────────────────────────────────────────

@app.route('/api/complaints', methods=['POST'])
def add_complaint():
    data = request.json
    user_id = data.get('user_id')
    issue_type = data.get('issue_type')
    location = data.get('location')
    description = data.get('description')

    severity = detect_severity(description, issue_type)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO complaints (user_id, issue_type, location, description, severity, status, lifecycle_status)
        VALUES (?, ?, ?, ?, ?, 'Pending', 'Submitted')
    ''', (user_id, issue_type, location, description, severity))
    cid = cursor.lastrowid

    ref = format_ref(cid)
    cursor.execute('''
        INSERT INTO notifications (user_id, title, message)
        VALUES (?, ?, ?)
    ''', (user_id, "Complaint Submitted Successfully",
          f"Your complaint {ref} for '{issue_type}' has been recorded and is currently under review."))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": "Complaint registered",
        "severity": severity,
        "complaint_id": cid,
        "reference": ref
    }), 201


@app.route('/api/complaints/user/<int:user_id>', methods=['GET'])
def get_user_complaints(user_id):
    conn = get_db_connection()
    complaints = conn.execute(
        "SELECT * FROM complaints WHERE user_id = ? ORDER BY timestamp DESC", (user_id,)
    ).fetchall()
    conn.close()
    result = []
    for row in complaints:
        c = dict(row)
        c['reference'] = format_ref(c['complaint_id'])
        result.append(c)
    return jsonify(result)


@app.route('/api/complaints', methods=['GET'])
def get_all_complaints():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, u.name, u.contact_info
        FROM complaints c
        JOIN users u ON c.user_id = u.user_id
        ORDER BY timestamp DESC
    ''')
    complaints = []
    for row in cursor.fetchall():
        c = dict(row)
        c['reference'] = format_ref(c['complaint_id'])
        complaints.append(c)
    conn.close()
    return jsonify(complaints)


@app.route('/api/status', methods=['PATCH'])
def update_status():
    data = request.json
    cid = data.get('complaint_id')
    status = data.get('status')

    conn = get_db_connection()
    conn.execute("UPDATE complaints SET status = ? WHERE complaint_id = ?", (status, cid))
    comp = conn.execute(
        "SELECT user_id, complaint_id, issue_type FROM complaints WHERE complaint_id = ?", (cid,)
    ).fetchone()
    if comp:
        user_id = comp['user_id']
        ref = format_ref(cid)
        title = f"Complaint Status Updated: {status}"
        msg = f"Your complaint {ref} ({comp['issue_type']}) status has been updated to '{status}'."
        conn.execute(
            "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
            (user_id, title, msg)
        )

    conn.commit()
    conn.close()
    return jsonify({"status": "success"})


@app.route('/api/complaints/notes', methods=['PATCH'])
def update_complaint_notes():
    data = request.json
    if not data or 'complaint_id' not in data:
        return jsonify({"status": "error", "message": "complaint_id is required"}), 400

    cid = data['complaint_id']
    admin_notes = data.get('admin_notes')
    assigned_team = data.get('assigned_team')
    severity = data.get('severity')

    try:
        conn = get_db_connection()
        if admin_notes is not None:
            conn.execute("UPDATE complaints SET admin_notes = ? WHERE complaint_id = ?", (admin_notes, cid))
        if assigned_team is not None:
            conn.execute("UPDATE complaints SET assigned_team = ? WHERE complaint_id = ?", (assigned_team, cid))
        if severity is not None:
            conn.execute("UPDATE complaints SET severity = ? WHERE complaint_id = ?", (severity, cid))

        comp = conn.execute(
            "SELECT user_id, complaint_id, issue_type FROM complaints WHERE complaint_id = ?", (cid,)
        ).fetchone()
        if comp:
            user_id = comp['user_id']
            ref = format_ref(cid)
            title = "Complaint Administrative Update"
            details = []
            if admin_notes is not None:
                details.append("administrative response was added")
            if assigned_team is not None:
                details.append(f"assigned force '{assigned_team}' was dispatched")
            if severity is not None:
                details.append(f"severity updated to '{severity}'")

            if details:
                msg = f"Your complaint {ref} ({comp['issue_type']}) has been updated: {', '.join(details)}."
                conn.execute(
                    "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
                    (user_id, title, msg)
                )

        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── v2.0: COMPLAINT LIFECYCLE ────────────────────────────────────────────────

@app.route('/api/complaints/lifecycle', methods=['PATCH'])
def update_lifecycle():
    data = request.json
    if not data or 'complaint_id' not in data:
        return jsonify({"status": "error", "message": "complaint_id is required"}), 400

    cid = data['complaint_id']
    lifecycle_status = data.get('lifecycle_status')

    # Map lifecycle → status for backward compat
    status_map = {
        'Submitted':  'Pending',
        'Verified':   'Pending',
        'Escalated':  'Pending',
        'In Progress':'In Progress',
        'Resolved':   'Resolved',
        'Archived':   'Resolved'
    }

    try:
        conn = get_db_connection()
        conn.execute(
            "UPDATE complaints SET lifecycle_status = ? WHERE complaint_id = ?",
            (lifecycle_status, cid)
        )
        if lifecycle_status in status_map:
            conn.execute(
                "UPDATE complaints SET status = ? WHERE complaint_id = ?",
                (status_map[lifecycle_status], cid)
            )

        # Notify user
        comp = conn.execute(
            "SELECT user_id, issue_type FROM complaints WHERE complaint_id = ?", (cid,)
        ).fetchone()
        if comp:
            ref = format_ref(cid)
            title = f"Complaint {lifecycle_status}"
            msg = f"Your complaint {ref} ({comp['issue_type']}) has been moved to '{lifecycle_status}' stage."
            conn.execute(
                "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
                (comp['user_id'], title, msg)
            )

        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── v3.0: DEPARTMENT ASSIGNMENT ─────────────────────────────────────────────

@app.route('/api/complaints/<int:cid>/assign-department', methods=['PATCH'])
def assign_department(cid):
    data = request.json or {}
    department = data.get('department', '').strip()
    if not department:
        return jsonify({"status": "error", "message": "department is required"}), 400
    try:
        conn = get_db_connection()
        conn.execute(
            "UPDATE complaints SET department = ?, lifecycle_status = 'Verified', status = 'Pending' WHERE complaint_id = ?",
            (department, cid)
        )
        comp = conn.execute("SELECT user_id, issue_type FROM complaints WHERE complaint_id = ?", (cid,)).fetchone()
        if comp:
            conn.execute(
                "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
                (comp['user_id'], "Complaint Assigned to Department",
                 f"Your complaint {format_ref(cid)} ({comp['issue_type']}) has been assigned to the {department} department.")
            )
        conn.execute(
            "INSERT INTO complaint_timeline (complaint_id, stage, note, actor) VALUES (?, 'Verified', ?, 'admin')",
            (cid, f"Assigned to {department} department.")
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── v3.0: ACTION PLAN ────────────────────────────────────────────────────────

@app.route('/api/complaints/<int:cid>/action-plan', methods=['PATCH'])
def set_action_plan(cid):
    data = request.json or {}
    action_plan = data.get('action_plan', '').strip()
    action_deadline = data.get('action_deadline', '').strip()
    action_priority = data.get('action_priority', 'Normal').strip()
    if not action_plan:
        return jsonify({"status": "error", "message": "action_plan is required"}), 400
    try:
        conn = get_db_connection()
        conn.execute(
            """UPDATE complaints SET action_plan=?, action_deadline=?, action_priority=?,
               lifecycle_status='In Progress', status='In Progress' WHERE complaint_id=?""",
            (action_plan, action_deadline, action_priority, cid)
        )
        comp = conn.execute("SELECT user_id, issue_type FROM complaints WHERE complaint_id=?", (cid,)).fetchone()
        if comp:
            conn.execute(
                "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
                (comp['user_id'], "Action Plan Created for Your Complaint",
                 f"An action plan has been created for your complaint {format_ref(cid)} ({comp['issue_type']}). Work is now in progress.")
            )
        conn.execute(
            "INSERT INTO complaint_timeline (complaint_id, stage, note, actor) VALUES (?, 'In Progress', ?, 'admin')",
            (cid, f"Action plan set. Priority: {action_priority}. Deadline: {action_deadline}.")
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── v3.0: RESOLVE WITH EVIDENCE ─────────────────────────────────────────────

@app.route('/api/complaints/<int:cid>/resolve', methods=['PATCH'])
def resolve_complaint(cid):
    data = request.json or {}
    resolution_notes = data.get('resolution_notes', '').strip()
    resolution_date = data.get('resolution_date', datetime.now().strftime('%Y-%m-%d')).strip()
    before_image_url = data.get('before_image_url', '').strip()
    after_image_url = data.get('after_image_url', '').strip()
    evidence_document = data.get('evidence_document', '').strip()

    if not resolution_notes:
        return jsonify({"status": "error", "message": "resolution_notes are required to resolve a complaint"}), 400

    try:
        conn = get_db_connection()
        conn.execute(
            """UPDATE complaints SET
               resolution_notes=?, resolution_date=?,
               before_image_url=?, after_image_url=?, evidence_document=?,
               lifecycle_status='Resolved', status='Resolved'
               WHERE complaint_id=?""",
            (resolution_notes, resolution_date, before_image_url, after_image_url, evidence_document, cid)
        )
        comp = conn.execute("SELECT user_id, issue_type FROM complaints WHERE complaint_id=?", (cid,)).fetchone()
        if comp:
            conn.execute(
                "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
                (comp['user_id'], "Your Complaint Has Been Resolved! ✅",
                 f"Great news! Your complaint {format_ref(cid)} ({comp['issue_type']}) has been resolved on {resolution_date}. Please share your feedback.")
            )
        conn.execute(
            "INSERT INTO complaint_timeline (complaint_id, stage, note, actor) VALUES (?, 'Resolved', ?, 'admin')",
            (cid, f"Resolved on {resolution_date}. {resolution_notes}")
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── v3.0: ARCHIVE ────────────────────────────────────────────────────────────

@app.route('/api/complaints/<int:cid>/archive', methods=['PATCH'])
def archive_complaint(cid):
    try:
        conn = get_db_connection()
        conn.execute(
            "UPDATE complaints SET lifecycle_status='Archived', status='Resolved' WHERE complaint_id=?",
            (cid,)
        )
        conn.execute(
            "INSERT INTO complaint_timeline (complaint_id, stage, note, actor) VALUES (?, 'Archived', 'Complaint archived after resolution.', 'admin')",
            (cid,)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── v3.0: SUCCESS STORY ─────────────────────────────────────────────────────

@app.route('/api/complaints/<int:cid>/success-story', methods=['PATCH'])
def mark_success_story(cid):
    data = request.json or {}
    title = data.get('title', '').strip()
    impact = data.get('impact', '').strip()
    try:
        conn = get_db_connection()
        conn.execute(
            "UPDATE complaints SET is_success_story=1, success_story_title=?, success_story_impact=? WHERE complaint_id=?",
            (title, impact, cid)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/success-stories', methods=['GET'])
def get_success_stories():
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT c.*, u.name as citizen_name
           FROM complaints c
           JOIN users u ON c.user_id = u.user_id
           WHERE c.is_success_story = 1
           ORDER BY c.resolution_date DESC"""
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        r = dict(row)
        r['reference'] = format_ref(r['complaint_id'])
        result.append(r)
    return jsonify(result)


# ─── v3.0: COMPLAINT TIMELINE ────────────────────────────────────────────────

@app.route('/api/complaints/<int:cid>/timeline', methods=['GET'])
def get_complaint_timeline(cid):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM complaint_timeline WHERE complaint_id = ? ORDER BY timestamp ASC", (cid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─── v3.0: FEEDBACK / SATISFACTION ───────────────────────────────────────────

@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    data = request.json or {}
    complaint_id = data.get('complaint_id')
    user_id = data.get('user_id')
    rating = data.get('rating')
    comment = data.get('comment', '').strip()

    if not all([complaint_id, user_id, rating]):
        return jsonify({"status": "error", "message": "complaint_id, user_id, and rating are required"}), 400
    if not (1 <= int(rating) <= 5):
        return jsonify({"status": "error", "message": "Rating must be between 1 and 5"}), 400

    rating = int(rating)
    label_map = {1: 'Very Dissatisfied', 2: 'Dissatisfied', 3: 'Neutral', 4: 'Satisfied', 5: 'Very Satisfied'}
    label = label_map[rating]

    try:
        conn = get_db_connection()
        # Check if complaint is resolved
        comp = conn.execute("SELECT lifecycle_status FROM complaints WHERE complaint_id=?", (complaint_id,)).fetchone()
        if not comp or comp['lifecycle_status'] not in ('Resolved', 'Archived'):
            conn.close()
            return jsonify({"status": "error", "message": "Feedback can only be submitted for Resolved complaints"}), 400

        conn.execute(
            "INSERT INTO feedback (complaint_id, user_id, rating, comment, satisfaction_label) VALUES (?,?,?,?,?)",
            (complaint_id, user_id, rating, comment, label)
        )
        conn.execute(
            "UPDATE complaints SET satisfaction_score=?, feedback_submitted=1 WHERE complaint_id=?",
            (float(rating), complaint_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "label": label})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/feedback/complaint/<int:cid>', methods=['GET'])
def get_complaint_feedback(cid):
    conn = get_db_connection()
    fb = conn.execute("SELECT * FROM feedback WHERE complaint_id = ? ORDER BY submitted_at DESC", (cid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in fb])


@app.route('/api/analytics/satisfaction', methods=['GET'])
def get_satisfaction_analytics():
    conn = get_db_connection()
    rows = conn.execute("SELECT rating, satisfaction_label FROM feedback").fetchall()
    conn.close()
    if not rows:
        return jsonify({"avg_rating": 0, "total_feedback": 0, "distribution": {}, "label_counts": {}})

    ratings = [r['rating'] for r in rows]
    avg = round(sum(ratings) / len(ratings), 2)
    dist = defaultdict(int)
    label_counts = defaultdict(int)
    for r in rows:
        dist[str(r['rating'])] += 1
        label_counts[r['satisfaction_label']] += 1

    return jsonify({
        "avg_rating": avg,
        "total_feedback": len(ratings),
        "distribution": dict(dist),
        "label_counts": dict(label_counts)
    })


# ─── v3.0: RESOLUTION CENTER — ADMIN OVERVIEW ────────────────────────────────

@app.route('/api/resolution/overview', methods=['GET'])
def resolution_overview():
    conn = get_db_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM complaints", conn)
    except Exception:
        conn.close()
        return jsonify({"error": "Could not read complaints"}), 500

    total = len(df)
    if total == 0:
        conn.close()
        return jsonify({
            "total": 0, "resolved": 0, "in_progress": 0, "pending": 0,
            "awaiting_evidence": 0, "overdue": 0,
            "avg_satisfaction": 0, "total_feedback": 0,
            "by_department": {}, "by_priority": {}
        })

    resolved = int(df[df['lifecycle_status'] == 'Resolved'].shape[0])
    in_progress = int(df[df['lifecycle_status'] == 'In Progress'].shape[0])
    pending = int(df[df['lifecycle_status'].isin(['Submitted', 'Verified'])].shape[0])

    # Complaints in progress but missing evidence (for "Awaiting Evidence" KPI)
    awaiting = int(df[
        (df['lifecycle_status'] == 'In Progress') &
        (df.get('action_plan', pd.Series([''] * len(df))).fillna('') != '') &
        (df.get('after_image_url', pd.Series([''] * len(df))).fillna('') == '')
    ].shape[0]) if 'action_plan' in df.columns else 0

    # Overdue = In Progress with deadline passed
    overdue = 0
    if 'action_deadline' in df.columns:
        today = datetime.now().date()
        ip_df = df[df['lifecycle_status'] == 'In Progress']
        for _, row in ip_df.iterrows():
            dl = row.get('action_deadline', '')
            if dl:
                try:
                    if datetime.strptime(str(dl), '%Y-%m-%d').date() < today:
                        overdue += 1
                except:
                    pass

    # Feedback stats
    fb_rows = conn.execute("SELECT AVG(rating) as avg, COUNT(*) as cnt FROM feedback").fetchone()
    avg_sat = round(fb_rows['avg'] or 0, 2)
    total_fb = fb_rows['cnt'] or 0

    # By department
    by_dept = {}
    if 'department' in df.columns:
        by_dept = df[df['department'] != '']['department'].value_counts().to_dict()

    # By action priority
    by_prio = {}
    if 'action_priority' in df.columns:
        by_prio = df[df['action_priority'] != '']['action_priority'].value_counts().to_dict()

    conn.close()
    return jsonify({
        "total": total,
        "resolved": resolved,
        "in_progress": in_progress,
        "pending": pending,
        "awaiting_evidence": awaiting,
        "overdue": overdue,
        "avg_satisfaction": avg_sat,
        "total_feedback": total_fb,
        "by_department": by_dept,
        "by_priority": by_prio
    })


# ─── CONTACT ─────────────────────────────────────────────────────────────────

@app.route('/api/contact', methods=['POST'])
def submit_contact():
    data = request.json
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    subject = data.get('subject', '').strip()
    message = data.get('message', '').strip()

    if not all([name, email, subject, message]):
        return jsonify({"status": "error", "message": "All fields are required"}), 400

    try:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO contact_messages (name, email, subject, message) VALUES (?, ?, ?, ?)",
            (name, email, subject, message)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Your message has been received. We'll respond within 24 hours."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/messages', methods=['GET'])
def get_contact_messages():
    conn = get_db_connection()
    messages = conn.execute(
        "SELECT * FROM contact_messages ORDER BY timestamp DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in messages])


# ─── NOTIFICATIONS ────────────────────────────────────────────────────────────

@app.route('/api/notifications/user/<int:user_id>', methods=['GET'])
def get_notifications(user_id):
    conn = get_db_connection()
    notifications = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in notifications])


@app.route('/api/notifications/read', methods=['POST'])
def mark_notifications_read():
    data = request.json
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400
    conn = get_db_connection()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})


# ─── ANALYTICS ───────────────────────────────────────────────────────────────

@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM complaints", conn)
    conn.close()

    if df.empty:
        return jsonify({
            "total": 0, "by_type": {}, "by_location": {}, "health_data": {},
            "pending": 0, "resolved": 0, "in_progress": 0, "high_severity": 0,
            "resolution_rate": 0, "avg_health_score": 0, "efficiency_score": 0,
            "active_high_risk_wards": 0, "pending_critical": 0,
            "priority_actions": [], "by_status": {"Pending": 0, "In Progress": 0, "Resolved": 0},
            "trends": {},
            "verified_count": 0, "escalated_count": 0, "archived_count": 0
        })

    total = len(df)
    by_type = df['issue_type'].value_counts().to_dict()
    by_location = df['location'].value_counts().to_dict()

    locations = df['location'].unique()
    health_data = {}
    for loc in locations:
        loc_complaints = df[df['location'] == loc].to_dict('records')
        score, risk = calculate_health_score(loc_complaints)
        issue_dist = df[df['location'] == loc]['issue_type'].value_counts().to_dict()
        recs = get_recommendation({"total_complaints": len(loc_complaints), "issue_distribution": issue_dist})
        health_data[loc] = {"score": score, "risk": risk, "total": len(loc_complaints), "recommendations": recs}

    pending = int(df[df['status'] == 'Pending'].shape[0])
    resolved = int(df[df['status'] == 'Resolved'].shape[0])
    in_progress = int(df[df['status'] == 'In Progress'].shape[0])
    high_severity = int(df[df['severity'] == 'High'].shape[0])
    resolution_rate = round((resolved / total * 100), 1) if total > 0 else 0
    avg_health_score = round(sum(v['score'] for v in health_data.values()) / len(health_data)) if health_data else 0
    efficiency_score = round((resolved * 100) / max(total, 1) * (1 + (in_progress * 0.5) / max(total, 1)), 1)
    active_high_risk_wards = sum(1 for v in health_data.values() if v['risk'] == 'Critical')
    pending_critical = int(df[(df['status'] == 'Pending') & (df['severity'] == 'High')].shape[0])

    priority_df = df[(df['status'] == 'Pending') & (df['severity'] == 'High')].head(5)
    priority_actions = priority_df[['complaint_id', 'location', 'issue_type', 'description', 'timestamp', 'severity']].to_dict('records')
    by_status = {'Pending': pending, 'In Progress': in_progress, 'Resolved': resolved}

    trends = {}
    today = datetime.now().date()
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        trends[day.strftime('%Y-%m-%d')] = 0

    if 'timestamp' in df.columns:
        df['date'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.date
        seven_days_ago = today - timedelta(days=6)
        recent = df[df['date'] >= seven_days_ago]
        day_counts = recent['date'].value_counts().to_dict()
        for d, count in day_counts.items():
            key = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)
            if key in trends:
                trends[key] = int(count)

    # v2.0: lifecycle counts
    verified_count = 0
    escalated_count = 0
    archived_count = 0
    if 'lifecycle_status' in df.columns:
        verified_count = int(df[df['lifecycle_status'] == 'Verified'].shape[0])
        escalated_count = int(df[df['lifecycle_status'] == 'Escalated'].shape[0])
        archived_count = int(df[df['lifecycle_status'] == 'Archived'].shape[0])

    return jsonify({
        "total": total, "by_type": by_type, "by_location": by_location, "health_data": health_data,
        "pending": pending, "resolved": resolved, "in_progress": in_progress, "high_severity": high_severity,
        "resolution_rate": resolution_rate, "avg_health_score": avg_health_score,
        "efficiency_score": efficiency_score, "active_high_risk_wards": active_high_risk_wards,
        "pending_critical": pending_critical, "priority_actions": priority_actions,
        "by_status": by_status, "trends": trends,
        "verified_count": verified_count, "escalated_count": escalated_count, "archived_count": archived_count
    })


# ─── v2.0: COMPLAINT AGING ANALYSIS ─────────────────────────────────────────

@app.route('/api/analytics/aging', methods=['GET'])
def get_complaint_aging():
    conn = get_db_connection()
    df = pd.read_sql_query(
        "SELECT complaint_id, timestamp, status, severity, location, issue_type FROM complaints", conn
    )
    conn.close()

    if df.empty:
        return jsonify({"bucket_0_7": [], "bucket_8_15": [], "bucket_15_plus": [], "counts": {"0_7": 0, "8_15": 0, "15_plus": 0}})

    now = datetime.now()
    df['ts'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df['age_days'] = (now - df['ts']).dt.days

    # Only unresolved
    unresolved = df[df['status'] != 'Resolved']

    b0 = unresolved[unresolved['age_days'] <= 7]
    b1 = unresolved[(unresolved['age_days'] >= 8) & (unresolved['age_days'] <= 15)]
    b2 = unresolved[unresolved['age_days'] > 15]

    def to_list(frame):
        return frame[['complaint_id', 'location', 'issue_type', 'severity', 'age_days']].to_dict('records')

    return jsonify({
        "bucket_0_7":    to_list(b0),
        "bucket_8_15":   to_list(b1),
        "bucket_15_plus": to_list(b2),
        "counts": {
            "0_7": len(b0),
            "8_15": len(b1),
            "15_plus": len(b2)
        }
    })


# ─── v2.0: REPORT HISTORY ─────────────────────────────────────────────────────

@app.route('/api/reports/history', methods=['GET'])
def get_report_history():
    conn = get_db_connection()
    reports = conn.execute(
        "SELECT * FROM reports ORDER BY generation_date DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in reports])


@app.route('/api/reports/generate', methods=['POST'])
def generate_report_endpoint():
    data = request.json or {}
    report_type = data.get('report_type', 'Custom')
    filters = data.get('filters', {})

    try:
        if report_type == 'Weekly':
            file_path = generate_weekly_report(filters)
        elif report_type == 'Monthly':
            file_path = generate_monthly_report(filters)
        else:
            file_path = generate_pdf_report()

        report_id = gen_report_id(report_type)
        now = datetime.now()

        if report_type == 'Weekly':
            period = f"Week of {now.strftime('%d %b %Y')}"
        elif report_type == 'Monthly':
            period = now.strftime('%B %Y')
        else:
            period = f"Custom — {now.strftime('%d %b %Y')}"

        conn = get_db_connection()
        conn.execute(
            '''INSERT INTO reports
               (report_id, report_type, period_covered, generated_by, generation_date,
                status, downloaded_count, authority_submission_status,
                complaint_ids, filters_used, file_path)
               VALUES (?, ?, ?, ?, ?, 'Generated', 1, 'Pending', '', ?, ?)''',
            (report_id, report_type, period, 'admin', now.isoformat(),
             str(filters), file_path)
        )
        conn.commit()
        conn.close()

        return send_file(file_path, as_attachment=True,
                         download_name=f"PTP_{report_type}_Report_{now.strftime('%Y%m%d')}.pdf")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/reports/<report_id>/status', methods=['PATCH'])
def update_report_status(report_id):
    data = request.json or {}
    status = data.get('status')
    authority_status = data.get('authority_submission_status')

    try:
        conn = get_db_connection()
        if status:
            conn.execute("UPDATE reports SET status = ? WHERE report_id = ?", (status, report_id))
        if authority_status:
            conn.execute("UPDATE reports SET authority_submission_status = ? WHERE report_id = ?", (authority_status, report_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/reports/<report_id>/download', methods=['GET', 'PATCH'])
def download_or_increment_report(report_id):
    try:
        conn = get_db_connection()
        report = conn.execute("SELECT file_path, report_type FROM reports WHERE report_id = ?", (report_id,)).fetchone()
        if not report:
            conn.close()
            return jsonify({"status": "error", "message": "Report not found"}), 404
        
        conn.execute("UPDATE reports SET downloaded_count = downloaded_count + 1 WHERE report_id = ?", (report_id,))
        conn.commit()
        conn.close()

        if request.method == 'GET':
            file_path = report['file_path']
            if not file_path or not os.path.exists(file_path):
                # Fallback: check if the legacy file path exists
                legacy_path = os.path.join(os.path.dirname(__file__), "ping_the_panchayat_report.pdf")
                if os.path.exists(legacy_path):
                    file_path = legacy_path
                else:
                    return jsonify({"status": "error", "message": "Original PDF file not available on disk"}), 404
            return send_file(file_path, as_attachment=True, download_name=f"{report_id}.pdf")
        
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── LEGACY REPORT (kept for compatibility) ───────────────────────────────────

@app.route('/api/report', methods=['GET'])
def get_report():
    report_path = generate_pdf_report()
    return send_file(report_path, as_attachment=True)


# ─── FRONTEND STATIC ROUTING ──────────────────────────────────────────────────

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/<path:path>')
def serve_static(path):
    if path.startswith('api/'):
        return jsonify({"status": "error", "message": "API endpoint not found"}), 404
    target = os.path.join(app.static_folder, path)
    if os.path.exists(target) and os.path.isfile(target):
        return app.send_static_file(path)
    if os.path.isdir(target) and os.path.exists(os.path.join(target, 'index.html')):
        return app.send_static_file(os.path.join(path, 'index.html'))
    return app.send_static_file('index.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

