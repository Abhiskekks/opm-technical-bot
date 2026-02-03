import pandas as pd
import re
import os
import ast
import sqlite3

# --- CONFIGURATION ---
KNOWLEDGE_BASE_FILE = 'knowledge_base_file.xlsx' 
DB_FILE = 'technical_kb.db' 

CODE_COL = 'Access Code'
NAME_COL = 'Setting item name' 
SUB_CODE_COL = 'Sub Code'
DESCRIPTION_COL = 'Description of values'

def clean_to_digits(val):
    if pd.isna(val) or str(val).lower() == 'nan' or str(val).strip() == "": 
        return ""
    s = str(val).split('.')[0]
    return re.sub(r'\D', '', s).strip()

def detect_intent(text):
    clean = text.lower().strip()
    # Confirmation logic - now includes more variations to prevent noise
    if clean in ["yes", "y", "yep", "ok", "okay", "show", "show me", "got it", "correct"]:
        return "CONFIRMATION"
    if clean in ["no", "n", "nope", "stop", "exit", "cancel"]:
        return "EXIT"
    if any(phrase in clean for phrase in ["setting name", "name of", "what is the name"]):
        return "NAME_QUERY"
    if any(phrase in clean for phrase in ["access code for", "code for", "what is the code"]):
        return "CODE_QUERY"
    if any(word in clean for word in ["hi", "hello", "hey", "thanks", "help"]):
        return "CONVERSATIONAL"
    return "TECHNICAL"

def init_db_from_excel():
    """Initializes the SQLite DB from Excel - required by app.py"""
    if not os.path.exists(KNOWLEDGE_BASE_FILE):
        print(f"Error: {KNOWLEDGE_BASE_FILE} not found.")
        return
    try:
        data = pd.read_excel(KNOWLEDGE_BASE_FILE)
        data.columns = [str(c).strip() for c in data.columns]
        conn = sqlite3.connect(DB_FILE)
        data.to_sql('knowledge_base', conn, if_exists='replace', index=False)
        conn.close()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Error syncing Excel to SQLite: {e}")

def load_database():
    if not os.path.exists(DB_FILE):
        init_db_from_excel()
    try:
        conn = sqlite3.connect(DB_FILE)
        data = pd.read_sql_query("SELECT * FROM knowledge_base", conn)
        conn.close()
        data[CODE_COL] = data[CODE_COL].apply(clean_to_digits)
        data[NAME_COL] = data[NAME_COL].astype(str).str.strip()
        data[SUB_CODE_COL] = data[SUB_CODE_COL].fillna('-').astype(str).str.strip()
        data[DESCRIPTION_COL] = data[DESCRIPTION_COL].fillna('No data').astype(str).str.strip()
        return data
    except Exception:
        return pd.DataFrame()

# Load DB into memory for fast searching
df = load_database()

def format_clean_description(text):
    text = str(text).strip()
    parts = re.split(r'(\d+:)', text)
    if len(parts) <= 1: return text
    formatted_list = []
    for i in range(1, len(parts), 2):
        label = parts[i]
        value = parts[i+1].strip() if (i+1) < len(parts) else ""
        formatted_list.append(f"{label} {value}")
    return " <br> ".join(formatted_list)

def find_best_answer(user_prompt, history=None):
    global df
    if df is None or df.empty: 
        return True, "", str({"mode": "NOT_FOUND"}), "DATA_MISSING"

    user_text = user_prompt.lower().strip()
    intent = detect_intent(user_text)
    
    # --- 1. EXIT & CONVERSATIONAL ---
    if intent == "EXIT":
        return True, "", str({"mode": "EXIT"}), "READY"
    
    if intent == "CONVERSATIONAL":
        return False, "", "{}", "NONE"
    
    # --- 2. HANDLE CONFIRMATIONS (The "OK" Fix) ---
    if intent == "CONFIRMATION":
        if history:
            last_msg = str(history[-1].get('content', ''))
            # User says OK to seeing sub-codes
            if "know the sub code" in last_msg:
                code_match = re.search(r'\(Code: (\d+)\)', last_msg)
                if code_match:
                    code = code_match.group(1)
                    rows = df[df[CODE_COL] == code].copy()
                    table_lines = ["| Sub-Code | Description / Values |", "| :--- | :--- |"]
                    for _, r in rows.iterrows():
                        sub = "NA" if r[SUB_CODE_COL] == "-" else r[SUB_CODE_COL]
                        table_lines.append(f"| {sub} | {format_clean_description(r[DESCRIPTION_COL])} |")
                    return True, "", str({"mode": "SUB_TABLE", "table": "\n".join(table_lines), "code": code}), "READY"

            # User says OK to seeing procedures
            if "how to set the 08 code" in last_msg or "💡" in last_msg:
                return True, "", "{}", "SHOW_PROCEDURE"
        
        # IMPORTANT: If intent is confirmation but no specific history match, 
        # stop here anyway so we don't search for "ok" in the database.
        return False, "", "{}", "NONE"

    # --- 3. TECHNICAL SEARCH (Only reached if NOT a confirmation) ---
    search_term = re.sub(r'(what is the|access code for|code for|setting name of|name of code|the code for|setting name for)', '', user_text).strip()
    
    # Final safety: stop if the term is too short or just "ok"
    if len(search_term) < 2 or search_term == "ok":
        return False, "", "{}", "NONE"

    # Search Logic (Codes)
    all_codes = re.findall(r'\b\d{4,5}\b', search_term)
    if all_codes:
        rows = df[df[CODE_COL] == all_codes[0]].copy()
        if intent == "NAME_QUERY" and not rows.empty:
            return True, "", str({"mode": "NAME_ONLY", "name": rows.iloc[0][NAME_COL], "code": all_codes[0]}), "READY"
    else:
        # Search Logic (Names)
        rows = df[df[NAME_COL].str.lower() == search_term].copy()
        if rows.empty:
            rows = df[df[NAME_COL].str.lower().str.contains(search_term, na=False)].copy()
        
        if intent == "CODE_QUERY" and not rows.empty:
            return True, "", str({"mode": "NAME_ONLY", "name": rows.iloc[0][NAME_COL], "code": rows.iloc[0][CODE_COL]}), "READY"

    # Process search results (LIST, COMPARE, or SINGLE)...
    if rows.empty: 
        return True, "", str({"mode": "NOT_FOUND", "query": search_term}), "DATA_MISSING"

    unique_codes = sorted(rows[CODE_COL].unique())

    if len(unique_codes) > 2:
        match_list = rows.drop_duplicates(subset=[CODE_COL, NAME_COL])[[CODE_COL, NAME_COL]]
        tbl = "| Access Code | Setting Name |\n| :--- | :--- |\n"
        for _, r in match_list.iterrows():
            tbl += f"| {r[CODE_COL]} | {r[NAME_COL]} |\n"
        return True, "", str({"mode": "LIST", "query": search_term.upper(), "content": tbl}), "READY"
    
    elif len(unique_codes) == 2:
        # (Your existing Compare logic)
        c1, c2 = unique_codes[0], unique_codes[1]
        n1, n2 = rows[rows[CODE_COL]==c1].iloc[0][NAME_COL], rows[rows[CODE_COL]==c2].iloc[0][NAME_COL]
        table_lines = [f"| Sub | {c1} ({n1}) | {c2} ({n2}) |", "| :--- | :--- | :--- |"]
        all_subs = sorted(rows[SUB_CODE_COL].unique())
        for sub in all_subs:
            v1 = rows[(rows[CODE_COL]==c1) & (rows[SUB_CODE_COL]==sub)][DESCRIPTION_COL].tolist()
            v2 = rows[(rows[CODE_COL]==c2) & (rows[SUB_CODE_COL]==sub)][DESCRIPTION_COL].tolist()
            d1 = format_clean_description(v1[0]) if v1 else "-"
            d2 = format_clean_description(v2[0]) if v2 else "-"
            s_label = "NA" if sub == "-" else sub
            table_lines.append(f"| {s_label} | {d1} | {d2} |")
        return True, "", str({"mode": "COMPARE", "query": search_term.upper(), "table": "\n".join(table_lines)}), "READY"
    
    else:
        # (Your existing Single logic)
        rows = rows.drop_duplicates(subset=[SUB_CODE_COL], keep='first')
        table_lines = ["| Sub-Code | Description / Values |", "| :--- | :--- |"]
        for _, r in rows.iterrows():
            sub = "NA" if r[SUB_CODE_COL] == "-" else r[SUB_CODE_COL]
            table_lines.append(f"| {sub} | {format_clean_description(r[DESCRIPTION_COL])} |")
        return True, "", str({"mode": "SINGLE", "name": rows.iloc[0][NAME_COL], "code": rows.iloc[0][CODE_COL], "table": "\n".join(table_lines)}), "READY"

def generate_ai_response(user_prompt, history, data_str, search_context="", intent="TECHNICAL", status="READY"):
    if status == "DATA_MISSING":
        yield "🔍 I couldn't find any technical data for that. Please check the spelling or try the Access Code."
        return

    if status == "SHOW_PROCEDURE":
        yield "### 🛠️ 08 Service Mode Procedure\n\n1. Go to **User Function** -> **Setting Icon**.\n2. Enter **Password** -> Select **08 Code**.\n3. Enter the **08 Code** -> Press **Enter**.\n4. Enter **Sub Code** -> **Enter**.\n5. Enter **Value** -> **Enter** to save."
        return

    try:
        info = ast.literal_eval(data_str)
        mode = info.get("mode")

        if mode == "EXIT":
            yield "Understood. Let me know if you need help with other codes!"
        
        elif mode == "NAME_ONLY":
            current_intent = detect_intent(user_prompt)
            if current_intent == "NAME_QUERY":
                yield f"The setting name for **{info['code']}** is **{info['name']}**.\n\n 💡 Do you want to know the sub code for that? (Code: {info['code']})"
            else:
                yield f"The Access Code for **{info['name']}** is **{info['code']}**.\n\n 💡 Do you want to know the sub code for that? (Code: {info['code']})"

        elif mode == "SUB_TABLE":
            yield f"Here are the sub codes for code **{info['code']}**:\n\n{info['table']}\n\n 💡 Do you want to know how to set the 08 code?"
        
        elif mode == "SINGLE":
            yield f"Technical Record for **{info['name']}** (Code: {info['code']})\n\n{info['table']}\n\n💡 **Suggestion:** Type **Yes** to see the 08 procedure."
        
        elif mode == "LIST":
            yield f"I found several entries for **{info.get('query')}**:\n\n{info['content']}\n\n💡 Please type the specific **Access Code** you need."
        
        elif mode == "COMPARE":
            yield f"### 📊 Side-by-Side Comparison: {info.get('query')}\n\n{info['table']}\n\n💡 **Tip:** Use these to check state differences."
        
        else:
            yield "Hello! I am your Technical Assistant. How can I help you today?"
    except:
        yield "Hello! How can I help you today?"

def get_db_preview(limit=50, search_filter=""):
    if not os.path.exists(DB_FILE): return []
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if search_filter:
            query = f"SELECT * FROM knowledge_base WHERE \"{CODE_COL}\" LIKE ? OR \"{NAME_COL}\" LIKE ? LIMIT ?"
            cursor.execute(query, (f'%{search_filter}%', f'%{search_filter}%', limit))
        else:
            cursor.execute(f"SELECT * FROM knowledge_base LIMIT {limit}")
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"Preview error: {e}")
        return []