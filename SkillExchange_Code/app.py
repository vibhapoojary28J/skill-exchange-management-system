from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from utils.db import get_connection
from config import UPLOAD_FOLDER

app = Flask(__name__)
app.secret_key = 'replace-this-with-secure-key'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# ---------------- LOGIN ----------------
@app.route('/')
def login_page():
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        bio = request.form.get('bio')

        conn = get_connection(); cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close(); conn.close()
            return render_template('register.html', error='Email already registered')

        cur.execute("INSERT INTO users (name, email, password, bio) VALUES (%s,%s,%s,%s)", (name, email, password, bio))
        conn.commit(); cur.close(); conn.close()
        return redirect(url_for('login_page'))

    return render_template('register.html')


@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, name, email FROM users WHERE email=%s AND password=%s", (email, password))
    user = cur.fetchone()
    cur.close(); conn.close()

    if user:
        session['user_id'] = user[0]
        session['user_name'] = user[1]
        session['user_email'] = user[2]
        return redirect(url_for('dashboard'))

    return render_template('login.html', error='Invalid credentials')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))


def require_login():
    if 'user_id' not in session:
        return False
    return True


def ensure_video_category_column():
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS category VARCHAR(100) DEFAULT 'General';")
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close(); conn.close()


def ensure_skill_metadata_columns():
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE skills ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'Non-Tech';")
        cur.execute("ALTER TABLE skills ADD COLUMN IF NOT EXISTS usage_count INT DEFAULT 1;")
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close(); conn.close()


def ensure_messages_attachment_column():
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachment TEXT;")
        cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE;")
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close(); conn.close()


@app.context_processor
def inject_user_activity():
    user_id = session.get('user_id')
    if not user_id:
        return {
            'unread_notifications': 0,
            'pending_requests_count': 0,
            'connections_count': 0
        }

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM notifications WHERE user_id=%s AND is_read=false", (user_id,))
        unread_notifications = cur.fetchone()[0] if cur.rowcount >= 0 else 0

        cur.execute("SELECT COUNT(*) FROM connections WHERE receiver_id=%s AND status='pending'", (user_id,))
        pending_requests = cur.fetchone()[0] if cur.rowcount >= 0 else 0

        cur.execute("SELECT COUNT(*) FROM connections WHERE (sender_id=%s OR receiver_id=%s) AND status='accepted'", (user_id, user_id))
        connections = cur.fetchone()[0] if cur.rowcount >= 0 else 0
    except Exception:
        unread_notifications = 0
        pending_requests = 0
        connections = 0
    finally:
        cur.close(); conn.close()

    return {
        'unread_notifications': unread_notifications,
        'pending_requests_count': pending_requests,
        'connections_count': connections
    }


@app.route('/sidebar_info')
def sidebar_info():
    if not require_login():
        return jsonify({'error': 'not_logged_in'}), 401

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()
    data = {'pending_requests': 0, 'unread_notifications': 0, 'recent_activities': []}
    try:
        cur.execute("SELECT COUNT(*) FROM connections WHERE receiver_id=%s AND status='pending'", (user_id,))
        data['pending_requests'] = cur.fetchone()[0] if cur.rowcount else 0

        cur.execute("SELECT COUNT(*) FROM notifications WHERE user_id=%s AND is_read=false", (user_id,))
        data['unread_notifications'] = cur.fetchone()[0] if cur.rowcount else 0

        cur.execute("SELECT 'connect' AS type, u.name, c.created_at FROM connections c JOIN users u ON u.user_id=c.sender_id WHERE c.receiver_id=%s ORDER BY c.created_at DESC LIMIT 3", (user_id,))
        for r in cur.fetchall():
            data['recent_activities'].append({'type': 'connect', 'name': r[1], 'time': r[2].strftime('%Y-%m-%d %H:%M')})

        cur.execute("SELECT 'notification' AS type, message, created_at FROM notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT 3", (user_id,))
        for r in cur.fetchall():
            data['recent_activities'].append({'type': 'notification', 'message': r[1], 'time': r[2].strftime('%Y-%m-%d %H:%M')})

        data['recent_activities'] = sorted(data['recent_activities'], key=lambda x: x['time'], reverse=True)[:4]
    except Exception:
        pass
    finally:
        conn.close()

    return jsonify(data)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------- DASHBOARD ----------------
@app.route('/dashboard')
def dashboard():
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']

    ensure_video_category_column()
    conn = get_connection()
    cur = conn.cursor()

    def safe_fetch(sql, params=()):
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        except Exception:
            conn.rollback()
            return []

    def safe_one(sql, params=()):
        try:
            cur.execute(sql, params)
            return cur.fetchone()
        except Exception:
            conn.rollback()
            return None

    user_videos = safe_fetch("SELECT user_id, title, description, video_url, category FROM videos WHERE user_id=%s ORDER BY upload_date DESC", (user_id,))

    sort_by = request.args.get('sort_by', 'new')
    if sort_by == 'likes':
        order_clause = 'COALESCE((SELECT COUNT(*) FROM likes l WHERE l.video_id = v.video_id), 0) DESC'
    elif sort_by == 'rating':
        order_clause = 'COALESCE((SELECT AVG(rating) FROM ratings r WHERE r.video_id = v.video_id), 0) DESC'
    else:
        order_clause = 'v.upload_date DESC'

    cur.execute(f"SELECT v.video_id, v.title, v.description, v.video_url, COALESCE(v.category,'General'), u.name, u.user_id FROM videos v JOIN users u ON v.user_id = u.user_id ORDER BY {order_clause} LIMIT 8")
    rows = cur.fetchall()

    videos = []
    for row in rows:
        video_id, title, description, video_url, category, creator_name, creator_id = row

        likes_row = safe_one("SELECT COUNT(*) FROM likes WHERE video_id=%s", (video_id,))
        likes = likes_row[0] if likes_row else 0

        avg_row = safe_one("SELECT AVG(rating) FROM ratings WHERE video_id=%s", (video_id,))
        avg_rating = avg_row[0] or 0 if avg_row else 0

        liked_row = safe_one("SELECT COUNT(*) FROM likes WHERE video_id=%s AND user_id=%s", (video_id, user_id))
        liked_by_current = (liked_row[0] > 0) if liked_row else False

        try:
            cur.execute("SELECT c.comment_text, u.name FROM comments c JOIN users u ON c.user_id = u.user_id WHERE c.video_id=%s ORDER BY c.comment_id DESC LIMIT 4", (video_id,))
            comment_rows = cur.fetchall()
            comments = [{'author': c[1], 'text': c[0]} for c in comment_rows]
        except Exception:
            comments = []

        videos.append({
            'video_id': video_id,
            'title': title,
            'description': description,
            'video_url': video_url,
            'category': category or 'General',
            'creator_name': creator_name,
            'creator_id': creator_id,
            'likes': likes,
            'average_rating': round(avg_rating, 1),
            'liked_by_current': liked_by_current,
            'comments': comments,
        })

    cur.execute("SELECT COUNT(*) FROM connections WHERE status='accepted'")
    connections = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM videos")
    video_count = cur.fetchone()[0]

    cur.execute("SELECT AVG(rating) FROM ratings")
    avg_rating = cur.fetchone()[0] or 0

    analytics_rows = safe_fetch("SELECT date, videos_uploaded, connections_made, profile_views FROM analytics WHERE user_id=%s ORDER BY date DESC LIMIT 10", (user_id,))
    analytics_rows = list(reversed(analytics_rows))
    chart_dates = [r[0].strftime('%Y-%m-%d') for r in analytics_rows]
    chart_videos = [r[1] for r in analytics_rows]
    chart_connections = [r[2] for r in analytics_rows]
    chart_profile = [r[3] for r in analytics_rows]

    # recent activity feed: latest connections/comments/uploads
    cur.execute("SELECT u.name, c.created_at FROM connections c JOIN users u ON u.user_id = c.sender_id WHERE c.receiver_id=%s ORDER BY c.created_at DESC LIMIT 4", (user_id,))
    recent_connections = [{'name': r[0], 'when': r[1]} for r in cur.fetchall()]

    cur.execute("SELECT u.name, cm.comment_text, cm.created_at FROM comments cm JOIN users u ON u.user_id=cm.user_id WHERE cm.video_id IN (SELECT video_id FROM videos WHERE user_id=%s) ORDER BY cm.created_at DESC LIMIT 4", (user_id,))
    recent_comments = [{'name': r[0], 'text': r[1], 'when': r[2]} for r in cur.fetchall()]

    cur.execute("SELECT title, upload_date FROM videos WHERE user_id=%s ORDER BY upload_date DESC LIMIT 4", (user_id,))
    recent_uploads = [{'title': r[0], 'when': r[1]} for r in cur.fetchall()]

    cur.close(); conn.close()

    return render_template('dashboard.html', videos=videos, connections=connections, video_count=video_count,
                           avg_rating=round(avg_rating, 2), user_video_count=len(user_videos),
                           recent_connections=recent_connections, recent_comments=recent_comments, recent_uploads=recent_uploads)



# ---------------- ANALYTICS PAGE ----------------
@app.route('/analytics')
def analytics():
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    ensure_skill_metadata_columns()
    conn = get_connection(); cur = conn.cursor()

    cur.execute("SELECT date, videos_uploaded, connections_made, profile_views FROM analytics WHERE user_id=%s ORDER BY date DESC LIMIT 14", (user_id,))
    analytics_rows = list(reversed(cur.fetchall()))

    cur.execute("SELECT COUNT(*) FROM videos WHERE user_id=%s", (user_id,))
    user_video_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM connections WHERE sender_id=%s OR receiver_id=%s", (user_id, user_id))
    user_conn_count = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(profile_views),0) FROM analytics WHERE user_id=%s", (user_id,))
    profile_views_total = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(*) FROM user_skills WHERE user_id=%s", (user_id,))
    skills_shared = cur.fetchone()[0] or 0

    cur.execute("SELECT s.skill_id, s.skill_name, COALESCE(s.category,'Non-Tech'), COALESCE(s.usage_count, 1) FROM skills s JOIN user_skills us ON s.skill_id=us.skill_id WHERE us.user_id=%s", (user_id,))
    user_skill_details = [{'skill_id': r[0], 'skill_name': r[1], 'category': r[2], 'count': r[3]} for r in cur.fetchall()]

    chart_dates = [r[0].strftime('%Y-%m-%d') for r in analytics_rows]
    chart_videos = [r[1] for r in analytics_rows]
    chart_connections = [r[2] for r in analytics_rows]
    chart_profile = [r[3] for r in analytics_rows]

    # Insights
    most_active_index = max(range(len(analytics_rows)), key=lambda i: (analytics_rows[i][1] + analytics_rows[i][2] + analytics_rows[i][3])) if analytics_rows else None
    most_active_day = analytics_rows[most_active_index][0].strftime('%Y-%m-%d') if most_active_index is not None else 'N/A'
    total_last = (analytics_rows[-1][1] + analytics_rows[-1][2] + analytics_rows[-1][3]) if len(analytics_rows) >= 1 else 0
    total_prev = (analytics_rows[-2][1] + analytics_rows[-2][2] + analytics_rows[-2][3]) if len(analytics_rows) >= 2 else 0
    growth_rate = round(((total_last - total_prev) / abs(total_prev) * 100) if total_prev else 0, 1)
    engagement_score = int((user_conn_count * 5 + user_video_count * 10 + profile_views_total * 0.2) / 3)

    cur.close(); conn.close()
    return render_template('analytics.html', user_video_count=user_video_count,
                           user_conn_count=user_conn_count,
                           profile_views_total=profile_views_total,
                           skills_shared=skills_shared,
                           chart_dates=chart_dates, chart_videos=chart_videos,
                           chart_connections=chart_connections, chart_profile=chart_profile,
                           user_skill_details=user_skill_details,
                           most_active_day=most_active_day,
                           growth_rate=growth_rate,
                           engagement_score=engagement_score)


# ---------------- VIDEO DELETE ----------------
@app.route('/delete_video/<int:video_id>', methods=['POST'])
def delete_video(video_id):
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT user_id, video_url FROM videos WHERE video_id=%s", (video_id,))
    video = cur.fetchone()

    if not video or video[0] != user_id:
        cur.close(); conn.close()
        return redirect(url_for('profile'))

    video_url = video[1] or ''
    # delete file if it is local static/upload content
    if video_url.startswith('/static/upload/') or 'static/upload/' in video_url:
        try:
            local_path = video_url.replace('/', os.sep)
            if local_path.startswith(os.sep):
                local_path = local_path.lstrip(os.sep)
            if os.path.exists(local_path):
                os.remove(local_path)
        except Exception:
            pass

    # clean comments/ratings explicitly (in case DB cascade is not configured)
    cur.execute("DELETE FROM comments WHERE video_id=%s", (video_id,))
    cur.execute("DELETE FROM ratings WHERE video_id=%s", (video_id,))
    cur.execute("DELETE FROM likes WHERE video_id=%s", (video_id,))

    cur.execute("DELETE FROM videos WHERE video_id=%s", (video_id,))
    conn.commit(); cur.close(); conn.close()

    flash('Video deleted successfully', 'success')
    return redirect(url_for('profile'))


# ---------------- VIDEO UPLOAD ----------------
@app.route('/upload', methods=['GET', 'POST'])
def upload_video():
    if not require_login():
        return redirect(url_for('login_page'))

    if request.method == 'POST':
        ensure_video_category_column()

        file = request.files.get('video')
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category', 'General')

        if not file or file.filename == '':
            return redirect(url_for('upload_video'))

        filename = secure_filename(file.filename)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        video_url = filepath.replace('\\', '/')

        conn = get_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO videos (user_id, title, description, video_url, category) VALUES (%s,%s,%s,%s,%s)",
                    (session['user_id'], title, description, video_url, category))
        conn.commit(); cur.close(); conn.close()

        return redirect(url_for('dashboard'))

    return render_template('upload.html')


# ---------------- LIKE ----------------
@app.route('/like/<int:video_id>', methods=['POST'])
def like_video(video_id):
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()

    # likes table uses like_id as primary key
    cur.execute("SELECT like_id FROM likes WHERE user_id=%s AND video_id=%s", (user_id, video_id))
    exists = cur.fetchone()
    liked = False
    if exists:
        cur.execute("DELETE FROM likes WHERE like_id=%s", (exists[0],))
        liked = False
    else:
        cur.execute("INSERT INTO likes (user_id, video_id) VALUES (%s,%s)", (user_id, video_id))
        liked = True

        # update uploader analytics for like event
        cur.execute("SELECT user_id FROM videos WHERE video_id=%s", (video_id,))
        owner = cur.fetchone()
        if owner:
            owner_id = owner[0]
            cur.execute("SELECT analytics_id FROM analytics WHERE user_id=%s AND date=CURRENT_DATE", (owner_id,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE analytics SET profile_views = profile_views + 1 WHERE analytics_id=%s", (row[0],))
            else:
                cur.execute("INSERT INTO analytics (user_id, date, profile_views) VALUES (%s, CURRENT_DATE, 1)", (owner_id,))

    cur.execute("SELECT COUNT(*) FROM likes WHERE video_id=%s", (video_id,))
    like_count = cur.fetchone()[0]

    conn.commit(); cur.close(); conn.close()

    response_data = {'liked': liked, 'likes': like_count}
    # Always return JSON for like button so UI stays on page without reload
    return jsonify(response_data)


# ---------------- COMMENT ----------------
@app.route('/comment/<int:video_id>', methods=['POST'])
def add_comment(video_id):
    if not require_login():
        return redirect(url_for('login_page'))

    content = request.form.get('comment', '').strip()
    if content:
        conn = get_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO comments (video_id, user_id, comment_text) VALUES (%s,%s,%s)",
                    (video_id, session['user_id'], content))
        conn.commit(); cur.close(); conn.close()

    return redirect(url_for('dashboard'))


# ---------------- PROFILE ----------------
def load_profile_data(profile_user_id):
    conn = get_connection(); cur = conn.cursor()

    cur.execute("SELECT user_id, name, email, bio, profile_pic FROM users WHERE user_id=%s", (profile_user_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return None

    user = {'user_id': row[0], 'name': row[1], 'email': row[2], 'bio': row[3], 'profile_pic': row[4]}

    # User videos
    cur.execute("SELECT COUNT(*) FROM videos WHERE user_id=%s", (profile_user_id,))
    video_count = cur.fetchone()[0]

    cur.execute("SELECT video_id, title, description FROM videos WHERE user_id=%s ORDER BY video_id DESC", (profile_user_id,))
    user_videos = [{'video_id': r[0], 'title': r[1], 'description': r[2]} for r in cur.fetchall()]

    ensure_skill_metadata_columns()
    # User skills
    cur.execute("SELECT s.skill_id, s.skill_name, COALESCE(s.category,'Non-Tech') AS category, COALESCE(s.usage_count,1) AS usage_count FROM skills s JOIN user_skills us ON s.skill_id=us.skill_id WHERE us.user_id=%s", (profile_user_id,))
    user_skills = [{'skill_id': r[0], 'skill_name': r[1], 'category': r[2], 'count': r[3]} for r in cur.fetchall()]

    # Whether relationship info is shown is less important for other profile viewers, but keep accepted connections for this account
    cur.execute("""
        SELECT u.user_id, u.name, u.profile_pic, c.status
        FROM users u
        JOIN connections c ON (
            (c.sender_id=%s AND c.receiver_id=u.user_id)
            OR
            (c.receiver_id=%s AND c.sender_id=u.user_id)
        )
        WHERE c.status='accepted'
        ORDER BY c.created_at DESC
    """, (profile_user_id, profile_user_id))
    connections = [{'user_id': r[0], 'name': r[1], 'profile_pic': r[2], 'status': r[3]} for r in cur.fetchall()]

    cur.close(); conn.close()
    return {
        'user': user,
        'video_count': video_count,
        'user_videos': user_videos,
        'user_skills': user_skills,
        'connections': connections
    }


@app.route('/profile')
def profile():
    if not require_login():
        return redirect(url_for('login_page'))

    profile_user_id = session['user_id']
    data = load_profile_data(profile_user_id)
    if not data:
        flash('Profile not found', 'error')
        return redirect(url_for('dashboard'))

    data['is_owner'] = True
    # suggested users for self profile
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT u.user_id, u.name, u.profile_pic
        FROM users u
        WHERE u.user_id != %s
          AND u.user_id NOT IN (
              SELECT receiver_id FROM connections WHERE sender_id = %s AND status = 'accepted'
              UNION
              SELECT sender_id FROM connections WHERE receiver_id = %s AND status = 'accepted'
          )
        ORDER BY u.name
        LIMIT 5
    """, (profile_user_id, profile_user_id, profile_user_id))
    suggested_users = [{'user_id': r[0], 'name': r[1], 'profile_pic': r[2]} for r in cur.fetchall()]
    conn.close()

    return render_template('profile.html', **data, suggested_users=suggested_users)


@app.route('/user/<int:profile_user_id>')
def view_user_profile(profile_user_id):
    if not require_login():
        return redirect(url_for('login_page'))

    data = load_profile_data(profile_user_id)
    if not data:
        flash('Profile not found', 'error')
        return redirect(url_for('dashboard'))

    data['is_owner'] = (session['user_id'] == profile_user_id)
    return render_template('profile.html', **data)


@app.route('/add_skill', methods=['POST'])
def add_skill():
    if not require_login():
        return jsonify({'success': False, 'message': 'Login required'}), 401

    ensure_skill_metadata_columns()
    user_id = session['user_id']
    skill_name = request.form.get('skill_name', '').strip()
    category = request.form.get('category', 'Non-Tech').strip() or 'Non-Tech'

    if not skill_name:
        return jsonify({'success': False, 'message': 'Skill name required'}), 400

    conn = get_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO skills (skill_name, category) VALUES (%s,%s) ON CONFLICT(skill_name) DO UPDATE SET category = EXCLUDED.category", (skill_name, category))
    cur.execute("SELECT skill_id FROM skills WHERE skill_name=%s", (skill_name,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({'success': False, 'message': 'Could not add skill'}), 500

    skill_id = row[0]
    cur.execute("SELECT 1 FROM user_skills WHERE user_id=%s AND skill_id=%s", (user_id, skill_id))
    exists = cur.fetchone()
    if not exists:
        cur.execute("INSERT INTO user_skills (user_id, skill_id) VALUES (%s, %s)", (user_id, skill_id))
        cur.execute("UPDATE skills SET usage_count = COALESCE(usage_count,0) + 1 WHERE skill_id=%s", (skill_id,))
        conn.commit(); cur.close(); conn.close()
        return jsonify({'success': True, 'skill': {'skill_id': skill_id, 'skill_name': skill_name, 'category': category, 'count': 1}})

    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True, 'skill': {'skill_id': skill_id, 'skill_name': skill_name, 'category': category, 'count': 1}})


@app.route('/remove_skill/<int:skill_id>', methods=['POST'])
def remove_skill(skill_id):
    if not require_login():
        return jsonify({'success': False, 'message': 'Login required'}), 401

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM user_skills WHERE user_id=%s AND skill_id=%s", (user_id, skill_id))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'success': True})


# ---------------- CONNECTIONS ----------------
@app.route('/connections', methods=['GET', 'POST'])
def connections():
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()

    # Other users to send requests to. exclude self and users already connected or pending in either direction.
    cur.execute("SELECT sender_id FROM connections WHERE sender_id=%s OR receiver_id=%s UNION SELECT receiver_id FROM connections WHERE sender_id=%s OR receiver_id=%s", (user_id, user_id, user_id, user_id))
    related_user_ids = {r[0] for r in cur.fetchall()}

    cur.execute("SELECT user_id, name, email FROM users WHERE user_id != %s", (user_id,))
    all_users = [{'user_id': r[0], 'name': r[1], 'email': r[2]} for r in cur.fetchall()]

    users = [u for u in all_users if u['user_id'] not in related_user_ids]

    # decide mutual friends for suggestions (shared accepted connections by skill or network)
    cur.execute("SELECT receiver_id FROM connections WHERE sender_id=%s AND status='accepted' UNION SELECT sender_id FROM connections WHERE receiver_id=%s AND status='accepted'", (user_id, user_id))
    accepted_ids = {r[0] for r in cur.fetchall()}

    cur.execute("SELECT u.user_id, u.name, u.email FROM users u JOIN user_skills us ON u.user_id=us.user_id WHERE us.skill_id IN (SELECT skill_id FROM user_skills WHERE user_id=%s) AND u.user_id != %s", (user_id, user_id))
    skill_friends = [{'user_id': r[0], 'name': r[1], 'email': r[2]} for r in cur.fetchall()]

    mutual_friends = [u for u in skill_friends if u['user_id'] in accepted_ids and u['user_id'] not in related_user_ids]

    # pending requests where current user is receiver
    cur.execute("SELECT c.connection_id, u.name FROM connections c JOIN users u ON c.sender_id = u.user_id WHERE c.receiver_id=%s AND c.status='pending'", (user_id,))
    pending_requests = [{'connection_id': r[0], 'sender_name': r[1]} for r in cur.fetchall()]

    # outgoing requests where current user is sender (can withdraw)
    cur.execute("SELECT c.connection_id, u.name FROM connections c JOIN users u ON c.receiver_id = u.user_id WHERE c.sender_id=%s AND c.status='pending'", (user_id,))
    outgoing_requests = [{'connection_id': r[0], 'receiver_name': r[1]} for r in cur.fetchall()]

    # total waiting count
    standing_requests = len(pending_requests)

    cur.close(); conn.close()
    return render_template('connections.html', users=users, pending_requests=pending_requests, outgoing_requests=outgoing_requests, mutual_friends=mutual_friends, standing_requests=standing_requests)


@app.route('/notifications')
def notifications():
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT notification_id, source_user_id, type, message, is_read, created_at FROM notifications WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
        notes = [{'id': r[0], 'source_user_id': r[1], 'type': r[2], 'message': r[3], 'is_read': r[4], 'when': r[5]} for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM notifications WHERE user_id=%s AND is_read=false", (user_id,))
        unread_count = cur.fetchone()[0]
    except Exception:
        notes = []
        unread_count = 0
    finally:
        cur.close(); conn.close()

    if request.args.get('json') == '1':
        return {'unread_count': unread_count}

    return render_template('notifications.html', notifications=notes, unread_count=unread_count)


@app.route('/notifications/read/<int:notification_id>', methods=['POST'])
def set_notification_read(notification_id):
    if not require_login():
        return redirect(url_for('login_page'))
    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE notifications SET is_read=true WHERE notification_id=%s AND user_id=%s", (notification_id, user_id))
    conn.commit(); cur.close(); conn.close()
    return redirect(url_for('notifications'))


@app.route('/send_request/<int:user_id>', methods=['POST'])
def send_request(user_id):
    if not require_login():
        return redirect(url_for('login_page'))

    me = session['user_id']
    conn = get_connection(); cur = conn.cursor()

    cur.execute("SELECT connection_id, sender_id, receiver_id, status FROM connections WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)",
                (me, user_id, user_id, me))
    existing = cur.fetchone()

    if existing:
        _, s_id, r_id, status = existing
        if status == 'accepted':
            flash('You are already connected with this user.', 'info')
        elif status == 'pending':
            if s_id == me:
                flash('Connection request already sent and pending.', 'info')
            else:
                flash('This user already sent you a request. Please accept it.', 'info')
        else:
            flash('Connection already exists as status: %s' % status, 'info')
    else:
        cur.execute("INSERT INTO connections (sender_id, receiver_id, status) VALUES (%s,%s,%s)",
                    (me, user_id, 'pending'))
        # create notification for recipient
        cur.execute("INSERT INTO notifications (user_id, source_user_id, type, message) VALUES (%s,%s,%s,%s)",
                    (user_id, me, 'connection_request', 'New connection request from %s' % session.get('user_name', 'Someone')))
        conn.commit()
        flash('Connection request sent!', 'success')

    cur.close(); conn.close()
    return redirect(url_for('connections'))


@app.route('/withdraw_request/<int:connection_id>', methods=['POST'])
def withdraw_request(connection_id):
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT sender_id, receiver_id, status FROM connections WHERE connection_id=%s", (connection_id,))
    row = cur.fetchone()
    if row and row[0] == user_id and row[2] == 'pending':
        cur.execute("DELETE FROM connections WHERE connection_id=%s", (connection_id,))
        cur.execute("DELETE FROM notifications WHERE user_id=%s AND source_user_id=%s AND type='connection_request'", (row[1], row[0]))
        conn.commit()
        flash('Connection request withdrawn.', 'info')
    else:
        flash('Unable to withdraw request.', 'error')

    cur.close(); conn.close()
    return redirect(url_for('connections'))


@app.route('/respond_request/<int:connection_id>/<action>', methods=['POST'])
def respond_request(connection_id, action):
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT receiver_id, sender_id, status FROM connections WHERE connection_id=%s", (connection_id,))
    row = cur.fetchone()

    if not row:
        cur.close(); conn.close()
        flash('Connection request not found.', 'error')
        return redirect(url_for('connections'))

    receiver_id, sender_id, status = row
    if receiver_id != user_id:
        cur.close(); conn.close()
        flash('You are not authorized to respond to this request.', 'error')
        return redirect(url_for('connections'))

    if status != 'pending':
        cur.close(); conn.close()
        flash('This request has already been responded to.', 'info')
        return redirect(url_for('connections'))

    if action == 'accept':
        cur.execute("UPDATE connections SET status='accepted' WHERE connection_id=%s", (connection_id,))
        flash('Connection accepted. You can now message this user.', 'success')
    else:
        cur.execute("UPDATE connections SET status='rejected' WHERE connection_id=%s", (connection_id,))
        flash('Connection request rejected.', 'info')

    conn.commit(); cur.close(); conn.close()
    return redirect(url_for('connections'))


# ---------------- MESSAGES ----------------
@app.route('/messages')
def messages():
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    partner_id = request.args.get('with_user', type=int)

    ensure_messages_attachment_column()
    conn = get_connection(); cur = conn.cursor()
    # only accepted connections as contacts
    cur.execute("""
        SELECT u.user_id, u.name, u.profile_pic
        FROM users u
        JOIN connections c ON (
            (c.sender_id = %s AND c.receiver_id = u.user_id)
            OR
            (c.receiver_id = %s AND c.sender_id = u.user_id)
        )
        WHERE c.status = 'accepted'
        ORDER BY u.name
    """, (user_id, user_id))

    contacts = [{'user_id': r[0], 'name': r[1], 'profile_pic': r[2]} for r in cur.fetchall()]

    # unread counts per contact
    unread_map = {}
    try:
        cur.execute("SELECT sender_id, COUNT(*) FROM messages WHERE receiver_id=%s AND is_read=false GROUP BY sender_id", (user_id,))
        unread_map = {r[0]: r[1] for r in cur.fetchall()}
    except Exception:
        unread_map = {}

    selected_user = None
    thread = []
    if partner_id:
        cur.execute("SELECT user_id, name FROM users WHERE user_id=%s", (partner_id,))
        u = cur.fetchone()
        selected_user = {'user_id': u[0], 'name': u[1]} if u else None

        try:
            cur.execute(
                "SELECT sender_id, receiver_id, message_text, attachment, is_read, created_at FROM messages WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s) ORDER BY created_at ASC",
                (user_id, partner_id, partner_id, user_id)
            )
            rows = cur.fetchall()
            thread = [{'sender_id': r[0], 'receiver_id': r[1], 'message_text': r[2], 'attachment': r[3], 'is_read': r[4], 'sent_at': r[5]} for r in rows]

            # mark partner messages as read now
            cur.execute("UPDATE messages SET is_read=true WHERE sender_id=%s AND receiver_id=%s", (partner_id, user_id))
            conn.commit()
        except Exception:
            # fallback if attachment/is_read is missing (older schema), include will still work if absent columns are not used
            try:
                cur.execute(
                    "SELECT sender_id, receiver_id, message_text, attachment, created_at FROM messages WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s) ORDER BY created_at ASC",
                    (user_id, partner_id, partner_id, user_id)
                )
                rows = cur.fetchall()
                thread = [{'sender_id': r[0], 'receiver_id': r[1], 'message_text': r[2], 'attachment': r[3], 'sent_at': r[4]} for r in rows]
            except Exception:
                cur.execute(
                    "SELECT sender_id, receiver_id, message_text, created_at FROM messages WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s) ORDER BY created_at ASC",
                    (user_id, partner_id, partner_id, user_id)
                )
                rows = cur.fetchall()
                thread = [{'sender_id': r[0], 'receiver_id': r[1], 'message_text': r[2], 'attachment': None, 'sent_at': r[3]} for r in rows]

    cur.close(); conn.close()
    return render_template('messages.html', contacts=contacts, selected_user=selected_user, thread=thread, user_id=user_id, unread_map=unread_map)


@app.route('/send_message', methods=['POST'])
def send_message():
    if not require_login():
        return redirect(url_for('login_page'))

    sender = session['user_id']
    receiver = int(request.form.get('receiver_id', 0))
    message_text = request.form.get('message', '').strip()

    attachment = None
    file = request.files.get('attachment')
    if file and file.filename != '' and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        attachment = url_for('static', filename=f'upload/{filename}')

    if receiver and (message_text or attachment):
        ensure_messages_attachment_column()
        conn = get_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO messages (sender_id, receiver_id, message_text, attachment, is_read) VALUES (%s,%s,%s,%s,%s)",
                    (sender, receiver, message_text, attachment, False))
        # add notification for receiver
        cur.execute("INSERT INTO notifications (user_id, source_user_id, type, message) VALUES (%s,%s,%s,%s)",
                    (receiver, sender, 'message', f'New message from {session.get("user_name", "Someone")}'))
        conn.commit(); cur.close(); conn.close()

    return redirect(url_for('messages', with_user=receiver))


# ---------------- SETTINGS ----------------
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    conn = get_connection(); cur = conn.cursor()

    avatar_choices = [
        'https://api.dicebear.com/7.x/adventurer/svg?seed=bright-owl',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=happy-tiger',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=sunny-fox',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=kind-owl',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=courageous-lynx',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=cheerful-rabbit',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=brave-fox',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=lively-falcon',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=bold-panther',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=calm-owl',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=gentle-panda',
        'https://api.dicebear.com/7.x/adventurer/svg?seed=smart-koala'
    ]

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        bio = request.form.get('bio')
        profile_pic = request.form.get('profile_pic') or None

        ensure_skill_metadata_columns()

        selected_skills = request.form.getlist('skills')
        new_skill_raw = request.form.get('new_skill', '').strip()
        new_skill_category = request.form.get('new_skill_category', 'Non-Tech').strip() or 'Non-Tech'

        # support comma-separated skill entry for multiple skills
        if new_skill_raw:
            for token in new_skill_raw.split(','):
                skill_name = token.strip()
                if skill_name:
                    selected_skills.append((skill_name, new_skill_category))

        cur.execute("UPDATE users SET name=%s, email=%s, bio=%s, profile_pic=%s WHERE user_id=%s", (name, email, bio, profile_pic, user_id))
        cur.execute("DELETE FROM user_skills WHERE user_id=%s", (user_id,))

        for skill_item in selected_skills:
            if isinstance(skill_item, tuple):
                normalized = skill_item[0].strip()
                skill_category = skill_item[1].strip() if len(skill_item) > 1 else 'Non-Tech'
            else:
                normalized = skill_item.strip()
                skill_category = 'Non-Tech'

            if not normalized:
                continue

            cur.execute("INSERT INTO skills (skill_name, category) VALUES (%s,%s) ON CONFLICT(skill_name) DO UPDATE SET category=EXCLUDED.category", (normalized, skill_category))
            cur.execute("SELECT skill_id FROM skills WHERE skill_name=%s", (normalized,))
            skill_row = cur.fetchone()
            if skill_row:
                cur.execute("INSERT INTO user_skills (user_id, skill_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, skill_row[0]))
                # increment usage_count only once per user-skill assignment
                cur.execute("UPDATE skills SET usage_count = COALESCE(usage_count,0) + 1 WHERE skill_id=%s AND EXISTS (SELECT 1 FROM user_skills WHERE user_id=%s AND skill_id=%s)", (skill_row[0], user_id, skill_row[0]))

        conn.commit()
        session['user_name'] = name
        session['user_email'] = email
        session['user_profile_pic'] = profile_pic

    cur.execute("SELECT user_id, name, email, bio, profile_pic FROM users WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    user = {'user_id': row[0], 'name': row[1], 'email': row[2], 'bio': row[3], 'profile_pic': row[4]}

    cur.execute("SELECT skill_name FROM skills ORDER BY skill_name")
    skill_options = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT s.skill_name FROM skills s JOIN user_skills us ON s.skill_id=us.skill_id WHERE us.user_id=%s", (user_id,))
    user_skills = [r[0] for r in cur.fetchall()]

    uploads = []
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    for fname in os.listdir(app.config['UPLOAD_FOLDER']):
        if allowed_file(fname):
            uploads.append(url_for('static', filename=f'upload/{fname}'))

    cur.close(); conn.close()
    return render_template('settings.html', user=user, avatar_choices=avatar_choices, skill_options=skill_options, user_skills=user_skills)


# ---------------- RATING ----------------
@app.route('/rate/<int:video_id>', methods=['POST'])
def rate(video_id):
    if not require_login():
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    rating = int(request.form.get('rating', 0))
    if rating < 1 or rating > 5:
        return redirect(url_for('dashboard'))

    conn = get_connection()
    cur = conn.cursor()

    # if rating exists by this user update, else insert
    cur.execute("SELECT rating_id FROM ratings WHERE video_id=%s AND user_id=%s", (video_id, user_id))
    existing = cur.fetchone()
    if existing:
        cur.execute("UPDATE ratings SET rating=%s WHERE rating_id=%s", (rating, existing[0]))
    else:
        cur.execute("INSERT INTO ratings (video_id, user_id, rating) VALUES (%s, %s, %s)", (video_id, user_id, rating))

    # update uploader analytics with video rating events
    try:
        cur.execute("SELECT user_id FROM videos WHERE video_id=%s", (video_id,))
        owner = cur.fetchone()
        if owner:
            owner_id = owner[0]
            cur.execute("SELECT analytics_id FROM analytics WHERE user_id=%s AND date=CURRENT_DATE", (owner_id,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE analytics SET profile_views = profile_views + 1 WHERE analytics_id=%s", (row[0],))
            else:
                cur.execute("INSERT INTO analytics (user_id, date, profile_views) VALUES (%s, CURRENT_DATE, 1)", (owner_id,))
    except Exception:
        pass

    conn.commit(); cur.close(); conn.close()

    if request.is_json:
        return jsonify({'success': True, 'rating': rating})
    return redirect('/dashboard')


# ---------------- RUN ----------------
if __name__ == '__main__':
    app.run(debug=True)