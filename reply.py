# reply.py
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
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                st.error(f"Missing {CREDENTIALS_FILE} for Google OAuth.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save token
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

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
    for e in events:
        start = e["start"].get("dateTime")
        end = e["end"].get("dateTime")
        if start and end:
            busy_times.append((datetime.datetime.fromisoformat(start.replace("Z","+00:00")),
                               datetime.datetime.fromisoformat(end.replace("Z","+00:00"))))
    current_time = now
    while current_time < end_time:
        if WORK_START_HOUR <= current_time.hour < WORK_END_HOUR and current_time.weekday() < 5:
            slot_end = current_time + datetime.timedelta(hours=1)
            if not any(s < slot_end and e > current_time for s,e in busy_times):
                return current_time, slot_end
        current_time += datetime.timedelta(minutes=30)
    return None, None

def create_google_meet_event(service, attendee_email):
    start, end = get_next_free_slot(service)
    if not start: return None, None
    event = {
        "summary": f"Morphius AI Demo with {attendee_email}",
        "description": "Discussion about AI solutions.",
        "start": {"dateTime": start.isoformat(), "timeZone":"Asia/Kolkata"},
        "end": {"dateTime": end.isoformat(), "timeZone":"Asia/Kolkata"},
        "attendees":[{"email":attendee_email},{"email":EMAIL}],
        "conferenceData":{"createRequest":{"requestId":f"meet-{datetime.datetime.now().timestamp()}"}}
    }
    created = service.events().insert(calendarId="primary", body=event, conferenceDataVersion=1).execute()
    return created.get("hangoutLink"), start

# ================================
# DATABASE FUNCTIONS
# ================================
def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

def setup_database_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS email_logs (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                        event_type VARCHAR(50),
                        recipient_email TEXT,
                        subject TEXT,
                        status VARCHAR(50),
                        body TEXT,
                        interest_level VARCHAR(50),
                        mail_id TEXT,
                        meeting_time TIMESTAMPTZ,
                        meet_link TEXT
                    );""")
    conn.commit()

def log_event_to_db(conn, event_type, email_addr, subject, **kwargs):
    with conn.cursor() as cur:
        cols = ["event_type","recipient_email","subject"]
        vals = [event_type,email_addr,subject]
        for k,v in kwargs.items():
            cols.append(k)
            vals.append(v)
        placeholders = ",".join(["%s"]*len(vals))
        sql = f"INSERT INTO email_logs ({','.join(cols)}) VALUES ({placeholders})"
        cur.execute(sql, tuple(vals))
    conn.commit()

# ================================
# EMAIL & AI FUNCTIONS
# ================================
def classify_interest_with_keywords(body):
    body = body.lower()
    pos = ["interested","let's connect","schedule","love to","sounds great","learn more","curious"]
    neg = ["not interested","unsubscribe","remove me","not a good fit","not right now","no thank you"]
    if any(k in body for k in neg): return "negative"
    if any(k in body for k in pos): return "positive"
    return "neutral"

def classify_email_interest(body):
    try:
        prompt=f"Is this email positive, negative, or neutral?\n\n{body}"
        res = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            max_tokens=5
        )
        sentiment=res.choices[0].message.content.strip().lower()
        if sentiment in ["positive","negative","neutral"]:
            return sentiment
        return classify_interest_with_keywords(body)
    except:
        return classify_interest_with_keywords(body)

def get_unread_emails():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL,PASSWORD)
        mail.select("inbox")
        _,data = mail.search(None,"(UNSEEN)")
        emails=[]
        for e_id in data[0].split():
            _,msg_data = mail.fetch(e_id,"(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            sender = email.utils.parseaddr(msg["From"])[1]
            subject = email.header.decode_header(msg["Subject"])[0][0]
            if isinstance(subject, bytes): subject = subject.decode()
            body=""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type()=="text/plain":
                        body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore")
            emails.append({"from":sender,"subject":subject,"body":body,"id":e_id.decode()})
        mail.logout()
        return emails
    except Exception as e:
        st.error(f"Failed to fetch emails: {e}")
        return []

def send_reply(conn,to_email,orig_subject,interest,mail_id):
    subject=f"Re: {orig_subject}"
    body=""
    meet_link, meet_time = None, None
    if interest=="positive":
        service=get_calendar_service()
        if not service:
            st.error(f"Google Calendar not authorized for {to_email}")
            return
        meet_link,meet_time=create_google_meet_event(service,to_email)
        if not meet_link:
            st.error(f"No available slot for {to_email}")
            return
        body=f"""Hi,\n\nThank you for your positive response!\nMeeting: {meet_time.strftime('%A, %d %B %Y at %I:%M %p IST')}\nJoin: {meet_link}\n\nBest,\nAasrith"""
    else:
        body=f"Hi,\n\nThank you for your response. Explore more: {OTHER_SERVICES_LINK}\n\nBest,\nAasrith"

    msg = MIMEMultipart()
    msg["From"],msg["To"],msg["Subject"]=EMAIL,to_email,subject
    msg.attach(MIMEText(body,"plain"))
    try:
        with smtplib.SMTP(SMTP_SERVER,SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL,PASSWORD)
            server.sendmail(EMAIL,to_email,msg.as_string())
        log_event_to_db(conn,f"replied_{interest}",to_email,subject,status="success",
                        interest_level=interest,mail_id=mail_id,body=body,
                        meeting_time=meet_time,meet_link=meet_link)
        st.success(f"Sent '{interest}' reply to {to_email}")
    except Exception as e:
        st.error(f"Failed to send reply: {e}")
        log_event_to_db(conn,f"replied_{interest}",to_email,subject,status="failed",
                        interest_level=interest,mail_id=mail_id)

# ================================
# MAIN APP
# ================================
def main():
    st.title("📧 Automated Reply Handler + Smart Scheduler")
    conn = get_db_connection()
    if not conn: return
    setup_database_tables(conn)

    if st.button("Check Emails & Run Automations"):
        with st.spinner("Checking emails..."):
            emails = get_unread_emails()
            if not emails:
                st.info("No unread emails found")
                return
            st.write(f"Found {len(emails)} new email(s)")
            for mail in emails:
                log_event_to_db(conn,"received",mail["from"],mail["subject"],body=mail["body"],mail_id=mail["id"])
                interest=classify_email_interest(mail["body"])
                st.write(f"→ From: {mail['from']} | Subject: {mail['subject']} | Detected Interest: {interest.capitalize()}")
                send_reply(conn,mail["from"],mail["subject"],interest,mail["id"])
            st.success("Finished processing all emails")
    conn.close()

if _name=="main_":
    main()
