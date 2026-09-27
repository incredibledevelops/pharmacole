import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5005")),
        debug=app.config.get("DEBUG", False),
        use_reloader=os.getenv("FLASK_USE_RELOADER", "0") == "1",
    )