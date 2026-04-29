import os
import sqlite3
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "simple-dev-secret")
app.config["DATABASE"] = os.path.join(app.root_path, "manufacturing.db")


# -----------------------------
# Database helpers
# -----------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.teardown_appcontext
def teardown_db(exception):
    close_db(exception)


def init_db():
    db = get_db()

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS production (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            produced_count INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (item_id) REFERENCES inventory(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    # Seed default users
    admin_user = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if admin_user is None:
        db.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "admin"),
        )

    manager_user = db.execute("SELECT id FROM users WHERE username = ?", ("manager",)).fetchone()
    if manager_user is None:
        db.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("manager", generate_password_hash("manager123"), "manager"),
        )

    # Seed inventory if empty
    count = db.execute("SELECT COUNT(*) AS c FROM inventory").fetchone()["c"]
    if count == 0:
        db.execute("INSERT INTO inventory (item_name, quantity) VALUES (?, ?)", ("Steel Rod", 100))
        db.execute("INSERT INTO inventory (item_name, quantity) VALUES (?, ?)", ("Plastic Sheet", 250))
        db.execute("INSERT INTO inventory (item_name, quantity) VALUES (?, ?)", ("Copper Wire", 500))

    db.commit()


# -----------------------------
# Auth + Authorization helpers
# -----------------------------
@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please login first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Please login first.", "error")
                return redirect(url_for("login"))
            if g.user["role"] not in roles:
                flash("You are not authorized to access this page.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def log_action(user_id, action):
    db = get_db()
    db.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (user_id, action))
    db.commit()


# -----------------------------
# Public routes
# -----------------------------
@app.route("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("auth/register.html")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            flash("Username already exists.", "error")
            return render_template("auth/register.html")

        db.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), "staff"),
        )
        db.commit()
        flash("Registration successful. You can login now.", "success")
        return redirect(url_for("login"))

    return render_template("auth/register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user is None or not check_password_hash(user["password"], password):
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html")

        if user["role"] == "blocked":
            flash("Your account is blocked. Contact admin.", "error")
            return render_template("auth/login.html")

        session.clear()
        session["user_id"] = user["id"]
        flash("Login successful.", "success")
        return redirect(url_for("dashboard"))

    return render_template("auth/login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    if g.user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("inventory_list"))


# -----------------------------
# Inventory routes
# -----------------------------
@app.route("/inventory")
@login_required
@role_required("staff", "manager", "admin")
def inventory_list():
    items = get_db().execute("SELECT * FROM inventory ORDER BY id DESC").fetchall()
    return render_template("inventory/list.html", items=items)


@app.route("/inventory/update", methods=["GET", "POST"])
@login_required #checks whether youre logged in or not
@role_required("staff") #what type of user is logged in 
def inventory_update():
    db = get_db()

    if request.method == "POST":
        item_id = request.form.get("item_id", "").strip()
        quantity = request.form.get("quantity", "").strip()

        if not item_id or not quantity:
            flash("Item and quantity are required.", "error")
            items = db.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
            return render_template("inventory/update.html", items=items)

        try:
            quantity_int = int(quantity)
            if quantity_int < 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a non-negative number.", "error")
            items = db.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
            return render_template("inventory/update.html", items=items)

        item = db.execute("SELECT id FROM inventory WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            flash("Invalid inventory item.", "error")
            items = db.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
            return render_template("inventory/update.html", items=items)

        db.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (quantity_int, item_id))
        db.commit()

        log_action(g.user["id"], f"user {g.user['id']} updated stock of item {item_id} to {quantity_int}")
        flash("Stock updated successfully.", "success")
        return redirect(url_for("inventory_list"))

    items = db.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
    selected_item_id = request.args.get("item_id", "")
    return render_template("inventory/update.html", items=items, selected_item_id=selected_item_id)


# -----------------------------
# Production routes
# -----------------------------
@app.route("/production", methods=["GET", "POST"])
@login_required
@role_required("staff")
def production_entry():
    db = get_db()

    if request.method == "POST":
        item_id = request.form.get("item_id", "").strip()
        produced_count = request.form.get("produced_count", "").strip()

        if not item_id or not produced_count:
            flash("Item and produced count are required.", "error")
            items = db.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
            return render_template("inventory/update.html", items=items)

        try:
            count_int = int(produced_count)
            if count_int <= 0:
                raise ValueError
        except ValueError:
            flash("Produced count must be a positive number.", "error")
            items = db.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
            return render_template("inventory/update.html", items=items)

        item = db.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            flash("Invalid inventory item.", "error")
            items = db.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
            return render_template("inventory/update.html", items=items)

        db.execute(
            "INSERT INTO production (item_id, produced_count, user_id) VALUES (?, ?, ?)",
            (item_id, count_int, g.user["id"]),
        )

        new_quantity = item["quantity"] + count_int
        db.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_quantity, item_id))
        db.commit()

        log_action(g.user["id"], f"user {g.user['id']} recorded production for item {item_id} count {count_int}")
        flash("Production recorded successfully.", "success")
        return redirect(url_for("production_logs"))

    items = db.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
    return render_template("inventory/update.html", items=items)


@app.route("/production/logs")
@login_required
@role_required("staff", "manager", "admin")
def production_logs():
    rows = get_db().execute(
        """
        SELECT p.id, p.produced_count, i.item_name, u.username, p.user_id
        FROM production p
        JOIN inventory i ON p.item_id = i.id
        JOIN users u ON p.user_id = u.id
        ORDER BY p.id DESC
        """
    ).fetchall()
    return render_template("production/logs.html", records=rows)


# -----------------------------
# Admin routes
# -----------------------------
@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    db = get_db()
    user_count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    item_count = db.execute("SELECT COUNT(*) AS c FROM inventory").fetchone()["c"]
    production_count = db.execute("SELECT COUNT(*) AS c FROM production").fetchone()["c"]
    log_count = db.execute("SELECT COUNT(*) AS c FROM logs").fetchone()["c"]

    return render_template(
        "admin/dashboard.html",
        user_count=user_count,
        item_count=item_count,
        production_count=production_count,
        log_count=log_count,
    )


@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_users():
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        user_id = request.form.get("user_id", "").strip()

        if not user_id:
            flash("User not selected.", "error")
            return redirect(url_for("admin_users"))

        if str(g.user["id"]) == user_id:
            flash("You cannot modify your own account here.", "error")
            return redirect(url_for("admin_users"))

        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            flash("User not found.", "error")
            return redirect(url_for("admin_users"))

        if action == "block":
            db.execute("UPDATE users SET role = 'blocked' WHERE id = ?", (user_id,))
            db.commit()
            flash("User blocked.", "success")
            log_action(g.user["id"], f"admin {g.user['id']} blocked user {user_id}")

        elif action == "delete":
            db.execute("DELETE FROM production WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM logs WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.commit()
            flash("User deleted.", "success")
            log_action(g.user["id"], f"admin {g.user['id']} deleted user {user_id}")

        return redirect(url_for("admin_users"))

    users = db.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()
    return render_template("admin/users.html", users=users)


@app.route("/admin/inventory", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_inventory():
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        if action == "add":
            item_name = request.form.get("item_name", "").strip()
            quantity = request.form.get("quantity", "0").strip()

            if not item_name:
                flash("Item name is required.", "error")
                return redirect(url_for("admin_inventory"))

            try:
                quantity_int = int(quantity)
                if quantity_int < 0:
                    raise ValueError
            except ValueError:
                flash("Quantity must be non-negative.", "error")
                return redirect(url_for("admin_inventory"))

            db.execute(
                "INSERT INTO inventory (item_name, quantity) VALUES (?, ?)",
                (item_name, quantity_int),
            )
            db.commit()
            flash("Inventory item added.", "success")
            log_action(g.user["id"], f"admin {g.user['id']} added inventory item {item_name}")

        elif action == "update":
            item_id = request.form.get("item_id", "").strip()
            item_name = request.form.get("item_name", "").strip()
            quantity = request.form.get("quantity", "").strip()

            if not item_id or not item_name or not quantity:
                flash("All fields are required for update.", "error")
                return redirect(url_for("admin_inventory"))

            try:
                quantity_int = int(quantity)
                if quantity_int < 0:
                    raise ValueError
            except ValueError:
                flash("Quantity must be non-negative.", "error")
                return redirect(url_for("admin_inventory"))

            db.execute(
                "UPDATE inventory SET item_name = ?, quantity = ? WHERE id = ?",
                (item_name, quantity_int, item_id),
            )
            db.commit()
            flash("Inventory item updated.", "success")
            log_action(g.user["id"], f"admin {g.user['id']} updated inventory item {item_id}")

        elif action == "delete":
            item_id = request.form.get("item_id", "").strip()
            if not item_id:
                flash("Item not selected.", "error")
                return redirect(url_for("admin_inventory"))

            db.execute("DELETE FROM production WHERE item_id = ?", (item_id,))
            db.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
            db.commit()
            flash("Inventory item deleted.", "success")
            log_action(g.user["id"], f"admin {g.user['id']} deleted inventory item {item_id}")

        return redirect(url_for("admin_inventory"))

    items = db.execute("SELECT * FROM inventory ORDER BY id DESC").fetchall()
    return render_template("admin/inventory.html", items=items)


@app.route("/admin/logs")
@login_required
@role_required("admin")
def admin_logs():
    logs = get_db().execute(
        """
        SELECT l.id, l.action, l.timestamp, u.username
        FROM logs l
        JOIN users u ON l.user_id = u.id
        ORDER BY l.id DESC
        """
    ).fetchall()
    return render_template("production/logs.html", records=[], audit_logs=logs)


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
