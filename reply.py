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
import re

# ===============================
# CONFIGURATION
# ===============================
# --- OpenAI API Configuration ---
try:
    client = OpenAI(api_key=st.secrets["openai"]["api_key"])
except Exception:
    client = OpenAI(api_key="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")

# --- Database & Email Credentials ---
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
EMAIL = "thridorbit03@gmail.com"
PASSWORD = "ouhc mftv huww liru"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993

# --- Google Calendar Config ---
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = "credentials.json"
WORK_START_HOUR = 10  # 10 AM
WORK_END_HOUR = 18    # 6 PM

OTHER_SERVICES_LINK = "https://www.morphius.in/services"

# ===============================
# GOOGLE CALENDAR FUNCTIONS
# ===============================
def get_calendar_service():
    """Authenticate and return a Google Calendar API service instance."""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if not os.path.exists(CREDENTIALS_FILE):
            st.error("❌ Google Calendar `credentials.json` not found. Cannot schedule meetings.")
            return None
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def get_next_free_slot(service):
    """Find next available 1-hour slot in working hours."""
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)  # IST
    end_time = now + datetime.timedelta(days=3)
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat() + "Z",
            timeMax=end_time.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = events_result.get("items", [])
    busy_times = []
    for event in events:
        start = event["start"].get("dateTime")
        end = event["end"].get("dateTime")
        if start and end: # Only process events with specific times
            busy_times.append(
                (
                    datetime.datetime.fromisoformat(start.replace("Z", "+00:00")),
                    datetime.datetime.fromisoformat(end.replace("Z", "+00:00")),
                )
            )
    current = now
    while current < end_time:
        if WORK_START_HOUR <= current.hour < WORK_END_HOUR and current.weekday() < 5:  # Monday to Friday
            slot_end = current + datetime.timedelta(hours=1)
            overlap = any(s < slot_end and e > current for s, e in busy_times)
            if not overlap:
                return current, slot_end
        current += datetime.timedelta(minutes=30)
    return None, None

def create_google_meet_event(service, attendee_email):
    """Creates a Google Meet event in the next available slot."""
    start, end = get_next_free_slot(service)
    if not start:
        return None, None
    event = {
        "summary": f"Meeting with {attendee_email}",
        "location": "Google Meet",
        "description": "Automated meeting scheduled via AI Email Handler.",
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
        "attendees": [{"email": attendee_email}, {"email": EMAIL}],
        "conferenceData": {"createRequest": {"requestId": f"meet-{datetime.datetime.now().timestamp()}"}},
    }
    event = service.events().insert(calendarId="primary", body=event, conferenceDataVersion=1).execute()
    return event.get("hangoutLink"), start

# ===============================
# DATABASE FUNCTIONS
# ===============================
def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ Database Connection Error: {e}")
        return None

def setup_database_tables(conn):
    """
    FIXED: Ensures the 'email_logs' table exists and has ALL required columns.
    This is now robust and adds any missing columns to prevent runtime errors.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    event_type VARCHAR(50),
                    recipient_email TEXT,
                    subject TEXT,
                    status VARCHAR(50)
                );
            """)
            
            columns_to_add = {
                "body": "TEXT",
                "interest_level": "VARCHAR(50)",
                "mail_id": "TEXT",
                "meeting_time": "TIMESTAMP",
                "meet_link": "TEXT"
            }
            
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='email_logs';")
            existing_columns = [row[0] for row in cur.fetchall()]
            
            for col, col_type in columns_to_add.items():
                if col not in existing_columns:
                    cur.execute(f"ALTER TABLE email_logs ADD COLUMN {col} {col_type};")
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS unsubscribe_list (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to setup database tables: {e}")
        conn.rollback()


def log_event_to_db(conn, event_type, email_addr, subject, status=None, interest_level=None, mail_id=None, body=None, meet_time=None, meet_link=None):
    """FIXED: This function now correctly maps to the full schema."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO email_logs (event_type, recipient_email, subject, status, interest_level, mail_id, body, meeting_time, meet_link) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (event_type, email_addr, subject, status, interest_level, mail_id, body, meet_time, meet_link),
            )
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to log event: {e}")
        conn.rollback()

# ===============================
# AI & EMAIL FUNCTIONS
# ===============================

def classify_interest_with_keywords(email_body):
    """Fallback function to classify email interest using keywords."""
    body_lower = email_body.lower()
    positive_keywords = ["interested", "let's connect", "schedule a call", "sounds good", "like to know more", "tell me more"]
    negative_keywords = ["not interested", "unsubscribe", "remove me", "not a good fit", "not right now"]
    
    if any(re.search(r'\b' + keyword + r'\b', body_lower) for keyword in positive_keywords):
        return "positive"
    if any(re.search(r'\b' + keyword + r'\b', body_lower) for keyword in negative_keywords):
        return "negative"
    
    return "neutral"

def classify_email_interest(email_body):
    """
    NEW: Tries to classify email body using OpenAI. If it fails, it uses a keyword-based fallback.
    """
    try:
        prompt = f"Analyze the sentiment of this email reply. Respond only with: positive, negative, or neutral.\n\nEmail: \"{email_body}\""
        res = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}], max_tokens=10, temperature=0)
        sentiment = res.choices[0].message.content.strip().lower().replace('.', '')
        if sentiment in ["positive", "negative", "neutral"]:
            return sentiment
        # If the LLM returns something unexpected, fall back to keywords
        st.warning("LLM returned an unexpected value. Falling back to keyword analysis.")
        return classify_interest_with_keywords(email_body)
    except Exception as e:
        st.warning(f"⚠️ OpenAI API failed ({e}). Using keyword-based analysis as a fallback.")
        return classify_interest_with_keywords(email_body)

def get_unread_emails():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
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
        st.error(f"❌ Failed to fetch emails: {e}")
        return []

def send_reply(conn, to_email, original_subject, interest_level, mail_id):
    """
    UPDATED: Sends personalized reply.
    - Positive: Schedules Meet and sends link.
    - Negative/Neutral: Sends a polite message with a link to other services.
    """
    service = get_calendar_service()
    if not service and interest_level == "positive":
        st.error(f"Could not send meeting link to {to_email} because Google Calendar service is unavailable.")
        return

    meet_link, meet_time = (None, None)
    subject = f"Re: {original_subject}"

    if interest_level == "positive":
        meet_link, meet_time = create_google_meet_event(service, to_email)
        if not meet_link:
            st.error(f"Failed to find an available meeting slot for {to_email}. No reply sent.")
            return
            
        body = f"""Hi,

Thank you for your positive response! I'm glad to hear you're interested.

I've scheduled a Google Meet for you on {meet_time.strftime('%A, %d %B %Y at %I:%M %p IST')}.

Join using this link: {meet_link}

Looking forward to our conversation.

Best regards,
Aasrith
"""
    elif interest_level in ["negative", "neutral"]:
        if interest_level == "negative":
            body = f"""Hi,

Thank you for getting back to me. I understand completely.
"""
        else: # Neutral
             body = f"""Hi,

Thanks for your reply.
"""
        body += f"""
If your needs change in the future, you can explore our other services here:
{OTHER_SERVICES_LINK}

Best regards,
Aasrith
"""
    else:
        # This case should not be reached.
        return

    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        log_event_to_db(conn, f"replied_{interest_level}", to_email, subject, "success", interest_level, mail_id, body, meet_time, meet_link)
        st.success(f"✅ Sent '{interest_level}' reply to {to_email}")
    except Exception as e:
        st.error(f"❌ Failed to send reply to {to_email}: {e}")
        log_event_to_db(conn, f"replied_{interest_level}", to_email, subject, "failed", interest_level, mail_id, body, meet_time, meet_link)

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("📧 Automated Reply Handler + Smart Scheduler")

    conn = get_db_connection()
    if not conn:
        return
    # This now fixes the database table on every run.
    setup_database_tables(conn)

    if st.button("Check Emails & Run Automations"):
        with st.spinner("Processing incoming emails..."):
            unread_emails = get_unread_emails()
            if unread_emails:
                st.write(f"Found {len(unread_emails)} new email(s).")
                for mail in unread_emails:
                    log_event_to_db(conn, "received", mail["from"], mail["subject"], mail_id=mail["id"], body=mail["body"])
                    interest = classify_email_interest(mail["body"])
                    st.write(f"→ From: {mail['from']} | Subject: '{mail['subject']}' | Detected Interest: **{interest.capitalize()}**")
                    if interest in ["positive", "negative", "neutral"]:
                        send_reply(conn, mail["from"], mail["subject"], interest, mail["id"])
                    else:
                        st.info(f"No action defined for '{interest}' email from {mail['from']}.")
                st.success("✅ Finished processing new replies.")
            else:
                st.info("No new unread replies found.")

    conn.close()

if __name__ == "__main__":
    main()
