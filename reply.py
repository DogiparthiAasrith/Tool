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
import os

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

# --- Custom Links ---
CALENDLY_LINK = "https://calendly.com/thridorbit03/30min"
OTHER_SERVICES_LINK = "https://www.morphius.in/services"

# ===============================
# DATABASE FUNCTIONS
# ===============================
def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None

def setup_database_tables(conn):
    """Ensures all required tables and columns exist in the database."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    event_type VARCHAR(50), recipient_email TEXT, subject TEXT,
                    body TEXT, status VARCHAR(50)
                );
            """)
            cur.execute("ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS interest_level VARCHAR(50);")
            cur.execute("ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS mail_id TEXT;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS unsubscribe_list (
                    id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, reason TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to set up database tables: {e}")
        conn.rollback()

def log_event_to_db(conn, event_type, email_addr, subject, status=None, interest_level=None, mail_id=None, body=None):
    try:
        sql = "INSERT INTO email_logs (event_type, recipient_email, subject, status, interest_level, mail_id, body) VALUES (%s, %s, %s, %s, %s, %s, %s);"
        with conn.cursor() as cur:
            cur.execute(sql, (event_type, email_addr, subject, status, interest_level, mail_id, body))
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to log event to database: {e}")
        conn.rollback()

# ===============================
# AI & EMAIL FUNCTIONS
# ===============================

# --- NEW: Hardcoded fallback function ---
def check_interest_manually(email_body):
    """Performs a simple keyword search to classify interest as a fallback."""
    body_lower = email_body.lower()
    positive_keywords = ["interested", "let's connect", "schedule", "love to", "sounds great", "learn more", "curious"]
    negative_keywords = ["not interested", "unsubscribe", "remove me", "not a good fit", "not right now", "no thank you"]

    if any(keyword in body_lower for keyword in negative_keywords):
        return "negative"
    if any(keyword in body_lower for keyword in positive_keywords):
        return "positive"
    
    return "neutral"

def check_interest_with_openai(email_body):
    """Tries to classify interest with OpenAI, but falls back to a manual keyword check on failure."""
    try:
        # ATTEMPT 1: Use OpenAI
        prompt = f"Analyze the sentiment of this email reply. Respond with only one word: 'positive', 'negative', or 'neutral'.\n\nEmail: \"{email_body}\"\n\nClassification:"
        response = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}], max_tokens=5, temperature=0)
        interest = response.choices[0].message.content.strip().lower().replace(".", "")
        return interest if interest in ["positive", "negative", "neutral"] else "neutral"
    except Exception as e:
        # ATTEMPT 2: Use Fallback
        st.warning(f"⚠️ OpenAI API failed. Falling back to keyword-based analysis. (Error: {e})")
        return check_interest_manually(email_body)

def get_unread_emails():
    """Fetches unread emails from the Gmail inbox."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        _, data = mail.search(None, '(UNSEEN)')
        unread_ids = data[0].split()
        emails = []
        for e_id in unread_ids:
            _, msg_data = mail.fetch(e_id, '(RFC822)')
            msg = email.message_from_bytes(msg_data[0][1])
            from_addr = email.utils.parseaddr(msg["From"])[1]
            subject = msg["Subject"]
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        body = part.get_payload(decode=True).decode(errors='ignore')
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors='ignore')
            emails.append({"from": from_addr, "subject": subject, "body": body, "id": e_id.decode()})
        mail.logout()
        return emails
    except Exception as e:
        st.error(f"❌ Failed to fetch emails: {e}")
        return []

def send_reply(conn, to_email, original_subject, interest_level, mail_id):
    """Sends a reply based on the classified interest level."""
    # --- MODIFIED: Handle 'positive' vs 'negative'/'neutral' ---
    if interest_level == "positive":
        subject = f"Re: {original_subject}"
        body = f"Hi,\n\nThank you for your positive response! I'm glad to hear you're interested.\n\nYou can book a meeting with me directly here: {CALENDLY_LINK}\n\nI look forward to speaking with you.\n\nBest regards,\nAasrith"
    elif interest_level in ["negative", "neutral"]:
        subject = f"Re: {original_subject}"
        body = f"Hi,\n\nThank you for getting back to me. I understand.\n\nIn case you're interested, we also offer other services which you can explore here: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
    else:
        # This case should not be reached
        return

    msg = MIMEMultipart(); msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject; msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(); server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        st.success(f"✅ Sent '{interest_level}' reply to {to_email}")
        log_event_to_db(conn, f"replied_{interest_level}", to_email, subject, "success", interest_level, mail_id, body)
        mark_as_read(mail_id)
    except Exception as e:
        st.error(f"❌ Failed to send reply to {to_email}: {e}")

def mark_as_read(mail_id):
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER); mail.login(EMAIL, PASSWORD); mail.select("inbox")
        mail.store(mail_id.encode(), '+FLAGS', '\\Seen'); mail.logout()
    except Exception as e:
        st.warning(f"Could not mark email {mail_id} as read: {e}")

# ===============================
# AUTOMATED TASK PROCESSING
# ===============================
def process_follow_ups(conn):
    """Sends a follow-up to contacts who haven't replied and returns the number of actions taken."""
    two_minutes_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=2)
    follow_up_query = """
        SELECT DISTINCT recipient_email FROM email_logs
        WHERE event_type = 'sent' AND timestamp < %s
        AND recipient_email NOT IN (
            SELECT recipient_email FROM email_logs WHERE event_type LIKE 'replied%%' OR event_type = 'follow_up_sent'
        );
    """
    follow_up_candidates = pd.read_sql(follow_up_query, conn, params=(two_minutes_ago,))
    if follow_up_candidates.empty:
        return 0

    st.info("--- Sending Follow-Up Emails ---")
    unsubscribed_emails = pd.read_sql("SELECT email FROM unsubscribe_list", conn)['email'].tolist()
    actions_taken = 0
    for email_to_follow_up in follow_up_candidates['recipient_email']:
        if email_to_follow_up in unsubscribed_emails: continue

        subject, body = "Quick Follow-Up", f"Hi,\n\nJust wanted to quickly follow up on my previous email. If it's not the right time, no worries.\n\nWe also have other services you might find interesting: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
        msg = MIMEMultipart(); msg["From"], msg["To"], msg["Subject"] = EMAIL, email_to_follow_up, subject; msg.attach(MIMEText(body, "plain"))
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls(); server.login(EMAIL, PASSWORD)
                server.sendmail(EMAIL, email_to_follow_up, msg.as_string())
            st.success(f"✅ Follow-up sent to {email_to_follow_up}")
            log_event_to_db(conn, "follow_up_sent", email_to_follow_up, subject, "success", body=body)
            actions_taken += 1
        except Exception as e:
            st.error(f"❌ Failed to send follow-up to {email_to_follow_up}: {e}")
    return actions_taken

def process_unsubscribes(conn):
    """Adds contacts to the unsubscribe list if they haven't replied and returns the number of actions taken."""
    sent_counts = pd.read_sql("SELECT recipient_email, COUNT(*) as count FROM email_logs WHERE event_type IN ('sent', 'follow_up_sent') GROUP BY recipient_email", conn)
    replied_list = pd.read_sql("SELECT DISTINCT recipient_email FROM email_logs WHERE event_type LIKE 'replied%%'", conn)['recipient_email'].tolist()
    unsubscribed_list = pd.read_sql("SELECT email FROM unsubscribe_list", conn)['email'].tolist()
    
    unsubscribe_candidates = sent_counts[sent_counts['count'] >= 5]
    if unsubscribe_candidates.empty:
        return 0

    st.info("--- Updating Unsubscribe List ---")
    actions_taken = 0
    for _, row in unsubscribe_candidates.iterrows():
        email_addr = row['recipient_email']
        if email_addr not in replied_list and email_addr not in unsubscribed_list:
            try:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO unsubscribe_list (email, reason) VALUES (%s, %s) ON CONFLICT (email) DO NOTHING;", (email_addr, "No reply after 5 emails"))
                conn.commit()
                st.warning(f"🚫 Added {email_addr} to unsubscribe list.")
                actions_taken += 1
            except Exception as e:
                st.error(f"Failed to add {email_addr} to unsubscribe list: {e}")
                conn.rollback()
    return actions_taken

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("Automated Reply Handler")
    conn = get_db_connection()
    if not conn: return
    setup_database_tables(conn)

    if st.button("Check Emails & Run Automations"):
        with st.spinner("Processing..."):
            st.info("--- Checking for new replies ---")
            unread_emails = get_unread_emails()
            
            if unread_emails:
                st.write(f"Found {len(unread_emails)} new email(s).")
                for mail in unread_emails:
                    st.write(f"Processing reply from: {mail['from']}")
                    log_event_to_db(conn, "received", mail["from"], mail["subject"], mail_id=mail["id"], body=mail["body"])
                    interest = check_interest_with_openai(mail["body"])
                    st.write(f"-> Interest level: **{interest}**")
                    # --- MODIFIED: Call send_reply for all cases ---
                    send_reply(conn, mail["from"], mail["subject"], interest, mail["id"])
                st.success("✅ Finished processing new replies.")
            else:
                st.write("No new replies to process.")
                follow_ups_sent = process_follow_ups(conn)
                unsubscribes_processed = process_unsubscribes(conn)
                
                if follow_ups_sent == 0 and unsubscribes_processed == 0:
                    st.info("No pending automated tasks found.")
                else:
                    st.success("✅ Automated tasks complete.")

    conn.close()

if __name__ == "__main__":
    main()


