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
    """Fetches all records from the 'cleaned_contacts' collection and orders columns."""
    try:
        cursor = db[CLEANED_COLLECTION_NAME].find().sort('_id', -1)
        df = pd.DataFrame(list(cursor))
        if '_id' in df.columns:
            df = df.drop(columns=['_id'])
        
        # Define a logical order for columns
        desired_order = [
            "name", "emails", "phones", "source", 
            "source_url", "domain", "created_at"
        ]
        
        # Get columns that exist in the dataframe, in the desired order
        ordered_cols = [col for col in desired_order if col in df.columns]
        
        # Add any other columns that might exist but are not in the desired_order list
        for col in df.columns:
            if col not in ordered_cols:
                ordered_cols.append(col)
        
        return df[ordered_cols]
        
    except Exception as error:
        st.warning(f"⚠️ Could not fetch cleaned contacts. The collection might not exist yet. Error: {error}")
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
    st.markdown("This section displays the unique contacts collected from all sources. The list updates automatically as new, non-duplicate contacts are added.")

    if st.button("🔄 Refresh Data"):
        st.rerun()

    client, db = get_db_connection()
    if not client:
        return

    cleaned_df = fetch_cleaned_contacts(db)
    client.close()

    if not cleaned_df.empty:
        csv_saved = save_df_to_csv(cleaned_df)

        st.header(f"Unique Contacts ({len(cleaned_df)})")
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
        st.info("ℹ️ No unique contacts found in the database yet. Go to 'Collect Contacts' or 'AI Web Scraper' to add some!")

if __name__ == '__main__':
    main()
