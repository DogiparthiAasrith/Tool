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
from urllib.parse import quote

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

def send_reply(db, to_email, original_subject, interest_level, mail_id):
    """Sends a reply based on the classified interest level."""
    body = ""
    subject = f"Re: {original_subject}"

    if interest_level == "positive":
        body = f"Hi,\n\nThank you for your positive response! I'm glad to hear you're interested.\n\nYou can book a meeting with me directly here: {SCHEDULING_LINK}\n\nI look forward to speaking with you.\n\nBest regards,\nAasrith"
    elif interest_level in ["negative", "neutral"]:
        body = f"Hi,\n\nThank you for getting back to me. I understand.\n\nIn case you're interested, we also offer other services which you can explore here: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
    else:
        return

    # Append the unsubscribe link to all replies
    unsubscribe_link_url = f"https://unsubscribe-52pwl9yyy-gowthami-gs-projects.vercel.app/unsubscribe?email={quote(to_email)}"
    unsubscribe_text = f"\n\nIf you prefer not to receive future emails, you can unsubscribe here: {unsubscribe_link_url}"
    final_body = body + unsubscribe_text

    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject
    msg.attach(MIMEText(final_body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        st.success(f"✅ Sent '{interest_level}' reply to {to_email}")
        log_event_to_db(db, f"replied_{interest_level}", to_email, subject, "success", interest_level, mail_id, final_body)
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
def process_follow_ups(db):
    """Sends a follow-up to contacts who haven't replied to the last outreach email."""
    waiting_period = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=2)
    replied_emails = db.email_logs.distinct("recipient_email", {"event_type": {"$regex": "^replied"}})

    pipeline = [
        {'$match': {'event_type': {'$in': ['initial_outreach', 'follow_up_sent']}}},
        {'$sort': {'timestamp': 1}},
        {'$group': {
            '_id': '$recipient_email',
            'last_contact_time': {'$last': '$timestamp'},
            'outreach_count': {'$sum': 1}
        }},
        {'$match': {
            '_id': {'$nin': replied_emails},
            'last_contact_time': {'$lt': waiting_period},
            'outreach_count': {'$lt': 1}
        }}
    ]
    
    candidates = list(db.email_logs.aggregate(pipeline))
    if not candidates:
        return 0

    unsubscribed_docs = db.unsubscribe_list.find({}, {'email': 1})
    unsubscribed_emails = {doc['email'] for doc in unsubscribed_docs}
    actions_taken = 0

    for candidate in candidates:
        email_to_follow_up = candidate['_id']
        if email_to_follow_up in unsubscribed_emails: continue

        subject = "Quick Follow-Up"
        body_content = f"Hi,\n\nJust wanted to quickly follow up on my previous email. If it's not the right time, no worries.\n\nWe also have other services you might find interesting: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
        unsubscribe_link_url = f"https://unsubscribe-52pwl9yyy-gowthami-gs-projects.vercel.app/unsubscribe?email={quote(email_to_follow_up)}"
        unsubscribe_text = f"\n\nIf you prefer not to receive future emails, you can unsubscribe here: {unsubscribe_link_url}"
        body = body_content + unsubscribe_text
        
        msg = MIMEMultipart(); msg["From"], msg["To"], msg["Subject"] = EMAIL, email_to_follow_up, subject; msg.attach(MIMEText(body, "plain"))
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls(); server.login(EMAIL, PASSWORD)
                server.sendmail(EMAIL, email_to_follow_up, msg.as_string())
            st.success(f"✅ Follow-up sent to {email_to_follow_up}")
            log_event_to_db(db, "follow_up_sent", email_to_follow_up, subject, "success", body=body)
            actions_taken += 1
        except Exception as e:
            st.error(f"❌ Failed to send follow-up to {email_to_follow_up}: {e}")
    return actions_taken

def process_unsubscribes(db):
    """Adds contacts to the unsubscribe list if they haven't replied after 5 total outreach emails."""
    pipeline = [
        {'$match': {'event_type': {'$in': ['initial_outreach', 'follow_up_sent']}}},
        {'$group': {'_id': '$recipient_email', 'count': {'$sum': 1}}},
        {'$match': {'count': {'$gte': 1}}}
    ]
    sent_counts = list(db.email_logs.aggregate(pipeline))
    
    replied_list = db.email_logs.distinct("recipient_email", {"event_type": {"$regex": "^replied"}})
    unsubscribed_list = db.unsubscribe_list.distinct("email")
    
    if not sent_counts: return 0

    actions_taken = 0
    for doc in sent_counts:
        email_addr = doc['_id']
        if email_addr not in replied_list and email_addr not in unsubscribed_list:
            try:
                db.unsubscribe_list.update_one(
                    {'email': email_addr},
                    {'$setOnInsert': {
                        'email': email_addr, 
                        'reason': 'No reply after 5 emails', 
                        'created_at': datetime.datetime.now(datetime.timezone.utc)
                    }},
                    upsert=True
                )
                st.warning(f"🚫 Added {email_addr} to unsubscribe list.")
                actions_taken += 1
            except Exception as e:
                st.error(f"Failed to add {email_addr} to unsubscribe list: {e}")
    return actions_taken

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("Automated Reply Handler")
    client, db = get_db_connection()
    if not client: return
    setup_database_indexes(db)

    if st.button("Check Emails & Run Automations"):
        with st.spinner("Processing all tasks..."):
            
            st.info("--- 1. Checking for new replies ---")
            unread_emails = get_unread_emails()
            if unread_emails:
                st.write(f"Found {len(unread_emails)} new email(s).")
                for mail in unread_emails:
                    st.write(f"Processing reply from: {mail['from']}")
                    
                    is_known_contact = db.email_logs.find_one({"recipient_email": mail['from']})

                    if is_known_contact:
                        log_event_to_db(db, "received", mail["from"], mail["subject"], mail_id=mail["id"], body=mail["body"])
                        interest = check_interest_with_openai(mail["body"])
                        st.write(f"-> Interest level: *{interest}*")
                        send_reply(db, mail["from"], mail["subject"], interest, mail["id"])
                    else:
                        st.warning(f"⚠️ Ignored email from {mail['from']} as they are not a known contact in the database.")
                        mark_as_read(mail["id"])

                st.success("✅ Finished processing new replies.")
            else:
                st.write("No new replies to process.")
            
            st.info("--- 2. Checking for pending follow-ups ---")
            follow_ups_sent = process_follow_ups(db)
            if follow_ups_sent > 0:
                 st.write(f"Sent {follow_ups_sent} follow-up email(s)..")
            else:
                st.write("No contacts needed a follow-up.")

            st.info("--- 3. Checking for unresponsive contacts ---")
            unsubscribes_processed = process_unsubscribes(db)
            if unsubscribes_processed > 0:
                st.write(f"Unsubscribed {unsubscribes_processed} contact(s) due to no reply.")
            else:
                st.write("No contacts met the criteria for unsubscribing.")
            
            st.success("✅ All automated tasks complete.")
            st.markdown("---")

    client.close()

if __name__ == "__main__":
    main()






