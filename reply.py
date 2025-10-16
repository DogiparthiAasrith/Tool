import streamlit as st
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import datetime
import pandas as pd
import psycopg2
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os

# ===============================
# CONFIGURATION
# ===============================
SCOPES = ["https://www.googleapis.com/auth/calendar"]

try:
    client = OpenAI(api_key=st.secrets["openai"]["api_key"])
except Exception:
    client = OpenAI(api_key="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")

POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
EMAIL = "thridorbit03@gmail.com"
PASSWORD = "ouhc mftv huww liru"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993

OTHER_SERVICES_LINK = "https://www.morphius.in/services"
CREDENTIALS_FILE = "credentials.json"  # OAuth credentials file

# ===============================
# GOOGLE CALENDAR FUNCTIONS
# ===============================
def get_calendar_service():
    """Authenticate and return a Google Calendar API service instance."""
    creds = None
    token_file = "token.json"

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as token:
            token.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)
    return service

def create_calendar_event(service, attendee_email):
    """Create a Google Calendar event for a meeting."""
    event = {
        "summary": "Meeting with Interested Contact",
        "location": "Google Meet",
        "description": "Automatic meeting scheduled via Streamlit Reply Handler.",
        "start": {"dateTime": (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat() + "Z"},
        "end": {"dateTime": (datetime.datetime.utcnow() + datetime.timedelta(days=1, hours=1)).isoformat() + "Z"},
        "attendees": [{"email": attendee_email}],
        "conferenceData": {
            "createRequest": {"requestId": f"meet-{datetime.datetime.now().timestamp()}"}
        },
    }

    event = service.events().insert(calendarId="primary", body=event, conferenceDataVersion=1).execute()
    return event.get("hangoutLink", "(Meeting link unavailable)")

# ===============================
# DATABASE & EMAIL FUNCTIONS
# ===============================
def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ Database Error: {e}")
        return None

def setup_database_tables(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    event_type VARCHAR(50), recipient_email TEXT, subject TEXT,
                    body TEXT, status VARCHAR(50), interest_level VARCHAR(50), mail_id TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS unsubscribe_list (
                    id SERIAL PRIMARY KEY, email TEXT UNIQUE, reason TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()
    except Exception as e:
        st.error(f"❌ DB Setup Failed: {e}")
        conn.rollback()

def log_event_to_db(conn, event_type, email_addr, subject, status=None, interest_level=None, mail_id=None, body=None):
    try:
        sql = "INSERT INTO email_logs (event_type, recipient_email, subject, status, interest_level, mail_id, body) VALUES (%s,%s,%s,%s,%s,%s,%s)"
        with conn.cursor() as cur:
            cur.execute(sql, (event_type, email_addr, subject, status, interest_level, mail_id, body))
        conn.commit()
    except Exception as e:
        st.error(f"❌ DB Logging Failed: {e}")
        conn.rollback()

# ===============================
# EMAIL HANDLER
# ===============================
def check_interest_manually(email_body):
    body = email_body.lower()
    pos = ["interested", "schedule", "connect", "love to", "sounds good"]
    neg = ["not interested", "unsubscribe", "no thanks"]
    if any(k in body for k in pos): return "positive"
    if any(k in body for k in neg): return "negative"
    return "neutral"

def check_interest_with_openai(email_body):
    try:
        prompt = f"Classify this email reply as positive, negative, or neutral:\n\n{email_body}"
        res = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}], max_tokens=5)
        val = res.choices[0].message.content.strip().lower()
        return val if val in ["positive", "negative", "neutral"] else "neutral"
    except Exception as e:
        st.warning(f"OpenAI failed → Using fallback ({e})")
        return check_interest_manually(email_body)

def get_unread_emails():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        _, data = mail.search(None, "(UNSEEN)")
        unread_ids = data[0].split()
        emails = []
        for e_id in unread_ids:
            _, msg_data = mail.fetch(e_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            sender = email.utils.parseaddr(msg["From"])[1]
            subject = msg["Subject"]
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore")
            emails.append({"from": sender, "subject": subject, "body": body, "id": e_id.decode()})
        mail.logout()
        return emails
    except Exception as e:
        st.error(f"❌ Fetch Emails Error: {e}")
        return []

def send_reply(conn, to_email, subject, interest_level, mail_id, event_link=None):
    if interest_level == "positive":
        meeting_text = f"\nLet's meet using this Google Meet link: {event_link}" if event_link else ""
        body = f"""Hi,

Thank you for your interest! I'm glad you'd like to connect.{meeting_text}

Looking forward to our discussion.

Best regards,
Aasrith"""
    else:
        body = f"""Hi,

Thank you for replying. You can explore our other services here:
{OTHER_SERVICES_LINK}

Best regards,
Aasrith"""

    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, f"Re: {subject}"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        st.success(f"✅ Sent {interest_level} reply to {to_email}")
        log_event_to_db(conn, f"replied_{interest_level}", to_email, subject, "success", interest_level, mail_id, body)
    except Exception as e:
        st.error(f"❌ Reply Send Failed: {e}")

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("📧 Automated Email Reply Handler (with Google Calendar Integration)")
    conn = get_db_connection()
    if not conn:
        return
    setup_database_tables(conn)

    if st.button("Check Emails & Run Automations"):
        with st.spinner("Processing incoming emails..."):
            unread_emails = get_unread_emails()
            if unread_emails:
                calendar_service = get_calendar_service()
                for mail in unread_emails:
                    st.info(f"Processing reply from {mail['from']}")
                    interest = check_interest_with_openai(mail["body"])
                    event_link = None
                    if interest == "positive":
                        event_link = create_calendar_event(calendar_service, mail["from"])
                    send_reply(conn, mail["from"], mail["subject"], interest, mail["id"], event_link)
                st.success("✅ Finished processing all replies.")
            else:
                st.info("No new unread emails found.")
    conn.close()

if _name_ == "_main_":
    main()
