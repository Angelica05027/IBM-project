import sqlite3
from flask import g

# Database file name
DATABASE = "factory_security.db"

# -----------------------------
# 📌 Get Database Connection
# -----------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row  # access columns by name
    return g.db


# -----------------------------
# ❌ Close Connection
# -----------------------------
def close_db(e=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


# -----------------------------
# 🏗️ Initialize Database
# -----------------------------
def init_db():
    db = get_db()

    with open("database/schema.sql", "r") as f:
        db.executescript(f.read())


# -----------------------------
# 🔗 Init App (connect with Flask)
# -----------------------------
def init_app(app):
    app.teardown_appcontext(close_db)

    # Command to initialize DB manually
    @app.cli.command("init-db")
    def init_db_command():
        init_db()
        print("✅ Database initialized successfully!")