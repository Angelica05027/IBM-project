from flask import Flask

def create_app():
    app = Flask(__name__)

    # -------------------------
    # 🔧 Configuration
    # -------------------------
    #app.config.from_object("config.Config")

    # -------------------------
    # 🗄️ Database setup
    # -------------------------
    

    # -------------------------
    # 📦 Register Blueprints
    # -------------------------
    try:
        from routes.auth import auth
        app.register_blueprint(auth)
    except ImportError:
        print("auth module not found")

    try:
        from routes.admin import admin
        app.register_blueprint(admin)
    except ImportError:
        print("admin module not found")

    try:
        from routes.shop import shop
        app.register_blueprint(shop)
    except ImportError:
        print("shop module not found")

    # -------------------------
    # 🏠 Default route
    # -------------------------
    @app.route("/")
    def home():
        return "Flask App Running 🚀"

    # -------------------------
    # ❌ Error Handlers
    # -------------------------
    @app.errorhandler(404)
    def not_found(e):
        return "404 Not Found", 404

    @app.errorhandler(500)
    def server_error(e):
        return "500 Internal Server Error", 500

    return app


# -------------------------
# ▶️ Run App
# -------------------------
if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)