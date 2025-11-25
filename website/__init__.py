# FILE: website/__init__.py (Corrected and Stable)

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_socketio import SocketIO 

db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO(cors_allowed_origins="*")

DB_NAME = 'database.db'


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'aldskfhlsd_lakdshflk'
    app.config['UPLOAD_FOLDER'] = path.join(path.abspath(path.join(path.dirname(__file__), '..')), 'uploads')

    project_root = path.abspath(path.join(path.dirname(__file__), '..'))
    db_path = path.join(project_root, DB_NAME)

    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"

    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)

    # Import ALL models BEFORE create_all()
    from .models import (
        User, Note, Tag, Comment, Reaction,
        ClassRoom, ClassPost, Message, NoteHistory,
        ClassChatMessage, Poll, PollOption, PollVote, NoteAttachment
    )

    # Register Blueprints
    from .views import views
    from .auth import auth
    from .admin import admin

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')
    app.register_blueprint(admin, url_prefix='/admin')

    # Create DB if missing
    create_database(app)

    # Login manager setup
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer-when-downgrade")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        # Light CSP to allow static/CDN
        response.headers.setdefault("Content-Security-Policy",
            "default-src 'self' data: blob:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://code.jquery.com https://cdn.quilljs.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdn.quilljs.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: blob: https://*; "
            "connect-src 'self';"
        )
        return response

    return app


def create_database(app):
    """Create the database file + all tables if DB is missing."""
    db_file = app.config['SQLALCHEMY_DATABASE_URI'].replace("sqlite:///", "")

    if not path.exists(db_file):
        print(f"Database not found. Creating new database at: {db_file}")
        with app.app_context():
            db.create_all()
            db.session.commit()
            print("Database schema created successfully!")


def run_socketio_app():
    app = create_app()
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)
