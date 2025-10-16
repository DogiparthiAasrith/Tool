import streamlit as st
import pandas as pd
import psycopg2
import os

# ===============================
# CONFIGURATION
# ===============================
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
CLEANED_CSV_PATH = "cleaned_contacts.csv"
CLEANED_TABLE_NAME = "cleaned_contacts"

# ===============================
# DATABASE & DATA FUNCTIONS
# ===============================
def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None

def fetch_cleaned_contacts(conn):
    try:
        df = pd.read_sql(f"SELECT * FROM {CLEANED_TABLE_NAME} ORDER BY id DESC", conn)
        return df
    except (Exception, psycopg2.DatabaseError):
        st.warning("⚠️ Could not fetch cleaned contacts.")
        return pd.DataFrame()

# ===============================
# STREAMLIT UI
# ===============================
def main():
    st.title("View and Download Cleaned Data")
    st.markdown("This section displays the unique, cleaned contacts. The data is automatically backed up to Google Drive when new contacts are added.")

    if st.button("🔄 Refresh Data"):
        st.rerun()

    conn = get_db_connection()
    if not conn:
        return

    cleaned_df = fetch_cleaned_contacts(conn)
    conn.close()

    if not cleaned_df.empty:
        st.header(f"Unique Contacts ({len(cleaned_df)})")
        st.dataframe(cleaned_df)

        # Prepare CSV data for download button
        csv_data = cleaned_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Cleaned Data (CSV)",
            data=csv_data,
            file_name="cleaned_contacts.csv",
            mime="text/csv"
        )
    else:
        st.info("ℹ️ No unique contacts found in the database yet. Go to 'Collect Contacts' to add some!")

if __name__ == '__main__':
    main()
