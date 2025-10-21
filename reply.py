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
        # Add index for recipient_email and timestamp for efficient querying
        db.email_logs.create_index([("recipient_email", 1), ("timestamp", 1)])
        db.email_logs.create_index("event_type")
    except OperationFailure as e:
        st.error(f"❌ Failed to set up database indexes: {e}")

def log_event_to_db(db, event_type, email_addr, subject, status=None, interest_level=None, mail_id=None, body=None):
    try:
        log_entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "event_type": event_type,
            "recipient_email": email_addr,
            "subject": subject,
            "status": status,
            "interest_level": interest_level,
            "mail_id": mail_id, # This is the ID of the received email if event_type is 'received'
            "body": body
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
        _, data = mail.search(None, '(UNSEEN)') # Search for UNSEEN emails
        unread_ids = data[0].split()
        emails = []
        for e_id in unread_ids:
            _, msg_data = mail.fetch(e_id, '(RFC822)')
            if not msg_data or msg_data[0] is None:
                st.warning(f"Skipping malformed email with ID: {e_id}")
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
        # This case should ideally not be reached if interest is always 'positive', 'negative', 'neutral'
        st.warning(f"Unknown interest level '{interest_level}' for {to_email}. No reply sent.")
        return

    msg = MIMEMultipart(); msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject; msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(); server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        st.success(f"✅ Sent '{interest_level}' reply to {to_email}")
        log_event_to_db(db, f"replied_{interest_level}", to_email, subject, "success", interest_level, mail_id, body)
        mark_as_read(mail_id) # Mark the original incoming email as read
    except Exception as e:
        st.error(f"❌ Failed to send reply to {to_email}: {e}")

def send_initial_email(db, to_email, subject, body):
    """Sends an initial outreach email. This function should be called from another part of your app,
    e.g., when loading a new list of leads."""
    msg = MIMEMultipart(); msg["From"], msg["To"], msg["Subject"] = EMAIL, to_email, subject; msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(); server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        st.success(f"📧 Initial email sent to {to_email}")
        log_event_to_db(db, "sent", to_email, subject, "success", body=body)
        return True
    except Exception as e:
        st.error(f"❌ Failed to send initial email to {to_email}: {e}")
        return False

def mark_as_read(mail_id):
    """Marks a specific email as read on the IMAP server."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        # Ensure mail_id is a string and store it to mark as seen
        mail.store(str(mail_id), '+FLAGS', '\\Seen')
        mail.logout()
    except Exception as e:
        st.warning(f"Could not mark email {mail_id} as read: {e}")

# ===============================
# AUTOMATED TASK PROCESSING
# ===============================
def process_follow_ups(db):
    """Sends a follow-up to contacts who haven't replied to any 'sent' or 'follow_up_sent' email
    after a specified waiting period."""
    # Define the waiting period. For testing, 2 minutes. For production, 48 hours.
    # waiting_period_delta = datetime.timedelta(minutes=2) # For testing
    waiting_period_delta = datetime.timedelta(hours=48) # For production
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # Get all emails that have been 'sent' or 'follow_up_sent'
    # And have not received any 'replied_...' event
    
    # Step 1: Find all emails that have received any kind of reply
    replied_emails = db.email_logs.distinct("recipient_email", {"event_type": {"$regex": "^replied"}})

    actions_taken = 0
    
    # Step 2: Iterate through all unique contacts who have been "sent" an email
    # but not yet replied and check if they've received a follow-up
    
    # Find initial outreach emails that are old enough for a follow-up
    # and for which no reply or subsequent follow-up has been sent
    
    # Aggregate to find the last relevant event for each email and filter
    pipeline = [
        # Match only 'sent' or 'follow_up_sent' events
        {'$match': {'event_type': {'$in': ['sent', 'follow_up_sent']}}},
        # Group by recipient_email to get the last relevant event for each
        {'$group': {
            '_id': '$recipient_email',
            'last_event_type': {'$last': '$event_type'},
            'last_event_timestamp': {'$last': '$timestamp'},
            'sent_count': {'$sum': 1} # Count total sent/follow-up emails
        }},
        # Filter out those who have replied
        {'$match': {'_id': {'$nin': replied_emails}}},
        # Filter by time since last event
        {'$match': {'last_event_timestamp': {'$lt': current_time_utc - waiting_period_delta}}},
        # Ensure we don't send endless follow-ups (e.g., max 2 follow-ups)
        {'$match': {'sent_count': {'$lt': 3}}} # 1 initial + 2 follow-ups max = 3 interactions
    ]
    
    contacts_for_follow_up = list(db.email_logs.aggregate(pipeline))

    unsubscribed_docs = db.unsubscribe_list.find({}, {'email': 1})
    unsubscribed_emails = {doc['email'] for doc in unsubscribed_docs}

    for contact in contacts_for_follow_up:
        email_to_follow_up = contact['_id']
        
        if email_to_follow_up in unsubscribed_emails:
            st.info(f"Skipping follow-up for {email_to_follow_up} (unsubscribed).")
            continue

        subject = "Quick Follow-Up"
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
            st.success(f"✅ Follow-up sent to {email_to_follow_up}")
            log_event_to_db(db, "follow_up_sent", email_to_follow_up, subject, "success", body=body)
            actions_taken += 1
        except Exception as e:
            st.error(f"❌ Failed to send follow-up to {email_to_follow_up}: {e}")
            
    return actions_taken

def process_unsubscribes(db):
    """Adds contacts to the unsubscribe list if they haven't replied after 5 or more emails
    (initial + follow-ups)."""
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)

    # Step 1: Get all emails that have received any kind of reply
    replied_emails = db.email_logs.distinct("recipient_email", {"event_type": {"$regex": "^replied"}})
    
    # Step 2: Get all emails already on the unsubscribe list
    already_unsubscribed = db.unsubscribe_list.distinct("email")

    actions_taken = 0

    pipeline = [
        # Match 'sent' or 'follow_up_sent' events
        {'$match': {'event_type': {'$in': ['sent', 'follow_up_sent']}}},
        # Group by recipient_email to count how many times we've reached out
        {'$group': {
            '_id': '$recipient_email',
            'total_sent_count': {'$sum': 1},
            'latest_sent_timestamp': {'$max': '$timestamp'} # Track latest interaction
        }},
        # Filter:
        # 1. Has sent 5 or more emails
        # 2. Has NOT replied (checked against replied_emails list)
        # 3. Is NOT already unsubscribed
        # 4. We should also consider a cooling off period since the last email,
        #    to avoid immediately unsubscribing right after the 5th email is sent.
        #    Let's say, 24 hours after the 5th email.
        {'$match': {
            'total_sent_count': {'$gte': 5},
            '_id': {'$nin': replied_emails},
            '_id': {'$nin': already_unsubscribed},
            'latest_sent_timestamp': {'$lt': current_time_utc - datetime.timedelta(hours=24)} # Give them 24 hours after the 5th email
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
                    'reason': f'No reply after {contact["total_sent_count"]} emails',
                    'created_at': datetime.datetime.now(datetime.timezone.utc)
                }},
                upsert=True
            )
            st.warning(f"🚫 Added {email_addr} to unsubscribe list (no reply after {contact['total_sent_count']} emails).")
            actions_taken += 1
        except Exception as e:
            st.error(f"Failed to add {email_addr} to unsubscribe list: {e}")
    return actions_taken

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.set_page_config(page_title="Automated Reply Handler", layout="wide")
    st.title("Automated Reply & Follow-Up System")
    st.markdown("This application automates checking email replies, classifying interest, sending appropriate responses, and managing follow-ups and unsubscriptions.")

    client, db = get_db_connection()
    if not client:
        st.stop() # Stop the app if DB connection fails
    setup_database_indexes(db)

    st.sidebar.header("Email Configuration")
    st.sidebar.write(f"Sender Email: {EMAIL}")
    st.sidebar.write(f"IMAP Server: {IMAP_SERVER}")
    st.sidebar.write(f"SMTP Server: {SMTP_SERVER}")
    st.sidebar.markdown("---")
    st.sidebar.info("Ensure your .env file is correctly configured with all necessary credentials and links.")
    
    st.subheader("Manual Email Sending (for testing initial outreach)")
    with st.expander("Send a Test Initial Email"):
        test_recipient = st.text_input("Recipient Email for Test Send", value="test@example.com")
        test_subject = st.text_input("Subject for Test Send", value="Regarding Our Services")
        test_body = st.text_area("Body for Test Send", value="Hi,\n\nI hope this email finds you well. I wanted to reach out regarding [Your Service/Product]. We believe it could greatly benefit your operations by [Specific Benefit].\n\nPlease let me know if you'd be interested in learning more.\n\nBest regards,\nAasrith")
        if st.button("Send Test Initial Email"):
            if test_recipient and test_subject and test_body:
                send_initial_email(db, test_recipient, test_subject, test_body)
            else:
                st.warning("Please fill in all fields to send a test email.")
    
    st.markdown("---")
    
    st.subheader("Run Automated Tasks")
    if st.button("🚀 Check Emails & Run All Automations Now", help="This will check for new replies, send follow-ups, and process unsubscribes."):
        with st.spinner("Processing all tasks... This might take a moment."):
            
            # --- STEP 1: PROCESS NEW REPLIES ---
            st.header("1. Processing New Replies")
            unread_emails = get_unread_emails()
            if unread_emails:
                st.info(f"Found {len(unread_emails)} new email(s). Analyzing and replying...")
                progress_bar = st.progress(0)
                for i, mail in enumerate(unread_emails):
                    st.write(f"📩 Processing reply from: *{mail['from']}* (Subject: '{mail['subject']}')")
                    log_event_to_db(db, "received", mail["from"], mail["subject"], mail_id=mail["id"], body=mail["body"])
                    interest = check_interest_with_openai(mail["body"])
                    st.write(f"   -> Interest level classified as: *{interest.upper()}*")
                    send_reply(db, mail["from"], mail["subject"], interest, mail["id"])
                    progress_bar.progress((i + 1) / len(unread_emails))
                st.success("✅ Finished processing new replies.")
            else:
                st.info("No new replies to process at this time.")
            
            st.markdown("---")

            # --- STEP 2: PROCESS FOLLOW-UPS ---
            st.header("2. Checking for Pending Follow-ups")
            follow_ups_sent = process_follow_ups(db)
            if follow_ups_sent > 0:
                 st.success(f"📧 Sent {follow_ups_sent} follow-up email(s).")
            else:
                st.info("No contacts met the criteria for a follow-up.")

            st.markdown("---")

            # --- STEP 3: PROCESS UNSUBSCRIBES ---
            st.header("3. Checking for Unresponsive Contacts")
            unsubscribes_processed = process_unsubscribes(db)
            if unsubscribes_processed > 0:
                st.warning(f"🚫 Added {unsubscribes_processed} contact(s) to the unsubscribe list.")
            else:
                st.info("No contacts met the criteria for unsubscribing.")
            
            st.markdown("---")
            st.success("✅ All automated tasks complete for this run!")
    
    st.markdown("---")
    st.subheader("Current Status")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Emails Logged", db.email_logs.count_documents({}))
    with col2:
        st.metric("Total Unsubscribes", db.unsubscribe_list.count_documents({}))
    with col3:
        st.metric("Positive Replies", db.email_logs.count_documents({"interest_level": "positive"}))

    st.markdown("---")

    # Display recent activity (last 10 logs)
    st.subheader("Recent Activity Log")
    recent_logs = list(db.email_logs.find().sort("timestamp", -1).limit(10))
    if recent_logs:
        df_logs = pd.DataFrame(recent_logs)
        df_logs['_id'] = df_logs['_id'].apply(str) # Convert ObjectId to string for display
        st.dataframe(df_logs)
    else:
        st.info("No activity logs yet.")

    # Display unsubscribe list
    st.subheader("Unsubscribe List")
    unsubscribe_list = list(db.unsubscribe_list.find().sort("created_at", -1))
    if unsubscribe_list:
        df_unsub = pd.DataFrame(unsubscribe_list)
        df_unsub['_id'] = df_unsub['_id'].apply(str) # Convert ObjectId to string for display
        st.dataframe(df_unsub)
    else:
        st.info("No emails on the unsubscribe list.")

    client.close()

if __name__ == "__main__":
    main()
