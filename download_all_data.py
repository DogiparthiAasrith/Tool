import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
COLLECTION_NAMES = ["cleaned_contacts", "contacts", "scraped_contacts", "email_logs", "unsubscribe_list"]

# ===============================
# DATABASE & DATA FUNCTIONS
# ===============================
def get_db_connection():
    """Establishes a connection to the MongoDB database."""
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure:
        st.error("❌ **Database Connection Error:** Could not connect to MongoDB.")
        return None, None

def fetch_all_data(db, collection_name):
    """Fetches all records from a specified collection."""
    try:
        cursor = db[collection_name].find()
        df = pd.DataFrame(list(cursor))
        if '_id' in df.columns:
            df['_id'] = df['_id'].astype(str) # Convert ObjectId to string
        return df
    except Exception as e:
        st.warning(f"⚠️ Could not fetch data from '{collection_name}'. It might be empty. Error: {e}")
        return pd.DataFrame()

@st.cache_data
def convert_df_to_csv(df):
    """Caches the conversion of a DataFrame to a CSV string to improve performance."""
    return df.to_csv(index=False).encode('utf-8')

# ===============================
# STREAMLIT UI
# ===============================
def main():
    """
    Main function to display the download page.
    """
    st.title("📥 Download All Collected Data")
    st.markdown("Here you can download the data from your various database collections as a CSV file.")

    client, db = get_db_connection()
    if not client:
        return

    # Let the user choose which collection to download
    selected_collection = st.selectbox(
        "Select a collection to download:",
        COLLECTION_NAMES
    )

    if st.button(f"Prepare '{selected_collection}' for Download"):
        with st.spinner(f"Fetching data from '{selected_collection}'..."):
            df = fetch_all_data(db, selected_collection)
            client.close()

            if not df.empty:
                st.success(f"✅ Successfully fetched {len(df)} records.")
                st.dataframe(df.head()) # Show a preview

                csv_data = convert_df_to_csv(df)

                st.download_button(
                    label=f"Download {selected_collection}.csv",
                    data=csv_data,
                    file_name=f"{selected_collection}.csv",
                    mime="text/csv",
                )
            else:
                st.info("ℹ️ This collection is currently empty. No data to download.")

if __name__ == '__main__':
    main()