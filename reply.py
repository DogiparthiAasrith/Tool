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

# ===============================
# LOAD CONFIG
# ===============================
load_dotenv()
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
        client.admin.command('ping')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ Database Connection Error: {e}")
        return None, None

def setup_database_indexes(db):
    try:
        db.unsubscribe_list.create_index("email", unique=True)
    except OperationFailure as e:
        st.error(f"❌ Failed to set up database indexes: {e}")

def log_event_to_db(db, event_type, email_addr, subject, status=None, interest_level=None, mail_id=None, body=None):
    try:
        db.email_logs.insert_one({
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "event_type": event_type,
            "recipient_email": email_addr,
            "subject": subject,
            "status": status,
            "interest_level": interest_level,
            "mail_id": mail_id,
            "body": body
        })
    except Exception as e:
        st.error(f"❌ Failed to log event: {e}")

# ===============================
# AI CLASSIFICATION
# ===============================
def check_interest_manually(email_body):
    body_lower = email_body.lower()
    positives = ["interested", "let's connect", "schedule", "love to", "sounds great", "learn more", "curious"]
    negatives = ["not interested", "unsubscribe", "remove me", "not a good fit", "no thank you"]
    if any(k in body_lower for k in negatives): return "negative"
    if any(k in body_lower for k in positives): return "positive"
    return "neutral"

def check_interest_with_openai(email_body):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Classify the reply as positive, negative, or neutral."},
                {"role": "user", "content": email_body}
            ],
            max_tokens=5
        )
        ans = resp.choices[0].message.content.strip().lower()
        return ans if ans in ["positive", "negative", "neutral"] else "neutral"
    except Exception as e:
        st.warning(f"⚠️ OpenAI failed: {e}")
        return check_interest_manually(email_body)

# ===============================
# EMAIL FUNCTIONS
# ===============================
def get_unread_emails():
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
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore")
            emails.append({"from": from_addr, "subject": subject, "body": body, "id": e_id.decode()})
        mail.logout()
        return emails
    except Exception as e:
        st.error(f"❌ Fetch failed: {e}")
        return []

def mark_as_read(mail_id):
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        mail.store(mail_id.encode(), '+FLAGS', '\\Seen')
        mail.logout()
    except Exception as e:
        st.warning(f"⚠️ Could not mark email {mail_id} as read: {e}")

def send_reply(db, to_email, subject, interest, mail_id):
    if interest == "positive":
        body = f"""Hi,

Thank you for your response! I'm glad to hear you're interested.
You can book a meeting with me here: {SCHEDULING_LINK}

Best regards,
Aasrith
"""
    else:
        body = f"""Hi,

Thanks for getting back. I understand completely.
You can also explore our other services here: {OTHER_SERVICES_LINK}

Best,
Aasrith
"""
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, f"Re: {subject}"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
            s.starttls()
            s.login(EMAIL, PASSWORD)
            s.sendmail(EMAIL, to_email, msg.as_string())
        st.success(f"✅ Sent reply to {to_email}")
        log_event_to_db(db, f"replied_{interest}", to_email, subject, "success", interest, mail_id, body)
        mark_as_read(mail_id)
    except Exception as e:
        st.error(f"❌ Failed to send reply: {e}")

# ===============================
# FOLLOW-UP PROCESSING (FIXED)
# ===============================
def process_follow_ups(db):
    now = datetime.datetime.now(datetime.timezone.utc)
    waiting_period = now - datetime.timedelta(minutes=2)  # change to days=2 for production

    replied = set(db.email_logs.distinct("recipient_email", {"event_type": {"$regex": "^replied"}}))
    unsubscribed = set(db.unsubscribe_list.distinct("email"))

    pipeline = [
        {'$match': {'event_type': {'$in': ['initial_outreach', 'follow_up_sent']}}},
        {'$sort': {'timestamp': 1}},
        {'$group': {
            '_id': '$recipient_email',
            'last_contact': {'$last': '$timestamp'},
            'count': {'$sum': 1}
        }}
    ]
    docs = list(db.email_logs.aggregate(pipeline))
    if not docs:
        st.info("No outreach records found.")
        return 0

    candidates = [
        d for d in docs
        if d['_id'] not in replied
        and d['_id'] not in unsubscribed
        and d['last_contact'] < waiting_period
        and d['count'] < 3
    ]

    if not candidates:
        st.info("No contacts needed a follow-up.")
        return 0

    count = 0
    for c in candidates:
        email_to = c['_id']
        subject = "Following up on my previous email"
        body = f"""Hi,

Just wanted to quickly follow up on my last email.
If now isn’t the right time, no problem.

You can also explore our other services here: {OTHER_SERVICES_LINK}

Best regards,
Aasrith
"""
        msg = MIMEMultipart()
        msg["From"], msg["To"], msg["Subject"] = EMAIL, email_to, subject
        msg.attach(MIMEText(body, "plain"))
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
                s.starttls()
                s.login(EMAIL, PASSWORD)
                s.sendmail(EMAIL, email_to, msg.as_string())
            st.success(f"📨 Follow-up sent to {email_to}")
            log_event_to_db(db, "follow_up_sent", email_to, subject, "success", body=body)
            count += 1
        except Exception as e:
            st.error(f"❌ Could not send follow-up to {email_to}: {e}")
    return count

# ===============================
# UNSUBSCRIBE HANDLER
# ===============================
def process_unsubscribes(db):
    pipeline = [
        {'$match': {'event_type': {'$in': ['initial_outreach', 'follow_up_sent']}}},
        {'$group': {'_id': '$recipient_email', 'count': {'$sum': 1}}},
        {'$match': {'count': {'$gte': 5}}}
    ]
    docs = list(db.email_logs.aggregate(pipeline))
    replied = set(db.email_logs.distinct("recipient_email", {"event_type": {"$regex": "^replied"}}))
    unsubscribed = set(db.unsubscribe_list.distinct("email"))
    count = 0

    for d in docs:
        email_addr = d['_id']
        if email_addr not in replied and email_addr not in unsubscribed:
            db.unsubscribe_list.update_one(
                {'email': email_addr},
                {'$setOnInsert': {
                    'email': email_addr,
                    'reason': 'No reply after 5 outreach attempts',
                    'created_at': datetime.datetime.now(datetime.timezone.utc)
                }},
                upsert=True
            )
            st.warning(f"🚫 Unsubscribed {email_addr}")
            count += 1
    return count

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("📧 Automated Reply Handler")
    client, db = get_db_connection()
    if not db: return
    setup_database_indexes(db)

    if st.button("Run All Automations"):
        with st.spinner("Processing emails..."):
            st.subheader("1️⃣ Checking new replies")
            unread = get_unread_emails()
            if unread:
                for m in unread:
                    log_event_to_db(db, "received", m["from"], m["subject"], mail_id=m["id"], body=m["body"])
                    interest = check_interest_with_openai(m["body"])
                    st.write(f"Interest: {interest}")
                    send_reply(db, m["from"], m["subject"], interest, m["id"])
            else:
                st.info("No new replies found.")

            st.subheader("2️⃣ Checking follow-ups")
            fups = process_follow_ups(db)
            st.write(f"Follow-ups sent: {fups}")

            st.subheader("3️⃣ Checking unsubscribes")
            unsubs = process_unsubscribes(db)
            st.write(f"Unsubscribed contacts: {unsubs}")

            st.success("✅ All automation tasks done.")
    client.close()

if __name__ == "__main__":
    main()
