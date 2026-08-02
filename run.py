from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Dev only. Production: gunicorn -w 4 -b 0.0.0.0:8000 run:app
    app.run(debug=False, host="0.0.0.0", port=5000)
