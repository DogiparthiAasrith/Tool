import streamlit as st
import imaplib, email, smtplib, datetime, os, re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ================================
# CONFIGURATION
# ================================
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

EMAIL = "thridorbit03@gmail.com"
PASSWORD = "ouhc mftv huww liru"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993

POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

WORK_START_HOUR = 10
WORK_END_HOUR = 18
OTHER_SERVICES_LINK = "https://www.morphius.in/services"

# OpenAI Client
try:
    client = OpenAI(api_key=st.secrets["openai"]["api_key"])
except Exception:
    client = OpenAI(api_key="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")

# ================================
# GOOGLE CALENDAR FUNCTIONS
# ================================
def get_calendar_service():
    """Authenticates Google Calendar API safely, avoiding crashes on servers."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                st.error(f"Google Token expired and could not be refreshed. Please re-authenticate locally. Error: {e}")
                return None
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                st.error(f"Missing `{CREDENTIALS_FILE}`. Please download it from Google Cloud Console.")
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                # This line will only work on a local machine to generate the token
                creds = flow.run_local_server(port=0)
            except Exception as e:
                st.error("Could not start local server for Google authentication. This is expected on a deployed server.")
                st.info("Please generate the `token.json` file by running this app on your local computer first, then upload it.")
                return None

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    try:
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        st.error(f"Failed to build Google Calendar service: {e}")
        return None

def get_next_free_slot(service):
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    end_time = now + datetime.timedelta(days=7)
    events_result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat() + "Z",
        timeMax=end_time.isoformat() + "Z",
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    events = events_result.get("items", [])

    busy_times = []
    for event in events:
        start_str = event["start"].get("dateTime")
        end_str = event["end"].get("dateTime")
        if start_str and end_str:
            busy_times.append((datetime.datetime.fromisoformat(start_str.replace("Z","+00:00")),
                               datetime.datetime.fromisoformat(end_str.replace("Z","+00:00"))))
    current_time = now
    while current_time < end_time:
        if WORK_START_HOUR <= current_time.hour < WORK_END_HOUR and current_time.weekday() < 5:
            slot_end = current_time + datetime.timedelta(hours=1)
            if not any(start < slot_end and end > current_time for start, end in busy_times):
                return current_time, slot_end
        current_time += datetime.timedelta(minutes=30)
    return None, None

def create_google_meet_event(service, attendee_email):
    start, end = get_next_free_slot(service)
    if not start: return None, None
    event_body = {
        "summary": f"Morphius AI Demo with {attendee_email}",
        "description": "A brief call to discuss potential collaboration and explore our AI solutions.",
        "start": {"dateTime": start.isoformat(), "timeZone":"Asia/Kolkata"},
        "end": {"dateTime": end.isoformat(), "timeZone":"Asia/Kolkata"},
        "attendees":[{"email":attendee_email},{"email":EMAIL}],
        "conferenceData":{"createRequest":{"requestId":f"morphius-meet-{datetime.datetime.now().timestamp()}"}}
    }
    created_event = service.events().insert(calendarId="primary", body=event_body, conferenceDataVersion=1).execute()
    return created_event.get("hangoutLink"), start

# ================================
# DATABASE FUNCTIONS
# ================================
def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ Database connection failed: {e}")
        return None

def setup_database_tables(conn):
    """
    Ensures the email_logs table exists and has ALL required columns.
    This prevents errors if the script is updated with new columns.
    """
    try:
        with conn.cursor() as cur:
            # Step 1: Create the base table if it doesn't exist.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    event_type VARCHAR(50),
                    recipient_email TEXT,
                    subject TEXT,
                    status VARCHAR(50)
                );
            """)

            # Step 2: Check for existing columns in the table.
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'email_logs';")
            existing_columns = [row[0] for row in cur.fetchall()]

            # Step 3: Define all columns the code expects to exist.
            columns_to_ensure = {
                "body": "TEXT",
                "interest_level": "VARCHAR(50)",
                "mail_id": "TEXT",
                "meeting_time": "TIMESTAMPTZ",
                "meet_link": "TEXT"
            }

            # Step 4: Add any missing columns.
            schema_updated = False
            for col_name, col_type in columns_to_ensure.items():
                if col_name not in existing_columns:
                    st.info(f"Schema mismatch detected. Adding column '{col_name}' to 'email_logs'...")
                    cur.execute(f"ALTER TABLE email_logs ADD COLUMN {col_name} {col_type};")
                    schema_updated = True
            
            if schema_updated:
                st.success("Database schema updated successfully.")

        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed during database setup: {e}")
        conn.rollback() # Rollback any partial changes on error

def log_event_to_db(conn, event_type, email_addr, subject, **kwargs):
    """Logs an event to the database, handling potential errors."""
    try:
        with conn.cursor() as cur:
            cols = ["event_type", "recipient_email", "subject"]
            vals = [event_type, email_addr, subject]
            for key, value in kwargs.items():
                cols.append(key)
                vals.append(value)
            
            placeholders = ",".join(["%s"] * len(vals))
            sql = f"INSERT INTO email_logs ({','.join(cols)}) VALUES ({placeholders})"
            cur.execute(sql, tuple(vals))
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to log event: {e}")
        conn.rollback()


# ================================
# EMAIL & AI FUNCTIONS
# ================================
def classify_interest_with_keywords(body):
    """Fallback classifier using keywords if the LLM fails."""
    body_lower = body.lower()
    positive_keywords = ["interested","let's connect","schedule","love to","sounds great","learn more","curious"]
    negative_keywords = ["not interested","unsubscribe","remove me","not a good fit","not right now","no thank you"]
    if any(keyword in body_lower for keyword in negative_keywords): return "negative"
    if any(keyword in body_lower for keyword in positive_keywords): return "positive"
    return "neutral"

def classify_email_interest(body):
    """Classifies email interest using OpenAI with a keyword-based fallback."""
    try:
        prompt = f"Analyze this email reply's intent. Respond with only one word: positive, negative, or neutral.\n\nEmail: \"{body}\""
        res = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0
        )
        sentiment = res.choices[0].message.content.strip().lower().replace('.', '')
        if sentiment in ["positive", "negative", "neutral"]:
            return sentiment
        # Fallback if LLM gives an unexpected response
        return classify_interest_with_keywords(body)
    except Exception as e:
        st.warning(f"⚠️ OpenAI API failed ({e}). Using keyword analysis as a fallback.")
        return classify_interest_with_keywords(body)

def get_unread_emails():
    """Fetches all unread emails from the inbox."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        _, data = mail.search(None, "(UNSEEN)")
        emails = []
        for e_id in data[0].split():
            _, msg_data = mail.fetch(e_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            sender = email.utils.parseaddr(msg["From"])[1]
            subject_header = email.header.decode_header(msg["Subject"])
            subject = subject_header[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode(subject_header[0][1] or 'utf-8', 'ignore')
            
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
        st.error(f"Failed to fetch emails: {e}")
        return []

def send_reply(conn, to_email, orig_subject, interest, mail_id):
    """Sends a reply based on the classified interest level."""
    subject = f"Re: {orig_subject}"
    meet_link, meet_time = None, None

    if interest == "positive":
        service = get_calendar_service()
        if not service:
            st.error(f"Cannot schedule meeting for {to_email} because Google Calendar is not authorized.")
            return
        
        meet_link, meet_time = create_google_meet_event(service, to_email)
        if not meet_link:
            st.error(f"Could not find an available meeting slot for {to_email}. No reply sent.")
            return
        
        body = f"Hi,\n\nThank you for your positive response! I'm glad you're interested.\n\nI've scheduled a brief call for us on {meet_time.strftime('%A, %d %B %Y at %I:%M %p IST')}.\n\nYou can join the Google Meet here: {meet_link}\n\nLooking forward to it.\n\nBest regards,\nAasrith"
    else: # Handles both "negative" and "neutral"
        body = f"Hi,\n\nThank you for your response. I understand.\n\nShould your needs change in the future, feel free to explore our other services here: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"

    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject
    msg.attach(MIMEText(body, "plain"))
    
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        
        log_event_to_db(conn, f"replied_{interest}", to_email, subject, status="success",
                        interest_level=interest, mail_id=mail_id, body=body,
                        meet_time=meet_time, meet_link=meet_link)
        st.success(f"Sent '{interest}' reply to {to_email}")
    except Exception as e:
        st.error(f"Failed to send reply to {to_email}: {e}")
        log_event_to_db(conn, f"replied_{interest}", to_email, subject, status="failed",
                        interest_level=interest, mail_id=mail_id)

# ================================
# MAIN APP
# ================================
def main():
    st.title("📧 Automated Reply Handler + Smart Scheduler")
    conn = get_db_connection()
    if not conn:
        return
    
    # This robust function now fixes the database table on every run
    setup_database_tables(conn)

    if st.button("Check Emails & Run Automations"):
        with st.spinner("Checking for new replies..."):
            unread_emails = get_unread_emails()
            if not unread_emails:
                st.info("No new unread replies found.")
                return

            st.write(f"Found {len(unread_emails)} new email(s). Processing now...")
            for mail in unread_emails:
                log_event_to_db(conn, "received", mail["from"], mail["subject"], body=mail["body"], mail_id=mail["id"])
                interest = classify_email_interest(mail["body"])
                st.write(f"→ From: {mail['from']} | Subject: '{mail['subject']}' | Detected Interest: **{interest.capitalize()}**")
                send_reply(conn, mail["from"], mail["subject"], interest, mail["id"])
            st.success("✅ Finished processing all new replies.")
    
    if conn:
        conn.close()

if __name__ == "__main__":
    main()
