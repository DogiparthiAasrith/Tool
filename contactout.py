import streamlit as st
import requests
import pandas as pd
import os
import psycopg2
from io import BytesIO
import json # Import the json library to catch the specific error
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ===============================
# CONFIGURATION
# ===============================
CONTACTOUT_API_TOKEN = "9Oe9pEW8Go2QkNiltRQsauf9"
API_BASE = "https://api.contactout.com/v1/people/enrich"
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Google Drive Configuration
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
GDRIVE_FOLDER_NAME = "Morphius AI CSV Backups"

# ===============================
# GOOGLE DRIVE UTILITY FUNCTIONS (CORRECTED)
# ===============================
def get_drive_service():
    """
    Handles Google authentication robustly. It now detects and handles a corrupted
    token.json file automatically.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            # --- FIX: Added a try-except block to catch a corrupted token.json ---
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except (ValueError, json.JSONDecodeError):
            st.warning("⚠️ Your 'token.json' authentication file is corrupted. Please re-authenticate.")
            # Setting creds to None will trigger the re-authentication flow.
            creds = None
            os.remove(TOKEN_FILE) # Safely remove the bad token file

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                st.error(f"Could not refresh Google token: {e}. Please re-authenticate.")
                creds = None
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                st.error(f"Missing Google credentials file: `{CREDENTIALS_FILE}`.")
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                st.error(f"Could not start authentication server: {e}")
                return None
        # Save the new, valid credentials to the token file
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    try:
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"Failed to build Google Drive service: {e}")
        return None


def upload_df_to_drive(df, file_name):
    """Converts a DataFrame to CSV bytes and uploads it to a specific Google Drive folder."""
    service = get_drive_service()
    if not service:
        st.error("Cannot upload to Google Drive: Authentication failed or was cancelled.")
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
        # --- FIX: Check if file already exists to update it instead of creating duplicates ---
        file_id = None
        response_files = service.files().list(q=f"name='{file_name}' and '{folder_id}' in parents and trashed=false", spaces='drive', fields='files(id)').execute()
        if response_files.get('files'):
            file_id = response_files.get('files')[0].get('id')

        if file_id:
            service.files().update(fileId=file_id, media_body=media).execute()
            st.success(f"✅ Automatically updated '{file_name}' in Google Drive.")
        else:
            service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            st.success(f"✅ Automatically saved '{file_name}' to Google Drive.")

    except Exception as e:
        st.error(f"❌ An error occurred while saving to Google Drive: {e}")

# ===============================
# DATABASE & API FUNCTIONS
# ===============================
def enrich_people(payload):
    headers = {"Content-Type": "application/json", "Accept": "application/json", "token": CONTACTOUT_API_TOKEN}
    st.info("🔄 Calling ContactOut API...")
    try:
        resp = requests.post(API_BASE, headers=headers, json=payload)
        if resp.status_code != 200:
            st.error(f"ContactOut API Error (Status: {resp.status_code})")
            try:
                st.json(resp.json())
            except ValueError:
                st.text(resp.text)
        return resp.status_code, resp.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Network error contacting ContactOut API: {e}")
        return None, None
    except ValueError:
        return resp.status_code, {"error": "Received non-JSON response from API"}


def extract_relevant_fields(response, original_payload={}):
    profile = response.get("profile", response)
    linkedin_url = profile.get("linkedin_url")
    if not linkedin_url and "linkedin_url" in original_payload:
        linkedin_url = original_payload["linkedin_url"]
    if isinstance(linkedin_url, str):
        linkedin_url = linkedin_url.rstrip('/')
    return {"name": profile.get("full_name"), "linkedin_url": linkedin_url, "work_emails": ", ".join(profile.get("work_email", [])), "personal_emails": ", ".join(profile.get("personal_email", [])), "phones": ", ".join(profile.get("phone", [])), "domain": profile.get("company", {}).get("domain") if profile.get("company") else None}

def get_db_connection():
    try: return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None

def setup_database_tables():
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS contacts (id SERIAL PRIMARY KEY, name TEXT, linkedin_url TEXT, work_emails TEXT, personal_emails TEXT, phones TEXT, domain TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS cleaned_contacts (id SERIAL PRIMARY KEY, name TEXT, linkedin_url TEXT UNIQUE NOT NULL, work_emails TEXT, personal_emails TEXT, phones TEXT, domain TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);""")
            conn.commit()
    finally:
        if conn: conn.close()

def save_to_postgres(conn, dict_data):
    sql = "INSERT INTO contacts (name, linkedin_url, work_emails, personal_emails, phones, domain) VALUES (%s, %s, %s, %s, %s, %s);"
    data_tuple = (dict_data.get("name"), dict_data.get("linkedin_url"), dict_data.get("work_emails"), dict_data.get("personal_emails"), dict_data.get("phones"), dict_data.get("domain"))
    with conn.cursor() as cur: cur.execute(sql, data_tuple)
    st.success(f"✅ Saved '{dict_data.get('name') or 'Unknown'}' to raw contacts log.")

def save_to_cleaned_postgres(conn, dict_data):
    if not dict_data.get("linkedin_url"): return False
    sql = "INSERT INTO cleaned_contacts (name, linkedin_url, work_emails, personal_emails, phones, domain) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (linkedin_url) DO NOTHING;"
    data_tuple = (dict_data.get("name"), dict_data.get("linkedin_url"), dict_data.get("work_emails"), dict_data.get("personal_emails"), dict_data.get("phones"), dict_data.get("domain"))
    with conn.cursor() as cur:
        cur.execute(sql, data_tuple)
        if cur.rowcount > 0:
            st.success(f"✅ Added new unique contact '{dict_data.get('name')}' to cleaned data.")
            return True
        else:
            st.info(f"ℹ️ Contact '{dict_data.get('name')}' already exists in cleaned data.")
            return False

def sync_cleaned_contacts_to_drive():
    conn = get_db_connection()
    if not conn: return
    try:
        st.info("Syncing cleaned contacts list to Google Drive...")
        df = pd.read_sql("SELECT * FROM cleaned_contacts ORDER BY id DESC", conn)
        if not df.empty:
            upload_df_to_drive(df, "cleaned_contacts.csv")
    finally:
        if conn: conn.close()

def process_enrichment(payload):
    if not payload: return
    status, response = enrich_people(payload)
    if status != 200 or not isinstance(response, dict): return

    enriched_data = extract_relevant_fields(response, payload)
    st.success("✅ Enriched Data:")
    st.json(enriched_data)
    
    conn = get_db_connection()
    if not conn: return
    try:
        save_to_postgres(conn, enriched_data)
        new_contact_added = save_to_cleaned_postgres(conn, enriched_data)
        conn.commit()
        if new_contact_added:
            sync_cleaned_contacts_to_drive()
    except (Exception, psycopg2.DatabaseError) as error:
        st.error(f"❌ An unexpected error occurred: {error}") # More generic error message
        conn.rollback()
    finally:
        if conn: conn.close()

def main():
    st.title("Contact Information Collector")
    setup_database_tables()
    choice = st.selectbox("Choose an input type to enrich:", ("Email", "LinkedIn URL", "Name + Company", "Company Domain"))
    
    if choice == 'Email':
        email = st.text_input("Enter the email address:")
        if st.button("Enrich from Email") and email:
            process_enrichment({"email": email, "include": ["work_email", "personal_email", "phone"]})
    elif choice == 'LinkedIn URL':
        linkedin_url = st.text_input("Enter the LinkedIn URL:")
        if st.button("Enrich from LinkedIn URL") and linkedin_url:
            process_enrichment({"linkedin_url": linkedin_url, "include": ["work_email", "personal_email", "phone"]})
    elif choice == 'Name + Company':
        name = st.text_input("Enter the full name:")
        company = st.text_input("Enter the company name:")
        if st.button("Enrich from Name + Company") and name and company:
            process_enrichment({"full_name": name, "company": [company], "include": ["work_email", "personal_email", "phone"]})

if __name__ == '__main__':
    main()
