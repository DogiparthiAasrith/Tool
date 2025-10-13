import streamlit as st
import requests
import pandas as pd
import os
import psycopg2

# ===============================
# CONFIGURATION
# ===============================
CONTACTOUT_API_TOKEN = "9Oe9pEW8Go2QkNiltRQsauf9"
API_BASE = "https://api.contactout.com/v1/people/enrich"
# --- FIX: Corrected the database password ---
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# ===============================
# UTILITIES
# ===============================
def enrich_people(payload):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "token": CONTACTOUT_API_TOKEN
    }
    st.info("🔄 Calling ContactOut API with payload...")
    resp = requests.post(API_BASE, headers=headers, json=payload)
    try:
        return resp.status_code, resp.json()
    except ValueError:
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

def save_to_csv(dict_data):
    df_new = pd.DataFrame([dict_data])
    output_file = "contactout_results.csv"
    if os.path.exists(output_file):
        df_old = pd.read_csv(output_file)
        all_columns = ["name", "linkedin_url", "work_emails", "personal_emails", "phones", "domain"]
        df_old = df_old.reindex(columns=all_columns)
        df_new = df_new.reindex(columns=all_columns)
        df = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df = df_new
    df.to_csv(output_file, index=False)
    return output_file

def setup_database_tables():
    """
    Ensures both 'contacts' (raw) and 'cleaned_contacts' (unique) tables exist.
    """
    try:
        with psycopg2.connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS contacts (
                        id SERIAL PRIMARY KEY,
                        name TEXT,
                        linkedin_url TEXT,
                        work_emails TEXT,
                        personal_emails TEXT,
                        phones TEXT,
                        domain TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cleaned_contacts (
                        id SERIAL PRIMARY KEY,
                        name TEXT,
                        linkedin_url TEXT UNIQUE NOT NULL,
                        work_emails TEXT,
                        personal_emails TEXT,
                        phones TEXT,
                        domain TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
    except (Exception, psycopg2.DatabaseError) as error:
        st.error(f"❌ Could not set up database tables: {error}")

def save_to_postgres(conn, dict_data):
    """Saves data to the raw 'contacts' table."""
    sql = """
        INSERT INTO contacts (name, linkedin_url, work_emails, personal_emails, phones, domain)
        VALUES (%s, %s, %s, %s, %s, %s);
    """
    data_tuple = (
        dict_data.get("name"), dict_data.get("linkedin_url"), dict_data.get("work_emails"),
        dict_data.get("personal_emails"), dict_data.get("phones"), dict_data.get("domain")
    )
    with conn.cursor() as cur:
        cur.execute(sql, data_tuple)
    contact_name = dict_data.get("name") or "Unknown Name"
    st.success(f"✅ Saved '{contact_name}' to raw contacts log.")

def save_to_cleaned_postgres(conn, dict_data):
    """
    Attempts to insert data into the 'cleaned_contacts' table.
    If the linkedin_url already exists, the database will ignore the command.
    """
    if not dict_data.get("linkedin_url"):
        st.warning("⚠️ Skipped saving to cleaned contacts: LinkedIn URL is missing.")
        return

    sql = """
        INSERT INTO cleaned_contacts (name, linkedin_url, work_emails, personal_emails, phones, domain)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (linkedin_url) DO NOTHING;
    """
    data_tuple = (
        dict_data.get("name"), dict_data.get("linkedin_url"), dict_data.get("work_emails"),
        dict_data.get("personal_emails"), dict_data.get("phones"), dict_data.get("domain")
    )
    with conn.cursor() as cur:
        cur.execute(sql, data_tuple)
        if cur.rowcount > 0:
            st.success(f"✅ Added new unique contact '{dict_data.get('name')}' to cleaned data.")
        else:
            st.info(f"ℹ️ Contact '{dict_data.get('name')}' already exists in cleaned data. No update needed.")

def process_enrichment(payload):
    if not payload:
        st.warning("⚠️ No valid input provided.")
        return
    
    status, response = enrich_people(payload)
    st.write(f"API HTTP Status: {status}")

    if status == 200 and isinstance(response, dict):
        enriched_data = extract_relevant_fields(response, payload)
        st.success("✅ Enriched Data:")
        st.json(enriched_data)
        
        file_path = save_to_csv(enriched_data)
        st.success(f"✅ Data appended to CSV: `{file_path}`")
        
        try:
            with psycopg2.connect(POSTGRES_URL) as conn:
                save_to_postgres(conn, enriched_data)
                save_to_cleaned_postgres(conn, enriched_data)
                conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            st.error(f"❌ Error during database operation: {error}")

    elif status == 404:
        st.warning("🟡 Contact Not Found.")
    else:
        st.error(f"❌ An API error occurred.")
        st.json(response)

def main():
    st.title("Contact Information Collector")
    setup_database_tables()

    st.sidebar.title("Input Type")
    choice = st.sidebar.selectbox(
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
