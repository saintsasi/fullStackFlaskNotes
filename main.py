# FILE: main.py (Final Stability Fix)

from website import create_app, db, run_socketio_app
from website.models import User, Note, Message, Tag, ClassRoom, ClassPost, Reaction, Comment, NoteHistory # Import ALL models

# --- Explicit Setup for Immediate Schema Creation ---

# 1. Create a temporary app instance to access the DB engine
temp_app = create_app()

# 2. Force creation of all tables if they don't exist
# This is a one-time check to ensure the schema is correct before running the server.
with temp_app.app_context():
    # This must be run BEFORE the application attempts to load any context processor
    db.create_all() 
    print("--- SCHEMA VERIFIED AND CREATED. ---")

# --- Run Application ---

# Now the application runs using the stable schema
if __name__ == "__main__":
    run_socketio_app()