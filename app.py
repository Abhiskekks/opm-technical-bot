import os
import json
import re
import datetime
import shutil
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, stream_with_context
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from functools import wraps

# --- CUSTOM MODULE IMPORTS ---
from user_model import (
    get_user_by_username, get_user_by_id, get_conversations_for_user, 
    get_conversation_by_id, add_new_conversation, append_to_conversation, 
    create_new_user, AnonymousUser, get_all_users
)

import chat_engine
from chat_engine import (
    find_best_answer, generate_ai_response, detect_intent, 
    df, NAME_COL, KNOWLEDGE_BASE_FILE, clean_to_digits, CODE_COL, SUB_CODE_COL, DESCRIPTION_COL,
    init_db_from_excel, get_db_preview
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'toshiba_opm_2025_secret')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, 'kb_backups')
if not os.path.exists(BACKUP_DIR): 
    os.makedirs(BACKUP_DIR)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.anonymous_user = AnonymousUser

@login_manager.user_loader
def load_user(user_id): 
    return get_user_by_id(user_id)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            flash("Admin access required.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    conversations = get_conversations_for_user(current_user.id) if current_user.is_authenticated else []
    return render_template('index.html', conversations=conversations)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = get_user_by_username(username)
        if user and user.password == password:
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid Employee ID or password.', 'error')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username and password:
            create_new_user(username, password)
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    users = get_all_users()
    backups = sorted(os.listdir(BACKUP_DIR), reverse=True) if os.path.exists(BACKUP_DIR) else []
    search_query = request.args.get('search', '').strip()
    db_preview = chat_engine.get_db_preview(limit=50, search_filter=search_query) 
    cols = db_preview[0].keys() if db_preview else []
    
    return render_template('admin.html', 
                           users=users, 
                           backups=backups, 
                           db_preview=db_preview, 
                           cols=cols,
                           search_query=search_query)

@app.route('/admin/upload', methods=['POST'])
@admin_required
def upload_kb():
    if 'file' not in request.files:
        flash('No file selected.', 'error')
        return redirect(url_for('admin_dashboard'))
    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('admin_dashboard'))

    active_kb_path = os.path.join(BASE_DIR, KNOWLEDGE_BASE_FILE)
    try:
        if os.path.exists(active_kb_path):
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy(active_kb_path, os.path.join(BACKUP_DIR, f"backup_{ts}.xlsx"))
        file.save(active_kb_path)
        chat_engine.init_db_from_excel()
        chat_engine.df = chat_engine.load_database()
        flash('Database and SQLite storage updated successfully.', 'success')
    except Exception as e:
        flash(f'Update failed: {str(e)}', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/revert/<filename>')
@admin_required
def revert_kb(filename):
    secure_name = os.path.basename(filename)
    backup_path = os.path.join(BACKUP_DIR, secure_name)
    active_kb_path = os.path.join(BASE_DIR, KNOWLEDGE_BASE_FILE)
    
    if os.path.exists(backup_path):
        try:
            shutil.copy(backup_path, active_kb_path)
            chat_engine.init_db_from_excel()
            chat_engine.df = chat_engine.load_database()
            flash(f"Successfully reverted to {secure_name}", "success")
        except Exception as e:
            flash(f"Revert failed: {str(e)}", "error")
    else:
        flash("Backup file not found.", "error")
    return redirect(url_for('admin_dashboard'))

@app.route('/chat_submit', methods=['POST'])
@login_required
def chat_submit():
    prompt = request.form.get('prompt', '').strip()
    conv_id_raw = request.form.get('conv_id')
    conv_id = int(conv_id_raw) if conv_id_raw and conv_id_raw.isdigit() else None
    if not prompt: 
        return jsonify(success=False), 400

    def generate():
        full_resp = ""
        intent = detect_intent(prompt)
        history = []
        if conv_id:
            conv = get_conversation_by_id(current_user.id, conv_id)
            if conv: 
                history = [{'role': m.role, 'content': m.content} for m in conv.messages]

        match_found, excel_text, data_str, status = find_best_answer(prompt, history)
        for ai_chunk in generate_ai_response(prompt, history, data_str, intent=intent, status=status):
            full_resp += ai_chunk
            yield f"data: {json.dumps({'chunk': ai_chunk})}\n\n"
        
        if conv_id:
            append_to_conversation(current_user.id, conv_id, prompt, full_resp)
        else:
            new_id = add_new_conversation(current_user.id, prompt[:30], prompt, full_resp)
            yield f"data: {json.dumps({'conv_id': new_id})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)