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
# Fetch environment variables, providing clear error messages if missing
try:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_API_KEY:
        st.error("❌ OPENAI_API_KEY not found in .env file. Please set it.")
        st.stop() # Stop execution if critical key is missing
    client = OpenAI(api_key=OPENAI_API_KEY)

    MONGO_URI = os.getenv("MONGO_URI")
    if not MONGO_URI:
        st.error("❌ MONGO_URI not found in .env file. Please set it.")
        st.stop()

    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
    if not MONGO_DB_NAME:
        st.error("❌ MONGO_DB_NAME not found in .env file. Please set it.")
        st.stop()

    EMAIL = os.getenv("SENDER_EMAIL")
    if not EMAIL:
        st.error("❌ SENDER_EMAIL not found in .env file. Please set it.")
        st.stop()

    PASSWORD = os.getenv("SENDER_PASSWORD")
    if not PASSWORD:
        st.error("❌ SENDER_PASSWORD not found in .env file. Please set it.")
        st.stop()

    SMTP_SERVER = os.getenv("SMTP_SERVER")
    if not SMTP_SERVER:
        st.error("❌ SMTP_SERVER not found in .env file. Please set it.")
        st.stop()

    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

    IMAP_SERVER = os.getenv("IMAP_SERVER")
    if not IMAP_SERVER:
        st.error("❌ IMAP_SERVER not found in .env file. Please set it.")
        st.stop()

    IMAP_PORT = int(os.getenv("IMAP_PORT", 993))

    SCHEDULING_LINK = os.getenv("SCHEDULING_LINK")
    if not SCHEDULING_LINK:
        st.error("❌ SCHEDULING_LINK not found in .env file. Please set it.")
        st.stop()

    OTHER_SERVICES_LINK = os.getenv("OTHER_SERVICES_LINK")
    if not OTHER_SERVICES_LINK:
        st.error("❌ OTHER_SERVICES_LINK not found in .env file. Please set it.")
        st.stop()

except Exception as e:
    st.error(f"Failed to load configuration from .env: {e}. Please check your .env file.")
    st.stop()

# Follow-up logic constants
FOLLOW_UP_DELAY_MINUTES = 2 # Time after last email (initial or follow-up) to send the next
MAX_FOLLOW_UPS = 5 # Maximum number of follow-up emails to send before unsubscribing

# ===============================
# DATABASE FUNCTIONS
# ===============================
def get_db_connection():
    """Establishes a connection to MongoDB."""
    try:
        client = MongoClient(MONGO_URI)
        # The ismaster command is cheap and does not require auth.
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ **Database Connection Error:** Could not connect to MongoDB. Please check MONGO_URI and network settings. Details: {e}")
        return None, None
    except Exception as e:
        st.error(f"❌ An unexpected error occurred during database connection: {e}")
        return None, None

def setup_database_indexes(db):
    """Ensures all required unique indexes exist for efficient querying and data integrity."""
    try:
        # Unique index to prevent duplicate unsubscribe entries
        db.unsubscribe_list.create_index("email", unique=True)
        # Compound index for efficient querying of email logs by recipient and timestamp
        db.email_logs.create_index([("recipient_email", 1), ("timestamp", -1)])
        # Index for filtering by event type
        db.email_logs.create_index("event_type")
        # Index for tracking original message ID for better threading
        db.email_logs.create_index("original_mail_id")
        st.sidebar.success("Database indexes checked/created.")
    except OperationFailure as e:
        st.error(f"❌ Failed to set up database indexes: {e}. This might indicate a permission issue or a pre-existing index conflict.")
    except Exception as e:
        st.error(f"❌ An unexpected error occurred during index setup: {e}")

def log_event_to_db(db, event_type, email_addr, subject, status=None, interest_level=None, mail_id=None, body=None, original_mail_id=None):
    """Logs an event to the email_logs collection in MongoDB."""
    try:
        log_entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "event_type": event_type,
            "recipient_email": email_addr,
            "subject": subject,
            "status": status,
            "interest_level": interest_level,
            "mail_id": mail_id, # ID of the incoming email (if any)
            "original_mail_id": original_mail_id, # ID of the outbound email in a thread
            "body": body
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
    positive_keywords = ["interested", "let's connect", "schedule", "love to", "sounds great", "learn more", "curious", "yes", "i'm in"]
    negative_keywords = ["not interested", "unsubscribe", "remove me", "not a good fit", "not right now", "no thank you", "no", "stop sending"]

    if any(keyword in body_lower for keyword in negative_keywords): return "negative"
    if any(keyword in body_lower for keyword in positive_keywords): return "positive"
    return "neutral"

@st.cache_data(ttl=3600) # Cache OpenAI responses for 1 hour to reduce API calls for repeated identical inputs
def check_interest_with_openai(email_body):
    """Tries to classify business interest with OpenAI, falls back to manual check on failure."""
    if not OPENAI_API_KEY:
        st.warning("⚠️ OpenAI API key not set. Falling back to keyword-based analysis.")
        return check_interest_manually(email_body)
    
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
        - Email: "Tell me more about X" -> neutral
        - Email: "How much does it cost?" -> neutral
        - Email: "Looks good, I'm in." -> positive
        """
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Classify this email reply:\n\n\"{email_body}\""}
            ],
            max_tokens=5, # Keep it short
            temperature=0 # Keep temperature low for consistent classification
        )
        interest = response.choices[0].message.content.strip().lower().replace(".", "")
        if interest in ["positive", "negative", "neutral"]:
            return interest
        else:
            st.warning(f"⚠️ OpenAI returned an unexpected interest level: '{interest}'. Falling back to keyword-based analysis.")
            return check_interest_manually(email_body)
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
        
        if not unread_ids:
            return []

        for e_id in unread_ids:
            try:
                _, msg_data = mail.fetch(e_id, '(RFC822)')
                msg = email.message_from_bytes(msg_data[0][1])
                from_addr_tuple = email.utils.parseaddr(msg["From"])
                from_addr = from_addr_tuple[1] if from_addr_tuple[1] else from_addr_tuple[0] # Use name if no email found
                subject = msg["Subject"] if msg["Subject"] else "No Subject"
                
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        cdispo = str(part.get('Content-Disposition'))
                        if ctype == 'text/plain' and 'attachment' not in cdispo:
                            try:
                                body = part.get_payload(decode=True).decode(errors='ignore')
                            except Exception:
                                body = "[Could not decode email body]"
                            break
                else:
                    try:
                        body = msg.get_payload(decode=True).decode(errors='ignore')
                    except Exception:
                        body = "[Could not decode email body]"
                
                emails.append({"from": from_addr, "subject": subject, "body": body, "id": e_id.decode()})
            except Exception as e:
                st.warning(f"Could not process email ID {e_id}: {e}")
                # Optionally mark this problematic email as read to avoid re-processing
                # mail.store(e_id, '+FLAGS', '\\Seen')
        mail.logout()
        return emails
    except Exception as e:
        st.error(f"❌ Failed to fetch emails. Please check IMAP_SERVER, IMAP_PORT, SENDER_EMAIL, SENDER_PASSWORD in .env. Details: {e}")
        return []

def send_reply(db, to_email, original_subject, interest_level, incoming_mail_id, is_follow_up=False, follow_up_count=0):
    """Sends a reply based on the classified interest level or a follow-up."""
    
    if is_follow_up:
        subject = f"Re: {original_subject} (Follow-up {follow_up_count+1})" if follow_up_count > 0 else f"Re: {original_subject} (Quick Follow-up)"
        body_text = f"Hi,\n\nJust wanted to quickly follow up on my previous email. If it's not the right time, no worries.\n\nWe also have other services you might find interesting: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
        event_type = "follow_up_sent"
    elif interest_level == "positive":
        subject = f"Re: {original_subject}"
        body_text = f"Hi,\n\nThank you for your positive response! I'm glad to hear you're interested.\n\nYou can book a meeting with me directly here: {SCHEDULING_LINK}\n\nI look forward to speaking with you.\n\nBest regards,\nAasrith"
        event_type = "replied_positive"
    elif interest_level in ["negative", "neutral"]:
        subject = f"Re: {original_subject}"
        body_text = f"Hi,\n\nThank you for getting back to me. I understand.\n\nIn case you're interested, we also offer other services which you can explore here: {OTHER_SERVICES_LINK}\n\nBest regards,\nAasrith"
        event_type = f"replied_{interest_level}"
    else:
        st.warning(f"Attempted to send a reply for unknown interest level: {interest_level} to {to_email}. Skipping.")
        return False

    msg = MIMEMultipart()
    msg["From"] = EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    # Add In-Reply-To and References headers for better threading, if an incoming mail ID is provided
    if incoming_mail_id:
        msg["In-Reply-To"] = f"<{incoming_mail_id}@{IMAP_SERVER}>" # Assuming IMAP_SERVER as part of Message-ID
        msg["References"] = f"<{incoming_mail_id}@{IMAP_SERVER}>"

    msg.attach(MIMEText(body_text, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls() # Secure the connection
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, to_email, msg.as_string())
        
        st.success(f"✅ Sent '{event_type.replace('_',' ')}' to {to_email}")
        log_event_to_db(db, event_type, to_email, subject, "success", interest_level if not is_follow_up else None, incoming_mail_id, body_text, original_mail_id=msg["Message-ID"])
        
        if incoming_mail_id: # Only mark as read if it's a direct reply we just processed
             mark_as_read(incoming_mail_id)
        return True
    except smtplib.SMTPAuthenticationError:
        st.error(f"❌ Failed to send email to {to_email}: Authentication error. Please check SENDER_EMAIL and SENDER_PASSWORD in .env. If using Gmail/Outlook, an App Password might be required.")
        log_event_to_db(db, event_type, to_email, subject, "failed", interest_level if not is_follow_up else None, incoming_mail_id, body_text, original_mail_id=msg["Message-ID"])
        return False
    except Exception as e:
        st.error(f"❌ Failed to send {event_type.replace('_',' ')} to {to_email}: {e}")
        log_event_to_db(db, event_type, to_email, subject, "failed", interest_level if not is_follow_up else None, incoming_mail_id, body_text, original_mail_id=msg["Message-ID"])
        return False

def mark_as_read(mail_id):
    """Marks an email as read in the IMAP inbox."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        mail.store(mail_id.encode(), '+FLAGS', '\\Seen')
        mail.logout()
        # st.info(f"Marked email {mail_id} as read.") # Optional for debugging
    except Exception as e:
        st.warning(f"Could not mark email {mail_id} as read: {e}")

# ===============================
# AUTOMATED TASK PROCESSING
# ===============================
def process_follow_ups(db):
    """Sends follow-up emails to contacts who haven't replied, up to MAX_FOLLOW_UPS."""
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # Aggregation pipeline to find candidates for follow-up
    pipeline = [
        {
            '$match': {
                'event_type': {'$in': ['sent', 'follow_up_sent']},
            }
        },
        {
            '$sort': {'timestamp': -1} # Get latest event first for each recipient
        },
        {
            '$group': {
                '_id': '$recipient_email',
                'latest_event_type': {'$first': '$event_type'},
                'latest_timestamp': {'$first': '$timestamp'},
                'subject': {'$first': '$subject'}, # The subject from the last email sent to them
                'follow_up_count': {
                    '$sum': {
                        '$cond': [{'$eq': ['$event_type', 'follow_up_sent']}, 1, 0]
                    }
                }
            }
        },
        {
            '$lookup': { # Check for any replies from this recipient
                'from': 'email_logs',
                'localField': '_id',
                'foreignField': 'recipient_email',
                'as': 'replies'
            }
        },
        {
            '$addFields': {
                'has_replied': { # True if any 'replied_...' event exists
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
                'has_replied': False, # Only consider those who haven't replied
                'follow_up_count': {'$lt': MAX_FOLLOW_UPS}, # Still within follow-up limit
                'latest_timestamp': {'$lt': current_time_utc - datetime.timedelta(minutes=FOLLOW_UP_DELAY_MINUTES)} # Last email sent long enough ago
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
        original_subject = candidate['subject'] 

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
                },
                'latest_timestamp': {'$max': '$timestamp'} # To get the last interaction time
            }
        },
        {
            '$lookup': { # Check for any replies from this recipient
                'from': 'email_logs',
                'localField': '_id',
                'foreignField': 'recipient_email',
                'as': 'replies'
            }
        },
        {
            '$addFields': {
                'has_replied': { # True if any 'replied_...' event exists
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
                'total_follow_ups_sent': MAX_FOLLOW_UPS, # Must have received max follow-ups
                'has_replied': False # Must not have replied
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
                    {'$setOnInsert': { # Only set these fields on insert
                        'email': email_addr, 
                        'reason': f'No reply after {MAX_FOLLOW_UPS} follow-up emails', 
                        'created_at': datetime.datetime.now(datetime.timezone.utc)
                    }},
                    upsert=True # Insert if not found, update if found (though 'email' is unique, so mostly insert)
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
    st.set_page_config(page_title="Automated Email Reply & Follow-up", layout="wide")
    st.title("Automated Email Reply & Follow-up Handler")
    st.markdown("Monitor inbox, send smart replies, and manage follow-ups automatically.")

    client_mongo, db = get_db_connection()
    if not client_mongo: 
        st.error("Cannot proceed without a database connection.")
        return
    
    setup_database_indexes(db)

    # Display current configuration
    st.sidebar.header("Configuration")
    st.sidebar.info(f"Sender Email: `{EMAIL}`")
    st.sidebar.info(f"Follow-up delay: `{FOLLOW_UP_DELAY_MINUTES} minutes`")
    st.sidebar.info(f"Max Follow-ups: `{MAX_FOLLOW_UPS}`")
    st.sidebar.markdown(f"**Scheduling Link:** [Link]({SCHEDULING_LINK})")
    st.sidebar.markdown(f"**Other Services Link:** [Link]({OTHER_SERVICES_LINK})")


    if st.button("🚀 Run All Email Automations Now", help="Click to process new replies, send pending follow-ups, and update unsubscribe lists."):
        with st.spinner("Processing all automated tasks... This might take a moment."):
            
            # --- STEP 1: PROCESS NEW REPLIES ---
            st.subheader("1. Processing New Replies")
            unread_emails = get_unread_emails()
            if unread_emails:
                st.write(f"Found {len(unread_emails)} new email(s) in inbox.")
                for mail in unread_emails:
                    st.markdown(f"--- Processing reply from: **`{mail['from']}`** (`{mail['subject']}`) ---")
                    log_event_to_db(db, "received", mail["from"], mail["subject"], mail_id=mail["id"], body=mail["body"])
                    
                    # Check against unsubscribe list before processing
                    unsubscribed_check = db.unsubscribe_list.find_one({'email': mail["from"]})
                    if unsubscribed_check:
                        st.info(f"Recipient `{mail['from']}` is on the unsubscribe list. No action taken.")
                        mark_as_read(mail["id"]) # Still mark as read to clear inbox
                        continue

                    interest = check_interest_with_openai(mail["body"])
                    st.write(f"-> Interest level for **`{mail['from']}`**: **`{interest.upper()}`**")
                    send_reply(db, mail["from"], mail["subject"], interest, mail["id"])
                st.success("✅ Finished processing new replies.")
            else:
                st.info("No new replies to process at this time.")
            
            # --- STEP 2: PROCESS FOLLOW-UPS ---
            st.subheader("2. Sending Pending Follow-ups")
            follow_ups_sent = process_follow_ups(db)
            if follow_ups_sent > 0:
                 st.success(f"✅ Sent {follow_ups_sent} follow-up email(s).")
            else:
                st.info("No contacts currently need a follow-up.")

            # --- STEP 3: PROCESS UNSUBSCRIBES ---
            st.subheader("3. Managing Unresponsive Contacts")
            unsubscribes_processed = process_unsubscribes(db)
            if unsubscribes_processed > 0:
                st.success(f"✅ Unsubscribed {unsubscribes_processed} contact(s) due to no reply after {MAX_FOLLOW_UPS} follow-ups.")
            else:
                st.info("No contacts met the criteria for unsubscribing this run.")
            
            st.success("🎉 All automated tasks complete for this run!")

    # Display recent activity logs
    st.subheader("📊 Recent Activity Log")
    recent_logs = list(db.email_logs.find().sort("timestamp", -1).limit(20)) # Display more logs
    if recent_logs:
        log_df = pd.DataFrame(recent_logs)
        # Select and reorder columns for better readability
        display_columns = ['timestamp', 'event_type', 'recipient_email', 'subject', 'interest_level', 'status']
        # Ensure all columns exist, fill missing with None or empty string
        for col in display_columns:
            if col not in log_df.columns:
                log_df[col] = None
        
        st.dataframe(log_df[display_columns].fillna('N/A').style.set_properties(**{'font-size': '10pt'}), use_container_width=True)
    else:
        st.info("No activity logged yet.")
    
    # Display current unsubscribe list
    st.subheader("🚫 Current Unsubscribe List")
    unsubscribe_list = list(db.unsubscribe_list.find().sort("created_at", -1))
    if unsubscribe_list:
        unsubscribe_df = pd.DataFrame(unsubscribe_list)
        # Select and reorder columns for better readability
        display_columns_unsubscribe = ['email', 'reason', 'created_at']
        for col in display_columns_unsubscribe:
            if col not in unsubscribe_df.columns:
                unsubscribe_df[col] = None
        
        st.dataframe(unsubscribe_df[display_columns_unsubscribe].fillna('N/A').style.set_properties(**{'font-size': '10pt'}), use_container_width=True)
    else:
        st.info("Unsubscribe list is empty.")

    client_mongo.close()
    st.sidebar.info("Database connection closed.")

if __name__ == "__main__":
    main()
