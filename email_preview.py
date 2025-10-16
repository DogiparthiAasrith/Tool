import streamlit as st
import smtplib
import datetime
import psycopg2
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# ===============================
# CONFIGURATION
# ===============================
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "thridorbit03@gmail.com"
SENDER_PASSWORD = "ouhc mftv huww liru"

# ===============================
# HELPER FUNCTIONS
# ===============================

def get_db_connection():
    """Establishes connection to the PostgreSQL database."""
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None

def setup_email_log_table(conn):
    """
    Ensures the 'email_logs' table exists and has all required columns.
    This function is now robust and adds any missing columns.
    """
    try:
        with conn.cursor() as cur:
            # Step 1: Create the table with a base schema if it doesn't exist.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    event_type VARCHAR(50),
                    recipient_email TEXT,
                    subject TEXT,
                    status VARCHAR(50)
                );
            """)

            # Step 2: Check for and add any missing columns to avoid errors.
            # This makes the schema management resilient.
            columns_to_add = {
                "body": "TEXT",
                "interest_level": "VARCHAR(50)",
                "mail_id": "TEXT",
                "meeting_time": "TIMESTAMP",
                "meet_link": "TEXT"
            }
            
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='email_logs';")
            existing_columns = [row[0] for row in cur.fetchall()]
            
            schema_updated = False
            for col, col_type in columns_to_add.items():
                if col not in existing_columns:
                    st.info(f"Updating 'email_logs' table schema to add '{col}' column...")
                    cur.execute(f"ALTER TABLE email_logs ADD COLUMN {col} {col_type};")
                    schema_updated = True
            
            if schema_updated:
                st.success("Schema updated successfully.")

        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to create or verify email_logs table: {e}")
        conn.rollback()

def log_event_to_db(conn, event_type, email_addr, subject, body, status):
    """Inserts an email event record, including the body, into the 'email_logs' table."""
    try:
        sql = """
            INSERT INTO email_logs (event_type, recipient_email, subject, body, status)
            VALUES (%s, %s, %s, %s, %s);
        """
        with conn.cursor() as cur:
            cur.execute(sql, (event_type, email_addr, subject, body, status))
        conn.commit()
    except Exception as e:
        st.error(f"❌ Failed to log event to database: {e}")
        conn.rollback()

def send_email_smtp(conn, to_email, subject, body):
    """Connects to the SMTP server, sends the email, and logs the event (with body) to the database."""
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        
        log_event_to_db(conn, "sent", to_email, subject, body, "success")
        return True
    except Exception as e:
        st.error(f"❌ Failed to send to {to_email}: {e}")
        log_event_to_db(conn, "sent", to_email, subject, body, "failed")
        return False

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("Email Preview & Send")

    if 'edited_emails' not in st.session_state or not st.session_state.edited_emails:
        st.info("📧 Please generate and edit some email drafts on the 'Generate & Edit Emails' page first.")
        return

    st.header("Final Review")
    st.info("This is a read-only preview of the emails that will be sent. Review them carefully.")

    for email in st.session_state.edited_emails:
        st.markdown("---")
        st.markdown(f"**To:** {email['name']} <{email['to_email']}>")
        st.markdown(f"**Subject:** {email['subject']}")
        st.text_area("Body Preview", value=email['body'], height=200, disabled=True, key=f"preview_{email['id']}")
    
    st.markdown("---")
    
    if st.button(f"🚀 Send {len(st.session_state.edited_emails)} Emails Now", type="primary"):
        conn = get_db_connection()
        if not conn:
            st.error("Cannot send emails without a database connection for logging.")
            return
        
        # This now ensures all columns exist before trying to log.
        setup_email_log_table(conn) 
        
        success_count = 0
        progress_bar = st.progress(0, text="Initializing...")
        
        for i, email_to_send in enumerate(st.session_state.edited_emails):
            progress_text = f"Sending email {i+1}/{len(st.session_state.edited_emails)} to {email_to_send['to_email']}..."
            progress_bar.progress((i + 1) / len(st.session_state.edited_emails), text=progress_text)
            if send_email_smtp(conn, email_to_send['to_email'], email_to_send['subject'], email_to_send['body']):
                success_count += 1
        
        conn.close()
        st.success(f"Campaign complete! Sent {success_count} out of {len(st.session_state.edited_emails)} emails. Full details logged to the database.")
        st.session_state.edited_emails = []
        st.rerun()

if __name__ == "__main__":
    main()
