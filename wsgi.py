from wms import app  # pragma: no cover

if __name__ == "__main__":
    app.run()

# Example Usage:
# gunicorn --bind 127.0.0.1:8000 wsgi:app
