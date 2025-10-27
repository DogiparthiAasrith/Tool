from flask import Flask, request, Response
from pymongo import MongoClient
import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

# Initialize Flask App and MongoDB Client
app = Flask(__name__)
try:
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    print("✅ Successfully connected to MongoDB.")
except Exception as e:
    print(f"❌ Could not connect to MongoDB. Error: {e}")
    db = None

# This is the content of a 1x1 transparent GIF
PIXEL_GIF_CONTENT = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'

# ===============================
# TRACKING ENDPOINT
# ===============================
@app.route('/track')
def track_open():
    """
    This endpoint is hit when an email client loads the tracking pixel.
    It logs the 'email_opened' event to the database.
    """
    tracking_id = request.args.get('id') # Get the unique ID from the URL

    if tracking_id and db:
        try:
            # Log the event to the same email_logs collection your dashboard uses
            db.email_logs.insert_one({
                "tracking_id": tracking_id,
                "event_type": "email_opened",
                "timestamp": datetime.datetime.utcnow(),
                "user_agent": request.headers.get('User-Agent')
            })
            print(f"Logged open for tracking_id: {tracking_id}")
        except Exception as e:
            print(f"Error logging to DB: {e}")

    # Return the 1x1 pixel image as the response
    return Response(PIXEL_GIF_CONTENT, mimetype='image/gif')

# ===============================
# RUN THE SERVER
# ===============================
if __name__ == '__main__':
    # You can run this with a proper WSGI server like Gunicorn in production
    app.run(host='0.0.0.0', port=5001)
