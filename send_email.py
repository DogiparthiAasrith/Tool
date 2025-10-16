import streamlit as st
import pandas as pd
import psycopg2
from io import StringIO, BytesIO
from openai import OpenAI
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ===============================
# CONFIGURATION
# ===============================
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

try:
    client = OpenAI(api_key=st.secrets["openai"]["api_key"])
except Exception:
    client = OpenAI(api_key="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")

# --- NEW: Google Drive Configuration ---
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
GDRIVE_FOLDER_NAME = "Morphius AI CSV Backups"

# ===============================
# NEW: GOOGLE DRIVE UTILITY FUNCTIONS
# ===============================
def get_drive_service():
    """Handles Google authentication and returns an authorized Drive service object."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try: creds.refresh(Request())
            except Exception: creds = None
        else:
            if not os.path.exists(CREDENTIALS_FILE): return None
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token: token.write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def upload_df_to_drive(df, file_name):
    """Converts a DataFrame to CSV bytes and uploads it to a specific Google Drive folder."""
    service = get_drive_service()
    if not service:
        st.error("Cannot upload to Google Drive: Service not available.")
        return

    try:
        folder_id = None
        q = f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        response = service.files().list(q=q, spaces='drive', fields='files(id)').execute()
        
        if not response.get('files'):
            folder_metadata = {'name': GDRIVE_FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder'}
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder.get('id')
        else:
            folder_id = response.get('files')[0].get('id')

        csv_bytes = df.to_csv(index=False).encode('utf-8')
        media = MediaIoBaseUpload(BytesIO(csv_bytes), mimetype='text/csv', resumable=True)
        
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        st.success(f"✅ Automatically backed up '{file_name}' to Google Drive.")
    except Exception as e:
        st.error(f"❌ An error occurred while saving to Google Drive: {e}")

# ===============================
# HELPER & EMAIL FUNCTIONS
# ===============================
def get_db_connection():
    try: return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ *Database Connection Error:* {e}")
        return None

def fetch_cleaned_contacts(conn):
    try: return pd.read_sql("SELECT * FROM cleaned_contacts ORDER BY id DESC", conn)
    except (Exception, psycopg2.DatabaseError): return pd.DataFrame()

def get_fallback_template(domain, name):
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    signature = "\n\nBest regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    domain_lower = str(domain).lower()
    if "edtech" in domain_lower: body = "I came across your profile and was impressed by your work in the EdTech space..."
    elif "commerce" in domain_lower: body = "I noticed your experience in the e-commerce sector and wanted to reach out..."
    else: body = f"I came across your profile and was interested in your work in the {domain} sector..."
    return f"{greeting}\n\n{body}{signature}"

def generate_personalized_email_body(contact_details):
    name = contact_details.get('name')
    domain = contact_details.get('domain', 'their industry')
    try:
        prompt = f"Write a professional outreach email from Aasrith at Morphius AI to {name or 'a professional'} in the {domain} sector..."
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=300)
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.warning(f"⚠️ OpenAI API failed. Using a template. (Error: {e})")
        return get_fallback_template(domain, name)

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("Generate & Edit Email Drafts")

    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []

    conn = get_db_connection()
    if not conn: return
    contacts_df = fetch_cleaned_contacts(conn)
    conn.close()

    if contacts_df.empty:
        st.info("No cleaned contacts found.")
        return

    st.header("Step 1: Select Contacts & Generate Drafts")
    if 'contacts_df' not in st.session_state:
        st.session_state.contacts_df = contacts_df.copy()
        st.session_state.contacts_df.insert(0, "Select", False)

    edited_df = st.data_editor(st.session_state.contacts_df, hide_index=True, disabled=st.session_state.contacts_df.columns.drop("Select"))
    st.session_state.contacts_df = edited_df
    selected_rows = st.session_state.contacts_df[st.session_state.contacts_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty):
        drafts = []
        with st.spinner("Generating drafts..."):
            for _, row in selected_rows.iterrows():
                to_email = row.get('work_emails') or row.get('personal_emails')
                if not to_email or pd.isna(to_email): continue
                body = generate_personalized_email_body(row)
                drafts.append({"id": row['id'], "name": row['name'], "to_email": to_email, "subject": "Connecting from Morphius AI", "body": body, "contact_details": row.to_dict()})
        
        st.session_state.edited_emails = drafts

        # --- AUTOMATION TRIGGER ---
        if drafts:
            drafts_df = pd.DataFrame(drafts)[["name", "to_email", "subject", "body"]]
            upload_df_to_drive(drafts_df, "morphius_email_drafts.csv")

    if st.session_state.edited_emails:
        st.header("Step 2: Review and Edit Drafts")
        for i, email_draft in enumerate(st.session_state.edited_emails):
            with st.expander(f"Draft for: {email_draft['name']} <{email_draft['to_email']}>", expanded=True):
                st.session_state.edited_emails[i]['subject'] = st.text_input("Subject", value=email_draft['subject'], key=f"subject_{i}")
                st.session_state.edited_emails[i]['body'] = st.text_area("Body", value=email_draft['body'], height=250, key=f"body_{i}")

        st.markdown("### 📥 Download All Drafts")
        df_export = pd.DataFrame(st.session_state.edited_emails)[["name", "to_email", "subject", "body"]]
        csv_bytes = df_export.to_csv(index=False).encode('utf-8')
        st.download_button(label="⬇ Download Drafts as CSV", data=csv_bytes, file_name="morphius_email_drafts.csv", mime="text/csv", use_container_width=True)
        st.success("✅ Drafts generated. Proceed to 'Email Preview' to send.")

if __name__ == "__main__":
    main()
