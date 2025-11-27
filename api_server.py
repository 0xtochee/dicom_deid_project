# api_server.py
from flask import (
    Flask, request, jsonify, render_template, send_from_directory,
    redirect, url_for, session, flash
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os, traceback, pymysql

# Your processing tools (from the versions we built together)
from dicom_deidentification import SimpleDicomDeidentifier
from text_detection import TextPassOrInpaint


# Flask setup

app = Flask(__name__, static_url_path='/static', static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change_me_in_prod')

UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
app.config.update(UPLOAD_FOLDER=UPLOAD_FOLDER, PROCESSED_FOLDER=PROCESSED_FOLDER, MAX_CONTENT_LENGTH=512 * 1024 * 1024)


# DB setup (MySQL via PyMySQL)

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "flask_user"),
    "password": os.environ.get("DB_PASSWORD", "3825968#"),
    "database": os.environ.get("DB_NAME", "dicom_users"),
    "autocommit": False,
    "cursorclass": pymysql.cursors.Cursor,
}

db = pymysql.connect(**DB_CONFIG)

def init_db():
    with db.cursor() as cur:
        # Users table (hashed password)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Activity log
        cur.execute("""
            CREATE TABLE IF NOT EXISTS file_activity_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255),
                filename VARCHAR(255),
                action ENUM('upload','view','download') NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    db.commit()

init_db()


# Tools

deidentifier = SimpleDicomDeidentifier()  # metadata-only, pixel-safe
# Enable inpainting with conservative banner strips (adjust if needed)
text_step = TextPassOrInpaint(enable_inpainting=True)


# Helpers

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            flash('Login required')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped

def log_activity(username: str | None, filename: str, action: str):
    if not username or not filename:
        return
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO file_activity_log (username, filename, action) VALUES (%s, %s, %s)",
                (username, filename, action),
            )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[log_activity] Failed: {e}")


# Auth routes

@app.before_request
def make_session_permanent():
    session.permanent = True

@app.route('/')
def home():
    # If logged in, go straight to dashboard
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        confirm  = request.form.get('confirm') or ''

        if not username or not password:
            flash('Username and password are required.')
            return redirect(url_for('signup'))
        if password != confirm:
            flash('Passwords do not match!')
            return redirect(url_for('signup'))
        if len(username) > 255:
            flash('Username too long.')
            return redirect(url_for('signup'))

        hashed = generate_password_hash(password)
        try:
            with db.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username=%s", (username,))
                if cur.fetchone():
                    flash('Username already exists!')
                    return redirect(url_for('signup'))
                cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed))
            db.commit()
            flash('Signup successful. Please login.')
            return redirect(url_for('login'))
        except Exception as e:
            db.rollback()
            flash(f'Signup error: {e}')
            return redirect(url_for('signup'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        try:
            with db.cursor() as cur:
                cur.execute("SELECT id, username, password FROM users WHERE username=%s", (username,))
                user = cur.fetchone()
            if user and check_password_hash(user[2], password):
                session['user'] = user[1]
                return redirect(url_for('dashboard'))
            flash('Invalid credentials.')
        except Exception as e:
            flash(f'Login failed: {e}')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('login'))


# App routes

@app.route('/index.html')
@login_required
def dashboard():
    return render_template('index.html')

@app.route('/upload_dicom', methods=['POST'])
def upload_dicom():
    # JSON API → return 401 JSON if not logged in
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    file = request.files.get('dicom_file')
    if not file or not file.filename:
        return jsonify({'error': 'No file uploaded'}), 400

    filename = secure_filename(file.filename)
    if not filename.lower().endswith('.dcm'):
        return jsonify({'error': 'Only .dcm files are supported'}), 400

    upload_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(upload_path)

    try:
        # Step 1: metadata de-id (pixel data untouched)
        deid_name = os.path.splitext(filename)[0] + "_deid.dcm"
        deid_path = os.path.join(app.config['PROCESSED_FOLDER'], deid_name)
        deidentifier(upload_path, deid_path)

        if not os.path.exists(deid_path):
            raise FileNotFoundError(f"Deidentified file not found: {deid_name}")

        # Step 2: burned-in text removal (inpainting)
        final_name = os.path.splitext(deid_name)[0] + "_final.dcm"
        final_path = os.path.join(app.config['PROCESSED_FOLDER'], final_name)
        text_step(deid_path, final_path)

        if not os.path.exists(final_path):
            raise FileNotFoundError(f"Final file not found: {final_name}")

        log_activity(session.get('user'), final_name, 'upload')

        processed_url = url_for('serve_processed', filename=final_name, _external=True)
        download_url  = url_for('download_file', filename=final_name, _external=True)

        return jsonify({
            'message': 'Processed',
            'processed_url': processed_url,
            'download_url': download_url
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'Processing failed: {e}'}), 500

@app.route('/processed/<path:filename>')
def serve_processed(filename):
    try:
        resp = send_from_directory(PROCESSED_FOLDER, filename)
        # Headers for Cornerstone & cache-busting
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        resp.headers['Content-Type'] = 'application/dicom'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404

@app.route('/download/<path:filename>')
def download_file(filename):
    log_activity(session.get('user'), filename, 'download')
    return send_from_directory(PROCESSED_FOLDER, filename, as_attachment=True)

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# Optional debug endpoints
@app.route('/debug/processed')
def debug_processed():
    try:
        files = os.listdir(PROCESSED_FOLDER)
        detail = []
        for f in files:
            p = os.path.join(PROCESSED_FOLDER, f)
            if os.path.isfile(p):
                detail.append({"name": f, "size": os.path.getsize(p), "exists": True})
        return jsonify({"processed_folder": PROCESSED_FOLDER, "total": len(detail), "files": detail})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(413)
def too_large(_):
    return jsonify({'error': 'File too large'}), 413


if __name__ == '__main__':
    app.run(debug=True, port=8000)
