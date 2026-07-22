import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Users Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        contact_info TEXT NOT NULL
    )
    ''')

    # Admins Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    ''')

    # Complaints Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS complaints (
        complaint_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        issue_type TEXT NOT NULL,
        location TEXT NOT NULL,
        description TEXT NOT NULL,
        severity TEXT NOT NULL,
        status TEXT DEFAULT 'Pending',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        image_url TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    ''')

    # Analytics Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS analytics (
        area_name TEXT PRIMARY KEY,
        total_complaints INTEGER DEFAULT 0,
        health_score INTEGER DEFAULT 100,
        risk_level TEXT DEFAULT 'Low'
    )
    ''')

    # Reports Table (v2.0)
    try:
        cursor.execute("SELECT period_covered FROM reports LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("DROP TABLE IF EXISTS reports")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        report_id TEXT PRIMARY KEY,
        report_type TEXT NOT NULL,
        period_covered TEXT NOT NULL,
        generated_by TEXT DEFAULT 'admin',
        generation_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'Generated',
        downloaded_count INTEGER DEFAULT 0,
        authority_submission_status TEXT DEFAULT 'Pending',
        complaint_ids TEXT DEFAULT '',
        filters_used TEXT DEFAULT '',
        file_path TEXT DEFAULT ''
    )
    ''')

    # Contact Messages Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS contact_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Notifications Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notifications (
        notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER DEFAULT 0,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    ''')

    # ── v3.0: Feedback Table ──────────────────────────────────────────────────
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS feedback (
        feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        rating INTEGER NOT NULL,
        comment TEXT DEFAULT '',
        satisfaction_label TEXT DEFAULT '',
        submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id),
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    ''')

    # ── v3.0: Complaint Timeline Table ───────────────────────────────────────
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS complaint_timeline (
        timeline_id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER NOT NULL,
        stage TEXT NOT NULL,
        note TEXT DEFAULT '',
        actor TEXT DEFAULT 'admin',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id)
    )
    ''')

    # ── Migrations (safe ALTER TABLE for existing databases) ──────────────────
    migrations = [
        "ALTER TABLE complaints ADD COLUMN admin_notes TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN assigned_team TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN security_question TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN security_answer TEXT DEFAULT ''",
        # v2.0 lifecycle & reporting columns
        "ALTER TABLE complaints ADD COLUMN lifecycle_status TEXT DEFAULT 'Submitted'",
        "ALTER TABLE complaints ADD COLUMN report_id TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN report_status TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN escalation_status TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN authority_status TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN last_reported_date TEXT DEFAULT ''",
        # v3.0 resolution & action plan columns
        "ALTER TABLE complaints ADD COLUMN department TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN action_plan TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN action_deadline TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN action_priority TEXT DEFAULT 'Normal'",
        "ALTER TABLE complaints ADD COLUMN resolution_notes TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN resolution_date TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN before_image_url TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN after_image_url TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN evidence_document TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN satisfaction_score REAL DEFAULT 0",
        "ALTER TABLE complaints ADD COLUMN feedback_submitted INTEGER DEFAULT 0",
        "ALTER TABLE complaints ADD COLUMN is_success_story INTEGER DEFAULT 0",
        "ALTER TABLE complaints ADD COLUMN success_story_title TEXT DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN success_story_impact TEXT DEFAULT ''",
    ]
    for m in migrations:
        try:
            cursor.execute(m)
        except Exception:
            pass  # Column already exists — safe to skip

    # ── Default admin ─────────────────────────────────────────────────────────
    cursor.execute("INSERT OR IGNORE INTO admins (username, password) VALUES ('admin', 'admin123')")

    # ── Seed demo report history (only if reports table is empty) ─────────────
    cursor.execute("SELECT COUNT(*) FROM reports")
    if cursor.fetchone()[0] == 0:
        seed_reports = [
            ('RPT-WEEK-001', 'Weekly',  'Week 1 — June 2026',      'admin', '2026-06-02 09:00:00', 'Sent to Authority', 3, 'Submitted', '', '', ''),
            ('RPT-WEEK-002', 'Weekly',  'Week 2 — June 2026',      'admin', '2026-06-09 09:00:00', 'Reviewed',          2, 'Reviewed',  '', '', ''),
            ('RPT-MON-MAY',  'Monthly', 'May 2026',                 'admin', '2026-06-01 08:00:00', 'Closed',            5, 'Reviewed',  '', '', ''),
            ('RPT-MON-JUN',  'Monthly', 'June 2026 (Ongoing)',      'admin', '2026-06-10 08:00:00', 'Generated',         1, 'Pending',   '', '', ''),
            ('RPT-CUST-001', 'Custom',  'High Severity — Q2 2026', 'admin', '2026-05-28 14:30:00', 'Sent to Authority', 2, 'Submitted', '', '', ''),
        ]
        cursor.executemany(
            '''INSERT OR IGNORE INTO reports
               (report_id, report_type, period_covered, generated_by, generation_date,
                status, downloaded_count, authority_submission_status,
                complaint_ids, filters_used, file_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            seed_reports
        )

    conn.commit()
    conn.close()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == '__main__':
    init_db()
    print("Database initialized.")
