import streamlit as st
import pandas as pd
import psycopg2
import os
from io import BytesIO
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ===============================
# CONFIGURATION
# ===============================
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
CLEANED_CSV_PATH = "cleaned_contacts.csv"
CLEANED_TABLE_NAME = "cleaned_contacts"

# Google Drive Configuration
# IMPORTANT: The scopes must include drive for this page and calendar for the reply page
# to ensure the token works for both.
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
GDRIVE_FOLDER_NAME = "Morphius AI CSV Backups"

# ===============================
# GOOGLE DRIVE FUNCTIONS
# ===============================
def upload_to_drive(file_name, file_content_bytes, mime_type):
    """Handles Google authentication and uploads a file to a specific Drive folder."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                st.error(f"Google Token expired and could not be refreshed. Please re-authenticate. Error: {e}")
                creds = None 
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                st.error(f"Missing Google credentials file: `{CREDENTIALS_FILE}`. Cannot upload to Drive.")
                return
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                st.error(f"Could not start local server for Google authentication: {e}")
                st.info("To use Google Drive features, you may need to generate the `token.json` file by running this app on your local machine first.")
                return
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    if not creds:
        st.error("Could not obtain Google credentials. Upload cancelled.")
        return

    try:
        service = build("drive", "v3", credentials=creds)
        
        folder_id = None
        response = service.files().list(q=f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                                        spaces='drive', fields='files(id, name)').execute()
        if not response.get('files'):
            folder_metadata = {'name': GDRIVE_FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder'}
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder.get('id')
            st.info(f"Created Google Drive folder: '{GDRIVE_FOLDER_NAME}'")
        else:
            folder_id = response.get('files')[0].get('id')

        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaIoBaseUpload(BytesIO(file_content_bytes), mimetype=mime_type, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        st.success(f"✅ Successfully uploaded '{file_name}' to Google Drive folder '{GDRIVE_FOLDER_NAME}'.")

    except Exception as e:
        st.error(f"❌ An error occurred while uploading to Google Drive: {e}")


# ===============================
# DATABASE & DATA FUNCTIONS
# ===============================
def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ **Database Connection Error:** Could not connect to PostgreSQL. Please ensure the database is running and the connection URL is correct.")
        st.error(e)
        return None

def fetch_cleaned_contacts(conn):
    """Fetches all records directly from the 'cleaned_contacts' table."""
    try:
        df = pd.read_sql(f"SELECT * FROM {CLEANED_TABLE_NAME} ORDER BY id DESC", conn)
        return df
    except (Exception, psycopg2.DatabaseError) as error:
        st.warning(f"⚠️ Could not fetch cleaned contacts. The table might not exist yet. Error: {error}")
        return pd.DataFrame()

def save_df_to_csv(df):
    """Saves the DataFrame to a CSV file for download."""
    if not df.empty:
        df.to_csv(CLEANED_CSV_PATH, index=False)
        return True
    return False

# ===============================
# STREAMLIT UI
# ===============================
def main():
    """
    Main function to display the cleaned data and provide a download option.
    """
    st.title("View and Download Cleaned Data")
    st.markdown("This section displays the unique contacts collected so far. The list updates automatically as new, non-duplicate contacts are added.")

    if st.button("🔄 Refresh Data"):
        st.rerun()

    conn = get_db_connection()
    if not conn:
        return

    cleaned_df = fetch_cleaned_contacts(conn)
    conn.close()

    if not cleaned_df.empty:
        csv_saved = save_df_to_csv(cleaned_df)

        st.header(f"Unique Contacts ({len(cleaned_df)})")
        st.dataframe(cleaned_df)
        
        col1, col2 = st.columns(2)

        if csv_saved:
            with col1:
                with open(CLEANED_CSV_PATH, "rb") as file:
                    st.download_button(
                        label="📥 Download Cleaned Data (CSV)",
                        data=file,
                        file_name="cleaned_contacts.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
            with col2:
                if st.button("🚀 Upload to Google Drive", use_container_width=True, key="upload_cleaned"):
                    with st.spinner("Uploading to Google Drive..."):
                        with open(CLEANED_CSV_PATH, "rb") as file:
                            upload_to_drive(
                                file_name="cleaned_contacts.csv",
                                file_content_bytes=file.read(),
                                mime_type="text/csv"
                            )
    else:
        st.info("ℹ️ No unique contacts found in the database yet. Go to 'Collect Contacts' to add some!")

if __name__ == '__main__':
    main()
