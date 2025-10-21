import streamlit as st
import smtplib
import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

# ===============================
# HELPER FUNCTIONS
# ===============================

def get_db_connection():
    """Establishes connection to the MongoDB database."""
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None, None

def log_event_to_db(db, event_type, email_addr, subject, body, status):
    """Inserts an email event document into the 'email_logs' collection."""
    try:
        log_entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "event_type": event_type,
            "recipient_email": email_addr,
            "subject": subject,
            "body": body,
            "status": status
        }
        db.email_logs.insert_one(log_entry)
    except Exception as e:
        st.error(f"❌ Failed to log event to database: {e}")

def send_email_smtp(db, to_email, subject, body):
    """Connects to the SMTP server, sends the email, and logs the event to the database."""
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        
        # --- CRITICAL FIX ---
        # Log the first email with a specific, unique event type.
        log_event_to_db(db, "initial_outreach", to_email, subject, body, "success")
        return True
    except Exception as e:
        st.error(f"❌ Failed to send to {to_email}: {e}")
        log_event_to_db(db, "initial_outreach", to_email, subject, body, "failed")
        return False

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("Email Preview & Send")

    if 'edited_emails' not in st.session_state or not st.session_state.edited_emails:
        st.info("📧 Please generate and edit some email drafts on the 'Generate & Edit Emails' page first.")
        return

    st.header("Final Review")
    st.info("This is a read-only preview of the emails that will be sent. Review them carefully.")

    for email in st.session_state.edited_emails:
        st.markdown("---")
        st.markdown(f"**To:** {email['name']} <{email['to_email']}>")
        st.markdown(f"**Subject:** {email['subject']}")
        st.text_area("Body Preview", value=email['body'], height=200, disabled=True, key=f"preview_{email['id']}")
    
    st.markdown("---")
    
    if st.button(f"🚀 Send {len(st.session_state.edited_emails)} Emails Now", type="primary"):
        client, db = get_db_connection()
        if not client:
            st.error("Cannot send emails without a database connection for logging.")
            return
        
        success_count = 0
        progress_bar = st.progress(0, text="Initializing...")
        
        for i, email_to_send in enumerate(st.session_state.edited_emails):
            progress_text = f"Sending email {i+1}/{len(st.session_state.edited_emails)} to {email_to_send['to_email']}..."
            progress_bar.progress((i + 1) / len(st.session_state.edited_emails), text=progress_text)
            if send_email_smtp(db, email_to_send['to_email'], email_to_send['subject'], email_to_send['body']):
                success_count += 1
        
        client.close()
        st.success(f"Campaign complete! Sent {success_count} out of {len(st.session_state.edited_emails)} emails. Full details logged to the database.")
        st.session_state.edited_emails = []
        st.rerun()

if __name__ == "__main__":
    main()
