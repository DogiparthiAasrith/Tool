import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
CLEANED_CSV_PATH = "cleaned_contacts.csv"
CLEANED_COLLECTION_NAME = "cleaned_contacts"

# ===============================
# DATABASE & DATA FUNCTIONS
# ===============================
def get_db_connection():
    """Establishes and returns a connection to the MongoDB database."""
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error("❌ **Database Connection Error:** Could not connect to MongoDB.")
        st.error(e)
        return None, None

def fetch_cleaned_contacts(db):
    """Fetches records and ensures clean display with ordered columns."""
    try:
        cursor = db[CLEANED_COLLECTION_NAME].find().sort('_id', -1)
        df = pd.DataFrame(list(cursor))
        if df.empty:
            return pd.DataFrame()

        if '_id' in df.columns:
            df = df.drop(columns=['_id'])

        desired_order = [
            "name", "work_emails", "personal_emails", "phones",
            "source", "source_url", "domain", "created_at"
        ]
        final_columns = [col for col in desired_order if col in df.columns]
        return df[final_columns]
    except Exception as error:
        st.warning(f"⚠️ Could not fetch cleaned contacts. Error: {error}")
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
    # --- PAGE CONFIG ---
    st.set_page_config(
        page_title="Cleaned Contacts Viewer",
        page_icon="📇",
        layout="wide"
    )

    # --- CUSTOM CSS STYLING ---
    st.markdown("""
        <style>
        /* Global Style */
        body {
            background-color: #f8f9fb;
            font-family: 'Inter', sans-serif;
        }
        .stButton>button {
            background-color: #4CAF50;
            color: white;
            border-radius: 10px;
            height: 2.5em;
            width: 200px;
            font-weight: 600;
            transition: 0.3s;
        }
        .stButton>button:hover {
            background-color: #45a049;
            transform: scale(1.03);
        }
        .download-button > button {
            background-color: #0066cc !important;
            color: white !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
        }
        .download-button > button:hover {
            background-color: #004c99 !important;
        }
        .metric-card {
            background-color: #ffffff;
            border-radius: 15px;
            box-shadow: 0px 2px 8px rgba(0,0,0,0.1);
            padding: 20px;
            margin-bottom: 20px;
            text-align: center;
        }
        </style>
    """, unsafe_allow_html=True)

    # --- HEADER ---
    st.title("📇 Cleaned Contacts Dashboard")
    st.markdown(
        "This dashboard displays all **unique contacts** collected from ContactOut and the **AI Web Scraper**. "
        "Use the refresh button below to load the latest data."
    )
    st.markdown("---")

    # --- REFRESH BUTTON ---
    col1, col2 = st.columns([1, 6])
    with col1:
        if st.button("🔄 Refresh Data"):
            st.rerun()

    client, db = get_db_connection()
    if not client:
        return

    cleaned_df = fetch_cleaned_contacts(db)
    client.close()

    # --- DATA DISPLAY ---
    if not cleaned_df.empty:
        csv_saved = save_df_to_csv(cleaned_df)
        
        # Metrics Section
        st.markdown("### 📊 Data Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"<div class='metric-card'><h3>👥 Total Contacts</h3><h2>{len(cleaned_df)}</h2></div>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<div class='metric-card'><h3>🕒 Last Updated</h3><h2>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</h2></div>", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<div class='metric-card'><h3>🗂️ Columns</h3><h2>{len(cleaned_df.columns)}</h2></div>", unsafe_allow_html=True)
        
        st.markdown("### 📋 Contacts Data")
        st.dataframe(cleaned_df, use_container_width=True)

        # --- DOWNLOAD BUTTON ---
        if csv_saved:
            with open(CLEANED_CSV_PATH, "rb") as file:
                st.download_button(
                    label="📥 Download Cleaned Data (CSV)",
                    data=file,
                    file_name="cleaned_contacts.csv",
                    mime="text/csv",
                    key="download_button",
                    use_container_width=True,
                    help="Click to download the cleaned contacts as a CSV file.",
                    type="primary"
                )
    else:
        st.info("ℹ️ No unique contacts found yet. Go to **'Collect Contacts'** or **'AI Web Scraper'** to add some!")

if __name__ == '__main__':
    main()
