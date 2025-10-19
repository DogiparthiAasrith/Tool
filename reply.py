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

# Follow-up logic constants
FOLLOW_UP_DELAY_MINUTES = 2 # Time after last email (initial or follow-up) to send the next
MAX_FOLLOW_UPS = 5 # Maximum number of follow-up emails to send before unsubscribing

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
        st.error(f"❌ **Database Connection Error:** {e}")
        return None, None

def setup_database_indexes(db):
    """Ensures all required unique indexes exist."""
    try:
        db.unsubscribe_list.create_index("email", unique=True)
        # Add index for efficient querying in email_logs
        db.email_logs.create_index([("recipient_email", 1), ("timestamp", -1)])
        db.email_logs.create_index("event_type")
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
        # st.info(f"Logged: {event_type} for {email_addr}") # Optional: for detailed logging feedback
    except Exception as e:
        st.error(f"❌ Failed to log event to database: {e}")

# ===============================
# AI & EMAIL FUNCTIONS
# ===============================
def check_interest_manually(email_body):
    """Performs a simple keyword search to classify interest as a fallback."""
    body_lower = email_body.lower()
    positive_keywords = ["interested", "let's connect", "schedule", "love to", "sounds great", "learn more", "curious", "yes"]
    negative_keywords = ["not interested", "unsubscribe", "remove me", "not a good fit", "not right now", "no thank you", "no"]

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
        - Email: "Yes, I'd like to know more." -> positive
        - Email: "No, thank you." -> negative
        """
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Classify this email reply:\n\n\"{email_body}\""}
            ],
            max_tokens=5,
            temperature=0 # Keep temperature low for consistent classification
        )
        interest = response.choices[0].message.content.strip().lower().replace(".", "")
        return interest if interest in ["positive", "negative", "neutral"] else "neutral"
    except Exception as e:
        st.warning(f"⚠️ OpenAI API failed. Falling back to keyword-based analysis. (Error: {e})")
        return check_interest_manually(email_body)

def get_unread_emails():
    """Fetches unread emails from the inbox."""
    emails = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        _, data = mail.search(None, '(UNSEEN)')
        unread_ids = data[0].split()
        
        for e_id in unread_ids:
            try:
                _, msg_data = mail.fetch(e_id, '(RFC822)')
                msg = email.message_from_bytes(msg_data[0][1])
                from_addr = email.utils.parseaddr(msg["From"])[1]
                subject = msg["Subject"]
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        cdispo = str(part.get('Content-Disposition'))
                        if ctype == 'text/plain' and 'attachment' not in cdispo:
                            body = part.get_payload(decode=True).decode(errors='ignore')
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors='ignore')
                emails.append({"from": from_addr, "subject": subject, "body": body, "id": e_id.decode()})
            except Exception as e:
                st.warning(f"Could not process email ID {e_id}: {e}")
                # Optionally mark this problematic email as read to avoid re-processing
                # mail.store(e_id, '+FLAGS', '\\Seen')
        mail.logout()
        return emails
    except Exception as e:
        st.error(f"❌ Failed to fetch emails: {e}")
        return []

def send_reply(db, to_email, original_subject, interest_level, mail_id, is_follow_up=False, follow_up_count=0):
    """Sends a reply based on the classified interest level or a follow-up."""
    
    if is_follow_up:
        subject = f"Re: {original_subject} (Follow-up {follow_up_count+1})" if follow_up_count > 0 else f"Re: {original_subject} (Quick Follow-up)"
        body = f"Hi,\n\nJust wanted to quickly follow up on my previous email. If it's not the right time, no worries.\n\nWe also have other services you might find interesting: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
        event_type = "follow_up_sent"
    elif interest_level == "positive":
        subject = f"Re: {original_subject}"
        body = f"Hi,\n\nThank you for your positive response! I'm glad to hear you're interested.\n\nYou can book a meeting with me directly here: {SCHEDULING_LINK}\n\nI look forward to speaking with you.\n\nBest regards,\nAasrith"
        event_type = "replied_positive"
    elif interest_level in ["negative", "neutral"]:
        subject = f"Re: {original_subject}"
        body = f"Hi,\n\nThank you for getting back to me. I understand.\n\nIn case you're interested, we also offer other services which you can explore here: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
        event_type = f"replied_{interest_level}"
    else:
        return

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
        
        st.success(f"✅ Sent '{event_type.replace('_',' ')}' to {to_email}")
        log_event_to_db(db, event_type, to_email, subject, "success", interest_level if not is_follow_up else None, mail_id, body)
        if not is_follow_up: # Only mark as read if it's an actual reply we just processed
             mark_as_read(mail_id)
        return True
    except Exception as e:
        st.error(f"❌ Failed to send {event_type.replace('_',' ')} to {to_email}: {e}")
        log_event_to_db(db, event_type, to_email, subject, "failed", interest_level if not is_follow_up else None, mail_id, body)
        return False

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
    """Sends follow-up emails to contacts who haven't replied, up to MAX_FOLLOW_UPS."""
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # Find all emails that have been 'sent' or 'follow_up_sent' but not 'replied'
    pipeline = [
        {
            '$match': {
                'event_type': {'$in': ['sent', 'follow_up_sent']},
            }
        },
        {
            '$sort': {'timestamp': -1} # Get latest event first
        },
        {
            '$group': {
                '_id': '$recipient_email',
                'latest_event_type': {'$first': '$event_type'},
                'latest_timestamp': {'$first': '$timestamp'},
                'subject': {'$first': '$subject'}, # The original subject from the last email
                'follow_up_count': {
                    '$sum': {
                        '$cond': [{'$eq': ['$event_type', 'follow_up_sent']}, 1, 0]
                    }
                }
            }
        },
        {
            '$lookup': {
                'from': 'email_logs',
                'localField': '_id',
                'foreignField': 'recipient_email',
                'as': 'replies'
            }
        },
        {
            '$addFields': {
                'has_replied': {
                    '$gt': [
                        {'$size': {
                            '$filter': {
                                'input': '$replies',
                                'as': 'reply',
                                'cond': {'$regexMatch': {'input': '$$reply.event_type', 'regex': '^replied'}}
                            }
                        }}, 0
                    ]
                }
            }
        },
        {
            '$match': {
                'has_replied': False,
                'follow_up_count': {'$lt': MAX_FOLLOW_UPS},
                'latest_timestamp': {'$lt': current_time_utc - datetime.timedelta(minutes=FOLLOW_UP_DELAY_MINUTES)}
            }
        }
    ]
    
    candidates = list(db.email_logs.aggregate(pipeline))
    
    if not candidates:
        return 0

    unsubscribed_docs = db.unsubscribe_list.find({}, {'email': 1})
    unsubscribed_emails = {doc['email'] for doc in unsubscribed_docs}
    actions_taken = 0

    for candidate in candidates:
        email_to_follow_up = candidate['_id']
        original_subject = candidate['subject'] # Use the subject of the last email in the chain

        if email_to_follow_up in unsubscribed_emails:
            # st.info(f"Skipping follow-up for {email_to_follow_up}: already unsubscribed.")
            continue
        
        # Ensure we don't accidentally send a 6th follow-up if MAX_FOLLOW_UPS is 5
        if candidate['follow_up_count'] < MAX_FOLLOW_UPS:
            if send_reply(db, email_to_follow_up, original_subject, None, None, is_follow_up=True, follow_up_count=candidate['follow_up_count']):
                actions_taken += 1
    return actions_taken

def process_unsubscribes(db):
    """Adds contacts to the unsubscribe list if they've received MAX_FOLLOW_UPS and haven't replied."""
    
    # Find emails that have received MAX_FOLLOW_UPS and have NOT replied
    pipeline = [
        {
            '$match': {
                'event_type': {'$in': ['sent', 'follow_up_sent']},
            }
        },
        {
            '$group': {
                '_id': '$recipient_email',
                'total_follow_ups_sent': {
                    '$sum': {
                        '$cond': [{'$eq': ['$event_type', 'follow_up_sent']}, 1, 0]
                    }
                }
            }
        },
        {
            '$lookup': {
                'from': 'email_logs',
                'localField': '_id',
                'foreignField': 'recipient_email',
                'as': 'replies'
            }
        },
        {
            '$addFields': {
                'has_replied': {
                    '$gt': [
                        {'$size': {
                            '$filter': {
                                'input': '$replies',
                                'as': 'reply',
                                'cond': {'$regexMatch': {'input': '$$reply.event_type', 'regex': '^replied'}}
                            }
                        }}, 0
                    ]
                }
            }
        },
        {
            '$match': {
                'total_follow_ups_sent': MAX_FOLLOW_UPS,
                'has_replied': False
            }
        }
    ]
    
    unresponsive_candidates = list(db.email_logs.aggregate(pipeline))
    
    if not unresponsive_candidates:
        return 0

    unsubscribed_emails = db.unsubscribe_list.distinct("email") # Get already unsubscribed emails
    actions_taken = 0

    for doc in unresponsive_candidates:
        email_addr = doc['_id']
        if email_addr not in unsubscribed_emails:
            try:
                db.unsubscribe_list.update_one(
                    {'email': email_addr},
                    {'$setOnInsert': {
                        'email': email_addr, 
                        'reason': f'No reply after {MAX_FOLLOW_UPS} follow-up emails', 
                        'created_at': datetime.datetime.now(datetime.timezone.utc)
                    }},
                    upsert=True
                )
                st.warning(f"🚫 Added {email_addr} to unsubscribe list (no reply after {MAX_FOLLOW_UPS} follow-ups).")
                actions_taken += 1
            except Exception as e:
                st.error(f"Failed to add {email_addr} to unsubscribe list: {e}")
    return actions_taken

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("Automated Reply Handler")
    st.markdown("Monitor inbox, send smart replies, and manage follow-ups automatically.")

    client_mongo, db = get_db_connection()
    if not client_mongo: return
    setup_database_indexes(db)

    # Display current configuration
    st.sidebar.header("Configuration")
    st.sidebar.info(f"Sender Email: `{EMAIL}`")
    st.sidebar.info(f"Follow-up delay: `{FOLLOW_UP_DELAY_MINUTES} minutes`")
    st.sidebar.info(f"Max Follow-ups: `{MAX_FOLLOW_UPS}`")
    st.sidebar.info(f"Scheduling Link: {SCHEDULING_LINK}")
    st.sidebar.info(f"Other Services Link: {OTHER_SERVICES_LINK}")


    if st.button("Check Emails & Run Automations", help="Click to process all new replies, send pending follow-ups, and update unsubscribe lists."):
        with st.spinner("Processing all tasks..."):
            
            # --- STEP 1: PROCESS NEW REPLIES ---
            st.subheader("1. Processing New Replies")
            unread_emails = get_unread_emails()
            if unread_emails:
                st.write(f"Found {len(unread_emails)} new email(s).")
                for mail in unread_emails:
                    st.write(f"--- Processing reply from: **{mail['from']}** ---")
                    log_event_to_db(db, "received", mail["from"], mail["subject"], mail_id=mail["id"], body=mail["body"])
                    
                    # Check against unsubscribe list before processing
                    unsubscribed_check = db.unsubscribe_list.find_one({'email': mail["from"]})
                    if unsubscribed_check:
                        st.info(f"Recipient {mail['from']} is on the unsubscribe list. No action taken.")
                        mark_as_read(mail["id"]) # Still mark as read to clear inbox
                        continue

                    interest = check_interest_with_openai(mail["body"])
                    st.write(f"-> Interest level for **{mail['from']}**: **{interest.upper()}**")
                    send_reply(db, mail["from"], mail["subject"], interest, mail["id"])
                st.success("✅ Finished processing new replies.")
            else:
                st.info("No new replies to process.")
            
            # --- STEP 2: PROCESS FOLLOW-UPS ---
            st.subheader("2. Sending Pending Follow-ups")
            follow_ups_sent = process_follow_ups(db)
            if follow_ups_sent > 0:
                 st.success(f"Sent {follow_ups_sent} follow-up email(s).")
            else:
                st.info("No contacts needed a follow-up at this time.")

            # --- STEP 3: PROCESS UNSUBSCRIBES ---
            st.subheader("3. Managing Unresponsive Contacts")
            unsubscribes_processed = process_unsubscribes(db)
            if unsubscribes_processed > 0:
                st.success(f"Unsubscribed {unsubscribes_processed} contact(s) due to no reply after {MAX_FOLLOW_UPS} follow-ups.")
            else:
                st.info("No contacts met the criteria for unsubscribing.")
            
            st.success("🎉 All automated tasks complete for this run!")

    # Display basic logs/stats
    st.subheader("Recent Activity Log")
    recent_logs = list(db.email_logs.find().sort("timestamp", -1).limit(10))
    if recent_logs:
        log_df = pd.DataFrame(recent_logs)
        log_df['_id'] = log_df['_id'].astype(str) # Convert ObjectId to string for display
        st.dataframe(log_df)
    else:
        st.info("No activity logged yet.")
    
    st.subheader("Current Unsubscribe List")
    unsubscribe_list = list(db.unsubscribe_list.find().sort("created_at", -1))
    if unsubscribe_list:
        unsubscribe_df = pd.DataFrame(unsubscribe_list)
        unsubscribe_df['_id'] = unsubscribe_df['_id'].astype(str)
        st.dataframe(unsubscribe_df)
    else:
        st.info("Unsubscribe list is empty.")


    client_mongo.close()

if __name__ == "__main__":
    main()
