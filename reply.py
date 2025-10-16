import streamlit as st
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import datetime
import psycopg2
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import re

# ===============================
# CONFIGURATION
# ===============================
# --- OpenAI API Configuration ---
try:
    # Recommended: Use Streamlit secrets for your API key in deployment
    client = OpenAI(api_key=st.secrets["openai"]["api_key"])
except Exception:
    # Fallback for local development if secrets aren't set
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
TOKEN_FILE = "token.json"
WORK_START_HOUR = 10  # 10 AM
WORK_END_HOUR = 18    # 6 PM

OTHER_SERVICES_LINK = "https://www.morphius.in/services"

# ===============================
# GOOGLE CALENDAR FUNCTIONS
# ===============================

def get_calendar_service():
    """
    CRITICAL FIX: Authenticates Google Calendar API safely for server environments.
    It avoids the `webbrowser` crash by NOT trying to open a browser.
    - On your LOCAL machine: It will open a browser ONCE to create 'token.json'.
    - On the SERVER (Streamlit Cloud): It relies on the pre-existing 'token.json'.
    You MUST run this app locally first to generate 'token.json' and then upload it.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # If there are no (valid) credentials available, handle it gracefully.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                st.error(f"❌ Failed to refresh Google token. You may need to re-authenticate locally. Error: {e}")
                return None
        else:
            # This block now prevents the app from crashing on a server.
            st.error("❌ Google Calendar token (`token.json`) is missing or invalid.")
            st.info("INSTRUCTIONS: To fix this, please run this application on your local computer once. A browser window will open for you to log in and authorize the app. This will create a 'token.json' file. You must then upload this file to your Streamlit project.")
            return None # Exit function gracefully

        # Save the credentials for the next run
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    try:
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        st.error(f"❌ Failed to build Google Calendar service: {e}")
        return None

def get_next_free_slot(service):
    """Find next available 1-hour slot in working hours."""
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)  # IST
    end_time = now + datetime.timedelta(days=7) # Look a week ahead
    events_result = service.events().list(
        calendarId="primary", timeMin=now.isoformat() + "Z", timeMax=end_time.isoformat() + "Z",
        singleEvents=True, orderBy="startTime"
    ).execute()
    events = events_result.get("items", [])
    
    busy_times = []
    for event in events:
        start_str = event["start"].get("dateTime")
        end_str = event["end"].get("dateTime")
        if start_str and end_str:
            busy_times.append((
                datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00")),
                datetime.datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            ))

    current_time = now
    while current_time < end_time:
        if WORK_START_HOUR <= current_time.hour < WORK_END_HOUR and current_time.weekday() < 5:
            slot_end = current_time + datetime.timedelta(hours=1)
            is_overlap = any(start < slot_end and end > current_time for start, end in busy_times)
            if not is_overlap:
                return current_time, slot_end
        current_time += datetime.timedelta(minutes=30)
    return None, None

def create_google_meet_event(service, attendee_email):
    """Creates a Google Meet event in the next available slot."""
    start, end = get_next_free_slot(service)
    if not start:
        return None, None
    event_body = {
        "summary": f"Morphius AI Demo with {attendee_email}",
        "description": "A brief call to discuss potential collaboration and explore our AI solutions.",
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
        "attendees": [{"email": attendee_email}, {"email": EMAIL}],
        "conferenceData": {"createRequest": {"requestId": f"morphius-meet-{datetime.datetime.now().timestamp()}"}},
    }
    created_event = service.events().insert(calendarId="primary", body=event_body, conferenceDataVersion=1).execute()
    return created_event.get("hangoutLink"), start

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
    """Ensures the 'email_logs' table exists and has all required columns."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    event_type VARCHAR(50), recipient_email TEXT, subject TEXT, status VARCHAR(50)
                );
            """)
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='email_logs';")
            existing_columns = [row[0] for row in cur.fetchall()]
            
            columns_to_ensure = {
                "body": "TEXT", "interest_level": "VARCHAR(50)", "mail_id": "TEXT",
                "meeting_time": "TIMESTAMP WITH TIME ZONE", "meet_link": "TEXT"
            }
            for col, col_type in columns_to_ensure.items():
                if col not in existing_columns:
                    cur.execute(f"ALTER TABLE email_logs ADD COLUMN {col} {col_type};")
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to setup database tables: {e}")
        conn.rollback()

def log_event_to_db(conn, event_type, email_addr, subject, **kwargs):
    """Logs an event to the database using keyword arguments for flexibility."""
    try:
        with conn.cursor() as cur:
            # Base columns
            cols = ["event_type", "recipient_email", "subject"]
            vals = [event_type, email_addr, subject]
            
            # Add optional columns from kwargs
            for key, value in kwargs.items():
                cols.append(key)
                vals.append(value)
            
            placeholders = ", ".join(["%s"] * len(vals))
            sql = f"INSERT INTO email_logs ({', '.join(cols)}) VALUES ({placeholders})"
            
            cur.execute(sql, tuple(vals))
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to log event: {e}")
        conn.rollback()

# ===============================
# AI & EMAIL FUNCTIONS
# ===============================
def classify_interest_with_keywords(email_body):
    """
    UPDATED: Hardcoded fallback using your specified keywords.
    """
    body_lower = email_body.lower()
    positive_keywords = ["interested", "let's connect", "schedule", "love to", "sounds great", "learn more", "curious"]
    negative_keywords = ["not interested", "unsubscribe", "remove me", "not a good fit", "not right now", "no thank you"]

    if any(keyword in body_lower for keyword in negative_keywords):
        return "negative"
    if any(keyword in body_lower for keyword in positive_keywords):
        return "positive"
    
    return "neutral"

def classify_email_interest(email_body):
    """Tries to classify email using OpenAI, but falls back to hardcoded keywords on any failure."""
    try:
        prompt = f"Analyze this email reply's intent. Is the sender interested in a meeting? Respond with only one word: positive, negative, or neutral.\n\nEmail: \"{email_body}\""
        res = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}], max_tokens=5, temperature=0)
        sentiment = res.choices[0].message.content.strip().lower().replace('.', '')
        if sentiment in ["positive", "negative", "neutral"]:
            return sentiment
        return classify_interest_with_keywords(email_body) # Fallback if LLM gives weird response
    except Exception as e:
        st.warning(f"⚠️ OpenAI API failed ({e}). Using hardcoded keyword analysis as a fallback.")
        return classify_interest_with_keywords(email_body)

def get_unread_emails():
    """Fetches all unread emails from the inbox."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        _, data = mail.search(None, "(UNSEEN)")
        email_ids = data[0].split()
        emails = []
        for e_id in email_ids:
            _, msg_data = mail.fetch(e_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            sender = email.utils.parseaddr(msg["From"])[1]
            subject = email.header.decode_header(msg["Subject"])[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            
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
    """Sends a reply based on the classified interest level."""
    subject = f"Re: {original_subject}"
    body = ""
    meet_link, meet_time = None, None

    if interest_level == "positive":
        service = get_calendar_service()
        if not service:
            st.error(f"Cannot schedule meeting for {to_email} because Google Calendar is not authorized.")
            return # Stop execution for this email
        
        meet_link, meet_time = create_google_meet_event(service, to_email)
        if not meet_link:
            st.error(f"Could not find an available meeting slot for {to_email}. No reply sent.")
            return

        body = f"""Hi,

Thank you for your positive response! I'm glad to hear you're interested.

I've scheduled a Google Meet for us on {meet_time.strftime('%A, %d %B %Y at %I:%M %p IST')}.

You can join using this link: {meet_link}

Looking forward to our conversation.

Best regards,
Aasrith
"""
    elif interest_level in ["negative", "neutral"]:
        greeting = "Thank you for getting back to me."
        if interest_level == "negative":
            greeting += " I understand completely."

        body = f"""Hi,

{greeting}

Should your needs change in the future, feel free to explore our other services here:
{OTHER_SERVICES_LINK}

Best regards,
Aasrith
"""
    else:
        return # Do nothing for unhandled interest levels

    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        
        log_event_to_db(conn, f"replied_{interest_level}", to_email, subject, status="success", 
                        interest_level=interest_level, mail_id=mail_id, body=body, 
                        meet_time=meet_time, meet_link=meet_link)
        st.success(f"✅ Sent '{interest_level}' reply to {to_email}")
    except Exception as e:
        st.error(f"❌ Failed to send reply to {to_email}: {e}")
        log_event_to_db(conn, f"replied_{interest_level}", to_email, subject, status="failed", interest_level=interest_level, mail_id=mail_id)

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("📧 Automated Reply Handler + Smart Scheduler")

    conn = get_db_connection()
    if not conn:
        return
    setup_database_tables(conn)

    if st.button("Check Emails & Run Automations"):
        with st.spinner("Checking for new replies..."):
            unread_emails = get_unread_emails()
            if not unread_emails:
                st.info("No new unread replies found.")
                return

            st.write(f"Found {len(unread_emails)} new email(s). Processing now...")
            for mail in unread_emails:
                # Log the received email first
                log_event_to_db(conn, "received", mail["from"], mail["subject"], body=mail["body"], mail_id=mail["id"])
                
                # Classify and reply
                interest = classify_email_interest(mail["body"])
                st.write(f"→ From: {mail['from']} | Subject: '{mail['subject']}' | Detected Interest: **{interest.capitalize()}**")
                send_reply(conn, mail["from"], mail["subject"], interest, mail["id"])
            st.success("✅ Finished processing all new replies.")

    conn.close()

if __name__ == "__main__":
    main()
