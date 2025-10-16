import streamlit as st
import requests
import pandas as pd
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
CONTACTOUT_API_TOKEN = os.getenv("CONTACTOUT_API_TOKEN")
POSTGRES_URL = os.getenv("POSTGRES_URL")
API_BASE = "https://api.contactout.com/v1/people/enrich"


# ===============================
# UTILITIES
# ===============================
def enrich_people(payload):
    """Makes an API call to ContactOut and handles potential errors gracefully."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "token": CONTACTOUT_API_TOKEN
    }
    st.info("🔄 Calling ContactOut API...")
    try:
        resp = requests.post(API_BASE, headers=headers, json=payload)

        # --- IMPROVED ERROR HANDLING ---
        # Check if the request was successful (e.g., status code 200)
        if resp.status_code != 200:
            st.error(f"ContactOut API returned an error (Status Code: {resp.status_code})")
            # Try to print the detailed error message from the API
            try:
                st.json(resp.json())
            except ValueError:
                st.text(resp.text) # If the error isn't in JSON format, show the raw text

        return resp.status_code, resp.json()

    except requests.exceptions.RequestException as e:
        # This catches network errors (e.g., can't connect to the server)
        st.error(f"A network error occurred while contacting the ContactOut API: {e}")
        return None, None
    except ValueError:
        # This catches errors if the response from the API is not valid JSON
        return resp.status_code, resp.text


def extract_relevant_fields(response, original_payload={}):
    profile = response.get("profile", response)
    linkedin_url = profile.get("linkedin_url")

    if not linkedin_url and "linkedin_url" in original_payload:
        linkedin_url = original_payload["linkedin_url"]

    if isinstance(linkedin_url, str):
        linkedin_url = linkedin_url.rstrip('/')

    return {
        "name": profile.get("full_name"),
        "linkedin_url": linkedin_url,
        "work_emails": ", ".join(profile.get("work_email", [])),
        "personal_emails": ", ".join(profile.get("personal_email", [])),
        "phones": ", ".join(profile.get("phone", [])),
        "domain": profile.get("company", {}).get("domain") if profile.get("company") else None
    }

def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None

def setup_database_tables():
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id SERIAL PRIMARY KEY, name TEXT, linkedin_url TEXT,
                    work_emails TEXT, personal_emails TEXT, phones TEXT,
                    domain TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cleaned_contacts (
                    id SERIAL PRIMARY KEY, name TEXT, linkedin_url TEXT UNIQUE NOT NULL,
                    work_emails TEXT, personal_emails TEXT, phones TEXT,
                    domain TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
    except (Exception, psycopg2.DatabaseError) as error:
        st.error(f"❌ Could not set up database tables: {error}")
    finally:
        if conn: conn.close()

def save_to_postgres(conn, dict_data):
    sql = "INSERT INTO contacts (name, linkedin_url, work_emails, personal_emails, phones, domain) VALUES (%s, %s, %s, %s, %s, %s);"
    data_tuple = (
        dict_data.get("name"), dict_data.get("linkedin_url"), dict_data.get("work_emails"),
        dict_data.get("personal_emails"), dict_data.get("phones"), dict_data.get("domain")
    )
    with conn.cursor() as cur:
        cur.execute(sql, data_tuple)
    contact_name = dict_data.get("name") or "Unknown Name"
    st.success(f"✅ Saved '{contact_name}' to raw contacts log.")

def save_to_cleaned_postgres(conn, dict_data):
    if not dict_data.get("linkedin_url"):
        st.warning("⚠️ Skipped saving to cleaned contacts: LinkedIn URL is missing.")
        return
    sql = "INSERT INTO cleaned_contacts (name, linkedin_url, work_emails, personal_emails, phones, domain) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (linkedin_url) DO NOTHING;"
    data_tuple = (
        dict_data.get("name"), dict_data.get("linkedin_url"), dict_data.get("work_emails"),
        dict_data.get("personal_emails"), dict_data.get("phones"), dict_data.get("domain")
    )
    with conn.cursor() as cur:
        cur.execute(sql, data_tuple)
        if cur.rowcount > 0:
            st.success(f"✅ Added new unique contact '{dict_data.get('name')}' to cleaned data.")
        else:
            st.info(f"ℹ️ Contact '{dict_data.get('name')}' already exists in cleaned data.")

def process_enrichment(payload):
    if not payload:
        st.warning("⚠️ No valid input provided.")
        return

    status, response = enrich_people(payload)

    # Handle case where the network request failed completely
    if status is None:
        return

    st.write(f"API HTTP Status: {status}")

    if status == 200 and isinstance(response, dict):
        enriched_data = extract_relevant_fields(response, payload)
        st.success("✅ Enriched Data:")
        st.json(enriched_data)

        conn = get_db_connection()
        if not conn: return
        try:
            save_to_postgres(conn, enriched_data)
            save_to_cleaned_postgres(conn, enriched_data)
            conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            st.error(f"❌ Error during database operation: {error}")
            conn.rollback()
        finally:
            if conn: conn.close()
    elif status == 404:
        st.warning("🟡 Contact Not Found.")

def main():
    st.title("Contact Information Collector")
    setup_database_tables()

    choice = st.selectbox(
        "Choose an input type to enrich:",
        ("Email", "LinkedIn URL", "Name + Company", "Company Domain")
    )

    payload = {}
    include_fields = ["work_email", "personal_email", "phone"]

    if choice == 'Email':
        email = st.text_input("Enter the email address:")
        if st.button("Enrich from Email"):
            if email:
                payload = {"email": email, "include": include_fields}
                process_enrichment(payload)
    elif choice == 'LinkedIn URL':
        linkedin_url = st.text_input("Enter the LinkedIn URL:")
        if st.button("Enrich from LinkedIn URL"):
            if linkedin_url:
                payload = {"linkedin_url": linkedin_url, "include": include_fields}
                process_enrichment(payload)
    elif choice == 'Name + Company':
        name = st.text_input("Enter the full name:")
        company = st.text_input("Enter the company name:")
        if st.button("Enrich from Name + Company"):
            if name and company:
                payload = {"full_name": name, "company": [company], "include": include_fields}
                process_enrichment(payload)
    elif choice == 'Company Domain':
        domain = st.text_input("Enter the company domain:")
        if st.button("Enrich from Company Domain"):
            if domain:
                payload = {"company_domain": domain, "include": include_fields}
                process_enrichment(payload)

if __name__ == '__main__':
    main()
