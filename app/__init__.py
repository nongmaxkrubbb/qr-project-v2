import logging
import sys

from flask import Flask, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')

    # ProxyFix เพื่อให้ Flask รองรับ URL สาธารณะเวลาใช้ Nginx/Cloudflare/Load balancer
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    app.config.from_object('config.Config')

    # ----- Structured logging ไป stdout (ให้ log aggregator เช่น CloudWatch/Datadog เก็บได้) -----
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        '{"time":"%(asctime)s","level":"%(levelname)s","module":"%(name)s","msg":"%(message)s"}'
    ))
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)

    # ----- CSRF protection สำหรับทุกฟอร์ม (login, get_ticket, call_next, complete, skip, logout) -----
    CSRFProtect(app)

    # ----- Rate limiting: กัน brute-force ที่หน้า login และกันสแปมกดรับบัตรคิว -----
    limiter.init_app(app)
    app.config["RATELIMIT_HEADERS_ENABLED"] = True

    from app.database import init_app as init_db_app
    init_db_app(app)

    from app.routes.user_routes import user_bp
    from app.routes.admin_routes import admin_bp

    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)

    # rate limit เฉพาะจุดเสี่ยง (ไม่ครอบทั้งแอปเพื่อไม่ให้หน้าติดตามคิว polling ทุก 5 วิ โดนบล็อก)
    limiter.limit("10 per minute")(admin_bp)
    limiter.limit("20 per minute")(user_bp)

    @app.route("/healthz")
    def healthz():
        """สำหรับ load balancer / uptime monitor เช็คว่าแอปยังตอบสนองอยู่"""
        return jsonify({"status": "ok"})

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": "internal server error"}), 500

    return app
