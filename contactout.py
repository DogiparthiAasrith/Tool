import streamlit as st
import requests
import pandas as pd
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from dotenv import load_dotenv
import datetime

# Load environment variables from .env file
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
CONTACTOUT_API_TOKEN = os.getenv("CONTACTOUT_API_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
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

        if resp.status_code != 200:
            st.error(f"ContactOut API returned an error (Status Code: {resp.status_code})")
            try:
                st.json(resp.json())
            except ValueError:
                st.text(resp.text)

        return resp.status_code, resp.json()

    except requests.exceptions.RequestException as e:
        st.error(f"A network error occurred while contacting the ContactOut API: {e}")
        return None, None
    except ValueError:
        return resp.status_code, resp.text


def extract_relevant_fields(response, original_payload={}):
    profile = response.get("profile", response)
    linkedin_url = profile.get("linkedin_url")

    if not linkedin_url and "linkedin_url" in original_payload:
        linkedin_url = original_payload["linkedin_url"]

    if isinstance(linkedin_url, str):
        linkedin_url = linkedin_url.rstrip('/')

    work_emails = profile.get("work_email", [])
    personal_emails = profile.get("personal_email", [])
    all_emails = ", ".join(work_emails + personal_emails)

    return {
        "name": profile.get("full_name"),
        "source_url": linkedin_url,
        "emails": all_emails,
        "phones": ", ".join(profile.get("phone", [])),
        "domain": profile.get("company", {}).get("domain") if profile.get("company") else None,
        "source": "ContactOut",
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    }

def get_db_connection():
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None, None

def setup_database_indexes():
    client, db = get_db_connection()
    if not client: return
    try:
        db.cleaned_contacts.create_index("source_url", unique=True)
    except OperationFailure as e:
        st.info(f"Database index on 'source_url' already exists.")
    finally:
        if client: client.close()

def save_to_mongo(db, collection_name, dict_data):
    try:
        db[collection_name].insert_one(dict_data)
        contact_name = dict_data.get("name") or "Unknown Name"
        st.success(f"✅ Saved '{contact_name}' to raw contacts log.")
    except Exception as e:
        st.error(f"❌ Error during raw save operation: {e}")

def save_to_cleaned_mongo(db, dict_data):
    source_url = dict_data.get("source_url")
    if not source_url:
        st.warning("⚠️ Skipped saving to cleaned contacts: Source URL (LinkedIn) is missing.")
        return

    try:
        result = db.cleaned_contacts.update_one(
            {'source_url': source_url},
            {'$setOnInsert': dict_data},
            upsert=True
        )
        contact_name = dict_data.get("name") or "Unknown Name"
        if result.upserted_id:
            st.success(f"✅ Added new unique contact '{contact_name}' to cleaned data.")
        else:
            st.info(f"ℹ️ Contact '{contact_name}' already exists in cleaned data.")
    except Exception as e:
        st.error(f"❌ Error during cleaned save operation: {e}")

def process_enrichment(payload):
    if not payload:
        st.warning("⚠️ No valid input provided.")
        return

    status, response = enrich_people(payload)

    if status is None:
        return

    st.write(f"API HTTP Status: {status}")

    if status == 200 and isinstance(response, dict):
        enriched_data = extract_relevant_fields(response, payload)
        st.success("✅ Enriched Data:")
        st.json(enriched_data)

        client, db = get_db_connection()
        if not client: return
        try:
            save_to_mongo(db, 'contacts', enriched_data)
            save_to_cleaned_mongo(db, enriched_data)
        except Exception as error:
            st.error(f"❌ Error during database operation: {error}")
        finally:
            if client: client.close()
    elif status == 404:
        st.warning("🟡 Contact Not Found.")

def main():
    st.title("Contact Information Collector")
    setup_database_indexes()

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
