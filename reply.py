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
# CORRECTED: Ensure Drive scope is included for app-wide authentication
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

EMAIL = "thridorbit03@gmail.com"
PASSWORD = "ouhc mftv huww liru"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993

POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
# ... (the rest of the file remains unchanged)
# The get_calendar_service function will now use the updated SCOPES
# when it creates a token for the first time.
# ================================
# GOOGLE CALENDAR FUNCTIONS
# ================================
def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                st.error(f"Google Token expired and could not be refreshed. Error: {e}")
                return None
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                st.error(f"Missing `{CREDENTIALS_FILE}`.")
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                st.error("Could not start local server for Google authentication.")
                st.info("Please generate `token.json` by running locally first.")
                return None
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    try:
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        st.error(f"Failed to build Google Calendar service: {e}")
        return None
# ... (rest of the file is the same as before)
def get_next_free_slot(service):
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    end_time = now + datetime.timedelta(days=7)
    events_result = service.events().list(
        calendarId="primary", timeMin=now.isoformat() + "Z", timeMax=end_time.isoformat() + "Z",
        singleEvents=True, orderBy="startTime"
    ).execute()
    events = events_result.get("items", [])
    busy_times = []
    for event in events:
        start_str, end_str = event["start"].get("dateTime"), event["end"].get("dateTime")
        if start_str and end_str:
            busy_times.append((datetime.datetime.fromisoformat(start_str.replace("Z","+00:00")),
                               datetime.datetime.fromisoformat(end_str.replace("Z","+00:00"))))
    current_time = now
    while current_time < end_time:
        if 10 <= current_time.hour < 18 and current_time.weekday() < 5:
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

def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ Database connection failed: {e}")
        return None
def setup_database_tables(conn):
    """Ensures the email_logs table exists and has ALL required columns."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    event_type VARCHAR(50), recipient_email TEXT, subject TEXT, status VARCHAR(50)
                );
            """)
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'email_logs';")
            existing_columns = [row[0] for row in cur.fetchall()]
            columns_to_ensure = {
                "body": "TEXT", "interest_level": "VARCHAR(50)", "mail_id": "TEXT",
                "meeting_time": "TIMESTAMPTZ", "meet_link": "TEXT"
            }
            for col_name, col_type in columns_to_ensure.items():
                if col_name not in existing_columns:
                    st.info(f"Schema mismatch detected. Adding column '{col_name}'...")
                    cur.execute(f"ALTER TABLE email_logs ADD COLUMN {col_name} {col_type};")
                    st.success(f"Column '{col_name}' added successfully.")
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed during database setup: {e}")
        conn.rollback()

def log_event_to_db(conn, event_type, email_addr, subject, status, body=None, interest_level=None, mail_id=None, meeting_time=None, meet_link=None):
    """
    (CORRECTED) Inserts a complete event record, using NULL for any missing optional values.
    This function is now robust and matches the database schema exactly.
    """
    try:
        sql = """
            INSERT INTO email_logs (
                event_type, recipient_email, subject, status, body, 
                interest_level, mail_id, meeting_time, meet_link
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """
        with conn.cursor() as cur:
            cur.execute(sql, (
                event_type, email_addr, subject, status, body, 
                interest_level, mail_id, meeting_time, meet_link
            ))
        conn.commit()
    except psycopg2.Error as e:
        st.error(f"❌ Failed to log event to database: {e}")
        conn.rollback()

# ================================
# EMAIL & AI FUNCTIONS
# ================================
def classify_interest_with_keywords(body):
    body_lower = body.lower()
    positive_keywords = ["interested","let's connect","schedule","love to","sounds great","learn more","curious"]
    negative_keywords = ["not interested","unsubscribe","remove me","not a good fit","not right now","no thank you"]
    if any(keyword in body_lower for keyword in negative_keywords): return "negative"
    if any(keyword in body_lower for keyword in positive_keywords): return "positive"
    return "neutral"

def classify_email_interest(body):
    try:
        prompt = f"Analyze this email reply's intent. Respond with only one word: positive, negative, or neutral.\n\nEmail: \"{body}\""
        res = client.chat.completions.create(
            model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}],
            max_tokens=5, temperature=0
        )
        sentiment = res.choices[0].message.content.strip().lower().replace('.', '')
        return sentiment if sentiment in ["positive", "negative", "neutral"] else classify_interest_with_keywords(body)
    except Exception as e:
        st.warning(f"⚠️ OpenAI API failed ({e}). Using keyword analysis as a fallback.")
        return classify_interest_with_keywords(body)

def get_unread_emails():
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
            subject = "".join(str(s, c or 'utf-8') if isinstance(s, bytes) else s for s, c in email.header.decode_header(msg["Subject"]))
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else: body = msg.get_payload(decode=True).decode(errors="ignore")
            emails.append({"from": sender, "subject": subject, "body": body, "id": e_id.decode()})
        mail.logout()
        return emails
    except Exception as e:
        st.error(f"Failed to fetch emails: {e}")
        return []

def send_reply(conn, to_email, orig_subject, interest, mail_id):
    subject = f"Re: {orig_subject}"
    meet_link, meeting_time = None, None
    try:
        if interest == "positive":
            service = get_calendar_service()
            if not service:
                st.error(f"Cannot schedule for {to_email}: Google Calendar not authorized.")
                return
            meet_link, meeting_time = create_google_meet_event(service, to_email)
            if not meet_link:
                st.error(f"Could not find a meeting slot for {to_email}. No reply sent.")
                return
            body = (f"Hi,\n\nThank you for your positive response! I'm glad you're interested.\n\n"
                    f"I've scheduled a brief call for us on {meeting_time.strftime('%A, %d %B %Y at %I:%M %p IST')}.\n\n"
                    f"You can join the Google Meet here: {meet_link}\n\nLooking forward to it.\n\nBest regards,\nAasrith")
        else:
            body = (f"Hi,\n\nThank you for your response. I understand.\n\n"
                    f"Should your needs change, feel free to explore our other services: {OTHER_SERVICES_LINK}\n\n"
                    f"Best regards,\nAasrith")
        
        msg = MIMEMultipart()
        msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        
        log_event_to_db(conn, f"replied_{interest}", to_email, subject, "success", body=body,
                        interest_level=interest, mail_id=mail_id, meeting_time=meeting_time, meet_link=meet_link)
        st.success(f"Sent '{interest}' reply to {to_email}")
    except Exception as e:
        st.error(f"Failed to send reply to {to_email}: {e}")
        log_event_to_db(conn, f"replied_{interest}", to_email, subject, "failed",
                        interest_level=interest, mail_id=mail_id)

# ================================
# MAIN APP
# ================================
def main():
    st.title("📧 Automated Reply Handler + Smart Scheduler")
    conn = get_db_connection()
    if not conn: return
    
    setup_database_tables(conn)

    if st.button("Check Emails & Run Automations"):
        with st.spinner("Checking for new replies..."):
            unread_emails = get_unread_emails()
            if not unread_emails:
                st.info("No new unread replies found.")
            else:
                st.write(f"Found {len(unread_emails)} new email(s). Processing now...")
                for mail in unread_emails:
                    log_event_to_db(conn, "received", mail["from"], mail["subject"], "success", body=mail["body"], mail_id=mail["id"])
                    interest = classify_email_interest(mail["body"])
                    st.write(f"→ From: {mail['from']} | Subject: '{mail['subject']}' | Detected Interest: **{interest.capitalize()}**")
                    send_reply(conn, mail["from"], mail["subject"], interest, mail["id"])
                st.success("✅ Finished processing all new replies.")
    
    if conn: conn.close()

if __name__ == "__main__":
    main()

