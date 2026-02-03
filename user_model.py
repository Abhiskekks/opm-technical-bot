# user_model.py - UPDATED FOR SESSION PERSISTENCE

from flask_login import AnonymousUserMixin

class User:
    """Represents a simple user in the system with role support."""
    def __init__(self, user_id, username, password, is_admin=False):
        self.id = user_id
        self.username = username
        self.password = password  # In production, this must be hashed!
        self.is_admin = is_admin  # Flag to identify administrative users
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def get_id(self):
        return str(self.id)

# --- Conversation Models ---

class Message:
    """Represents a single message in a conversation."""
    def __init__(self, role, content):
        self.role = role  # 'user' or 'assistant'
        self.content = content
        
class Conversation:
    """Represents a thread of chat messages for a single user."""
    # Counter starts high to avoid conflict with pre-seeded IDs 1 and 2
    conversation_id_counter = 3 
    
    def __init__(self, user_id, title=None):
        self.id = Conversation.conversation_id_counter
        Conversation.conversation_id_counter += 1
        self.user_id = user_id
        self.title = title if title else "New Chat"
        self.messages = []

# --- Database Simulation (In-Memory Storage) ---

# User Storage
USERS = {
    1: User(1, "testuser", "password", is_admin=False),
    2: User(2, "admin", "admin123", is_admin=True)
}

# Conversation Storage (user_id -> list of Conversation objects)
CONVERSATIONS = {
    1: [
        Conversation(1, title="NW-621 Search"),
        Conversation(1, title="Logging Configuration")
    ],
    2: []
}

# Fix IDs for pre-seeded conversations to match index 1 and 2
CONVERSATIONS[1][0].id = 1
CONVERSATIONS[1][0].messages.extend([
    Message('user', 'Give the 08 code of NW-621'),
    Message('assistant', 'Details for Code: NW-621. Access Code: NW-621. Setting Item Name: Network Protocol for 621.'),
])

CONVERSATIONS[1][1].id = 2
CONVERSATIONS[1][1].messages.extend([
    Message('user', 'How do I change the logging level?'),
    Message('assistant', 'To change the logging level, use Access Code PR-401.'),
])

# --- Functions for App.py to use ---

def get_user_by_id(user_id):
    """Used by Flask-Login to load a user."""
    try:
        return USERS.get(int(user_id))
    except (ValueError, TypeError):
        return None

def get_user_by_username(username):
    """Used for login authentication."""
    for user in USERS.values():
        if user.username == username:
            return user
    return None

def get_all_users():
    """Returns a list of all users for admin dashboard visibility."""
    return list(USERS.values())

def create_new_user(username, password, is_admin=False):
    """Creates a new user and initializes their conversation list."""
    if get_user_by_username(username):
        return None 
    new_id = max(USERS.keys()) + 1 if USERS else 1
    new_user = User(new_id, username, password, is_admin=is_admin)
    USERS[new_id] = new_user
    CONVERSATIONS[new_id] = [] 
    return new_user

def get_conversations_for_user(user_id):
    """Retrieves all chat threads for a specific user."""
    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []
    return CONVERSATIONS[user_id]

def get_conversation_by_id(user_id, conv_id):
    """Retrieves a specific chat thread by user ID and conversation ID."""
    for conv in get_conversations_for_user(user_id):
        if conv.id == conv_id:
            return conv
    return None
    
def add_new_conversation(user_id, title, user_message, assistant_response):
    """
    Creates a new conversation thread.
    RETURNS: The new conversation ID (Critical for frontend session sync).
    """
    conv = Conversation(user_id, title=title)
    conv.messages.append(Message('user', user_message))
    conv.messages.append(Message('assistant', assistant_response))
    
    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []
    
    # Insert at index 0 so most recent chats appear first
    CONVERSATIONS[user_id].insert(0, conv)
    
    # Returning the ID allows app.py to send it back to the JS frontend
    return conv.id

def append_to_conversation(user_id, conv_id, user_message, assistant_response):
    """Adds a new message pair to an existing thread."""
    conv = get_conversation_by_id(user_id, conv_id)
    if conv:
        conv.messages.append(Message('user', user_message))
        conv.messages.append(Message('assistant', assistant_response))
        return True
    return False

# Setup for Flask-Login compatibility (required methods)
class AnonymousUser(AnonymousUserMixin):
    username = "Guest"
    is_admin = False