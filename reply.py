import streamlit as st
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import datetime
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
EMAIL = os.getenv("SENDER_EMAIL")
PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
IMAP_SERVER = os.getenv("IMAP_SERVER")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
SCHEDULING_LINK = os.getenv("SCHEDULING_LINK")
OTHER_SERVICES_LINK = os.getenv("OTHER_SERVICES_LINK")

# ===============================
# DATABASE FUNCTIONS
# ===============================
def get_db_connection():
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ *Database Connection Error:* {e}")
        return None, None

def setup_database_indexes(db):
    """Ensures all required unique indexes exist."""
    try:
        db.unsubscribe_list.create_index("email", unique=True)
        # Crucial indexes for efficient follow-up and unsubscribe queries
        db.email_logs.create_index([("recipient_email", 1), ("timestamp", 1)])
        db.email_logs.create_index("event_type")
        # Ensure event_type and recipient_email are indexed for distinct queries
        db.email_logs.create_index("event_type")
        db.email_logs.create_index("recipient_email")
    except OperationFailure as e:
        st.error(f"❌ Failed to set up database indexes: {e}")

def log_event_to_db(db, event_type, email_addr, subject, status=None, interest_level=None, mail_id=None, body=None):
    try:
        log_entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "event_type": event_type, "recipient_email": email_addr,
            "subject": subject, "status": status, "interest_level": interest_level,
            "mail_id": mail_id, "body": body
        }
        db.email_logs.insert_one(log_entry)
    except Exception as e:
        st.error(f"❌ Failed to log event to database: {e}")

# ===============================
# AI & EMAIL FUNCTIONS
# ===============================
def check_interest_manually(email_body):
    """Performs a simple keyword search to classify interest as a fallback."""
    body_lower = email_body.lower()
    positive_keywords = ["interested", "let's connect", "schedule", "love to", "sounds great", "learn more", "curious"]
    negative_keywords = ["not interested", "unsubscribe", "remove me", "not a good fit", "not right now", "no thank you"]

    if any(keyword in body_lower for keyword in negative_keywords): return "negative"
    if any(keyword in body_lower for keyword in positive_keywords): return "positive"
    return "neutral"

def check_interest_with_openai(email_body):
    """Tries to classify business interest with OpenAI, falls back to manual check on failure."""
    try:
        system_prompt = """
        You are an expert assistant who classifies email replies based on business interest.
        The user was sent a business outreach email. Analyze their reply to determine if their intent is positive (interested), negative (not interested), or neutral (unclear, asking for more info).
        Respond with ONLY one word: 'positive', 'negative', or 'neutral'.

        Examples:
        - Email: "This looks great, let's connect." -> positive
        - Email: "I am not interested at this time." -> negative
        - Email: "Can you send me more details?" -> neutral
        - Email: "Please remove me from your mailing list." -> negative
        """
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Classify this email reply:\n\n\"{email_body}\""}
            ],
            max_tokens=5,
            temperature=0
        )
        interest = response.choices[0].message.content.strip().lower().replace(".", "")
        return interest if interest in ["positive", "negative", "neutral"] else "neutral"
    except Exception as e:
        st.warning(f"⚠ OpenAI API failed. Falling back to keyword-based analysis. (Error: {e})")
        return check_interest_manually(email_body)

def get_unread_emails():
    """Fetches unread emails from the inbox."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        _, data = mail.search(None, '(UNSEEN)')
        unread_ids = data[0].split()
        emails = []
        for e_id in unread_ids:
            _, msg_data = mail.fetch(e_id, '(RFC822)')
            
            # ADDED robustness for malformed emails
            if not msg_data or msg_data[0] is None:
                st.warning(f"Skipping malformed email with ID: {e_id.decode()}")
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            from_addr = email.utils.parseaddr(msg["From"])[1]
            subject = msg["Subject"] if msg["Subject"] else "No Subject" # Handle missing subject
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    cdispo = str(part.get('Content-Disposition'))
                    # Look for plain text parts, not attachments
                    if ctype == 'text/plain' and 'attachment' not in cdispo:
                        try:
                            body = part.get_payload(decode=True).decode(errors='ignore')
                        except:
                            body = "" # Fallback if decoding fails
                        break
            else:
                try:
                    body = msg.get_payload(decode=True).decode(errors='ignore')
                except:
                    body = "" # Fallback if decoding fails
            emails.append({"from": from_addr, "subject": subject, "body": body, "id": e_id.decode()})
        mail.logout()
        return emails
    except Exception as e:
        st.error(f"❌ Failed to fetch emails: {e}")
        return []

def send_reply(db, to_email, original_subject, interest_level, mail_id):
    """Sends a reply based on the classified interest level."""
    if interest_level == "positive":
        subject = f"Re: {original_subject}"
        body = f"Hi,\n\nThank you for your positive response! I'm glad to hear you're interested.\n\nYou can book a meeting with me directly here: {SCHEDULING_LINK}\n\nI look forward to speaking with you.\n\nBest regards,\nAasrith"
    elif interest_level in ["negative", "neutral"]: # Treat neutral similarly for reply purposes
        subject = f"Re: {original_subject}"
        body = f"Hi,\n\nThank you for getting back to me. I understand.\n\nIn case you're interested, we also offer other services which you can explore here: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
    else:
        st.warning(f"Unknown interest level '{interest_level}' for {to_email}. No reply sent.") # ADDED warning
        return

    msg = MIMEMultipart(); msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject; msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(); server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        st.success(f"✅ Sent '{interest_level}' reply to {to_email}")
        log_event_to_db(db, f"replied_{interest_level}", to_email, subject, "success", interest_level, mail_id, body)
        mark_as_read(mail_id)
    except Exception as e:
        st.error(f"❌ Failed to send reply to {to_email}: {e}")

def mark_as_read(mail_id):
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        mail.store(str(mail_id), '+FLAGS', '\\Seen'); mail.logout()
    except Exception as e:
        st.warning(f"Could not mark email {mail_id} as read: {e}")

# ===============================
# AUTOMATED TASK PROCESSING
# ===============================
def process_follow_ups(db):
    """
    Sends a follow-up to contacts if:
    - They haven't replied.
    - Their last 'sent' or 'follow_up_sent' email was 2 minutes ago.
    - They have received less than 5 follow-ups (meaning total emails sent < 6).
    """
    waiting_period_delta = datetime.timedelta(minutes=2)
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # Get all emails that have received any kind of reply
    replied_emails = db.email_logs.distinct("recipient_email", {"event_type": {"$regex": "^replied"}})
    
    # Get all emails already on the unsubscribe list
    already_unsubscribed = db.unsubscribe_list.distinct("email")

    actions_taken = 0
    
    # Aggregate to find the last relevant event for each email and filter
    pipeline = [
        # Match only 'sent' (initial) or 'follow_up_sent' events
        {'$match': {'event_type': {'$in': ['sent', 'follow_up_sent']}}},
        # Group by recipient_email to get the last relevant event and count total sent
        {'$group': {
            '_id': '$recipient_email',
            'last_sent_timestamp': {'$last': '$timestamp'},
            'total_sent_count': {'$sum': 1} # Counts initial email + follow-ups
        }},
        # Filter out those who have replied
        {'$match': {'_id': {'$nin': replied_emails}}},
        # Filter out those who are already unsubscribed
        {'$match': {'_id': {'$nin': already_unsubscribed}}},
        # Filter by time since last event (2 minutes)
        {'$match': {'last_sent_timestamp': {'$lt': current_time_utc - waiting_period_delta}}},
        # Ensure we don't send more than 5 follow-ups (total sent emails < 6)
        {'$match': {'total_sent_count': {'$lt': 6}}} # 1 initial + 5 follow-ups = 6 emails max
    ]
    
    contacts_for_follow_up = list(db.email_logs.aggregate(pipeline))

    for contact in contacts_for_follow_up:
        email_to_follow_up = contact['_id']
        current_follow_up_num = contact['total_sent_count'] # If total_sent_count is 1, it's the 1st follow-up (after initial)

        st.info(f"Preparing to send follow-up #{current_follow_up_num} to {email_to_follow_up}")

        subject = f"Follow-Up {current_follow_up_num}"
        body = f"Hi,\n\nJust wanted to quickly follow up on my previous email. If it's not the right time, no worries.\n\nWe also have other services you might find interesting: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
        
        msg = MIMEMultipart()
        msg["From"] = EMAIL
        msg["To"] = email_to_follow_up
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(EMAIL, PASSWORD)
                server.sendmail(EMAIL, email_to_follow_up, msg.as_string())
            st.success(f"✅ Follow-up #{current_follow_up_num} sent to {email_to_follow_up}")
            log_event_to_db(db, "follow_up_sent", email_to_follow_up, subject, "success", body=body)
            actions_taken += 1
        except Exception as e:
            st.error(f"❌ Failed to send follow-up to {email_to_follow_up}: {e}")
            
    return actions_taken

def process_unsubscribes(db):
    """
    Adds contacts to the unsubscribe list if:
    - They haven't replied to any email.
    - Exactly 5 follow-ups have been sent (meaning a total of 6 emails: 1 initial + 5 follow-ups).
    - The last email (the 5th follow-up) was sent more than 2 minutes ago.
    """
    waiting_period_delta = datetime.timedelta(minutes=2)
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)

    # Get all emails that have received any kind of reply
    replied_emails = db.email_logs.distinct("recipient_email", {"event_type": {"$regex": "^replied"}})
    
    # Get all emails already on the unsubscribe list
    already_unsubscribed = db.unsubscribe_list.distinct("email")

    actions_taken = 0

    pipeline = [
        # Match 'sent' or 'follow_up_sent' events
        {'$match': {'event_type': {'$in': ['sent', 'follow_up_sent']}}},
        # Group by recipient_email to count how many times we've reached out
        {'$group': {
            '_id': '$recipient_email',
            'total_sent_count': {'$sum': 1},
            'latest_sent_timestamp': {'$max': '$timestamp'}
        }},
        # Filter:
        # 1. Has sent exactly 6 emails (1 initial + 5 follow-ups)
        # 2. Has NOT replied
        # 3. Is NOT already unsubscribed
        # 4. The latest email was sent more than 2 minutes ago
        {'$match': {
            'total_sent_count': {'$eq': 6}, # Exactly 1 initial + 5 follow-ups
            '_id': {'$nin': replied_emails},
            '_id': {'$nin': already_unsubscribed},
            'latest_sent_timestamp': {'$lt': current_time_utc - waiting_period_delta}
        }}
    ]
    
    unresponsive_contacts = list(db.email_logs.aggregate(pipeline))

    for contact in unresponsive_contacts:
        email_addr = contact['_id']
        try:
            db.unsubscribe_list.update_one(
                {'email': email_addr},
                {'$setOnInsert': {
                    'email': email_addr,
                    'reason': f'No reply after {contact["total_sent_count"]} emails (including initial and 5 follow-ups)',
                    'created_at': datetime.datetime.now(datetime.timezone.utc)
                }},
                upsert=True
            )
            st.warning(f"🚫 Added {email_addr} to unsubscribe list (no reply after {contact['total_sent_count']} emails).")
            actions_taken += 1
        except Exception as e:
            st.error(f"Failed to add {email_addr} to unsubscribe list: {e}")
    return actions_taken

# Helper function to simulate initial email sending for testing
def send_initial_email(db, to_email, subject, body):
    msg = MIMEMultipart()
    msg["From"] = EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        st.success(f"✅ Initial email sent to {to_email}")
        log_event_to_db(db, "sent", to_email, subject, "success", body=body)
    except Exception as e:
        st.error(f"❌ Failed to send initial email to {to_email}: {e}")

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.set_page_config(layout="wide")
    st.title("Automated Reply Handler & Follow-up System")
    client, db = get_db_connection()
    if not client: return
    setup_database_indexes(db)

    st.sidebar.header("Manual Testing (Development Only)")
    with st.sidebar.expander("Send Initial Test Email"):
        test_email_recipient = st.text_input("Recipient Email for Test Send", "test@example.com")
        test_email_subject = st.text_input("Test Email Subject", "Your Business Proposal")
        test_email_body = st.text_area("Test Email Body", "Hi, just reaching out about our services. Let me know if you're interested!")
        if st.button("Send Initial Test Email"):
            if test_email_recipient and test_email_subject and test_email_body:
                send_initial_email(db, test_email_recipient, test_email_subject, test_email_body)
            else:
                st.warning("Please fill in all fields for the test email.")

    st.header("Automated Tasks")
    if st.button("Run All Automated Tasks Now"):
        with st.spinner("Processing all tasks (checking replies, follow-ups, unsubscribes)..."):
            
            # --- STEP 1: PROCESS NEW REPLIES ---
            st.subheader("1. Checking for New Replies")
            unread_emails = get_unread_emails()
            if unread_emails:
                st.write(f"Found {len(unread_emails)} new email(s).")
                for mail in unread_emails:
                    st.write(f"Processing reply from: *{mail['from']}* (Subject: {mail['subject']})")
                    log_event_to_db(db, "received", mail["from"], mail["subject"], mail_id=mail["id"], body=mail["body"])
                    interest = check_interest_with_openai(mail["body"])
                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp; -> Classified interest: *{interest.upper()}*")
                    send_reply(db, mail["from"], mail["subject"], interest, mail["id"])
                st.success("✅ Finished processing new replies.")
            else:
                st.info("No new replies to process.")
            
            # --- STEP 2: PROCESS FOLLOW-UPS ---
            st.subheader("2. Checking for Pending Follow-ups")
            follow_ups_sent = process_follow_ups(db)
            if follow_ups_sent > 0:
                 st.success(f"✅ Sent {follow_ups_sent} follow-up email(s).")
            else:
                st.info("No contacts currently need a follow-up.")

            # --- STEP 3: PROCESS UNSUBSCRIBES ---
            st.subheader("3. Checking for Unresponsive Contacts to Unsubscribe")
            unsubscribes_processed = process_unsubscribes(db)
            if unsubscribes_processed > 0:
                st.success(f"✅ Unsubscribed {unsubscribes_processed} contact(s) due to no reply after maximum follow-ups.")
            else:
                st.info("No contacts met the criteria for unsubscribing at this time.")
            
            st.success("✨ All automated tasks complete for this run.")

    st.subheader("Database Overview (Recent Activity)")
    
    # Display recent email logs
    st.markdown("### Recent Email Logs")
    log_data = list(db.email_logs.find().sort("timestamp", -1).limit(20))
    if log_data:
        df_logs = pd.DataFrame(log_data)
        st.dataframe(df_logs[['timestamp', 'event_type', 'recipient_email', 'subject', 'status', 'interest_level']])
    else:
        st.info("No email logs found yet.")

    # Display unsubscribe list
    st.markdown("### Unsubscribe List")
    unsubscribe_data = list(db.unsubscribe_list.find().sort("created_at", -1))
    if unsubscribe_data:
        df_unsub = pd.DataFrame(unsubscribe_data)
        st.dataframe(df_unsub[['created_at', 'email', 'reason']])
    else:
        st.info("Unsubscribe list is empty.")

    client.close()

if __name__ == "__main__":
    main()
