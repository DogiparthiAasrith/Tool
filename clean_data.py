import streamlit as st
import pandas as pd
import psycopg2
import os

# ===============================
# CONFIGURATION
# ===============================
# --- FIX: Corrected the database password ---
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
CLEANED_CSV_PATH = "cleaned_contacts.csv"
CLEANED_TABLE_NAME = "cleaned_contacts"

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

        if csv_saved:
            with open(CLEANED_CSV_PATH, "rb") as file:
                st.download_button(
                    label="📥 Download Cleaned Data (CSV)",
                    data=file,
                    file_name="cleaned_contacts.csv",
                    mime="text/csv"
                )
    else:
        st.info("ℹ️ No unique contacts found in the database yet. Go to 'Collect Contacts' to add some!")

if __name__ == '__main__':

    main()
