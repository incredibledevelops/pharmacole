from flask import render_template, request, jsonify


def register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(e):
        return _render(403, "errors/403.html", "Forbidden", "You don't have permission to view this.")

    @app.errorhandler(404)
    def not_found(e):
        return _render(404, "errors/404.html", "Page not found", "We couldn't find that page.")

    @app.errorhandler(429)
    def rate_limited(e):
        return _render(429, "errors/429.html", "Too many requests", "Please slow down and try again shortly.")

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Unhandled 500")
        return _render(500, "errors/500.html", "Something went wrong", "Something went wrong. Please try again.")

    @app.errorhandler(413)
    def too_large(e):
        return _render(413, "errors/500.html", "File too large", "The file you tried to upload is too large.")


def _render(code, template, title, message):
    from flask import current_app
    if _wants_json():
        return jsonify({"error": message}), code
    try:
        return render_template(template, title=title, message=message), code
    except Exception:
        # Fallback if template is missing
        return f"<h1>{code} · {title}</h1><p>{message}</p>", code


def _wants_json():
    accept = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    if request.path.startswith("/payments/") and request.method == "POST":
        return True
    return False