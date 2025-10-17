import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import os
from dotenv import load_dotenv

# Load environment variables from .env file
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
        st.error(f"❌ **Database Connection Error:** Could not connect to MongoDB.")
        st.error(e)
        return None, None

def fetch_cleaned_contacts(db):
    """Fetches records, selecting and ordering only the desired columns to ensure a clean display."""
    try:
        cursor = db[CLEANED_COLLECTION_NAME].find().sort('_id', -1)
        df = pd.DataFrame(list(cursor))
        
        if df.empty:
            return pd.DataFrame()

        # MongoDB adds an '_id' column, which we remove for display
        if '_id' in df.columns:
            df = df.drop(columns=['_id'])
        
        # **FIX:** Define the exact columns and their order for a clean, consistent table.
        # This prevents old or mismatched column names (like 'work_emails') from appearing.
        desired_order = [
            "name", 
            "emails", 
            "phones", 
            "source", 
            "source_url", 
            "domain", 
            "created_at"
        ]
        
        # We will only show columns that are in our desired_order list.
        # This makes the display robust against any old or malformed data in the database.
        final_columns = [col for col in desired_order if col in df.columns]
        
        # Return the DataFrame with ONLY the selected and ordered columns.
        return df[final_columns]
        
    except Exception as error:
        st.warning(f"⚠️ Could not fetch cleaned contacts. Collection might be empty. Error: {error}")
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
    st.markdown("This section displays all unique contacts collected from ContactOut and the AI Web Scraper. The list updates automatically.")

    if st.button("🔄 Refresh Data"):
        st.rerun()

    client, db = get_db_connection()
    if not client:
        return

    cleaned_df = fetch_cleaned_contacts(db)
    client.close()

    if not cleaned_df.empty:
        csv_saved = save_df_to_csv(cleaned_df)

        st.header(f"Total Unique Contacts ({len(cleaned_df)})")
        st.dataframe(cleaned_df)

        if csv_saved:
            with open(CLEANED_CSV_PATH, "rb") as file:
                st.download_button(
                    label="📥 Download Cleaned Data (CSV)",
                    data=file,
                    file_name="cleaned_contacts.csv",
                    mime="text/csv"
                )
    else:
        st.info("ℹ️ No unique contacts found yet. Go to 'Collect Contacts' or 'AI Web Scraper' to add some!")

if __name__ == '__main__':
    main()
