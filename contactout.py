import streamlit as st
import requests
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from dotenv import load_dotenv
import datetime

# ===============================
# CONFIGURATION
# ===============================
load_dotenv()

CONTACTOUT_API_TOKEN = os.getenv("CONTACTOUT_API_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
API_BASE = "https://api.contactout.com/v1/people/enrich"

RAW_CONTACTOUT_COLLECTION = "contacts"
CLEANED_COLLECTION_NAME = "cleaned_contacts"

# ===============================
# PAGE CONFIG & STYLING
# ===============================
st.set_page_config(page_title="Contact Information Collector", page_icon="📇", layout="centered")

st.markdown("""
    <style>
        /* General app style */
        .main {
            background-color: #f7f9fc;
            color: #1e1e1e;
            font-family: 'Inter', sans-serif;
        }
        h1, h2, h3 {
            text-align: center;
            color: #003366;
        }
        .stSelectbox label, .stTextInput label {
            font-weight: 600;
            color: #003366;
        }
        /* Custom card style */
        .stCard {
            background-color: white;
            border-radius: 18px;
            box-shadow: 0px 4px 10px rgba(0,0,0,0.1);
            padding: 20px;
            text-align: center;
            transition: all 0.3s ease;
        }
        .stCard:hover {
            box-shadow: 0px 8px 16px rgba(0,0,0,0.15);
            transform: translateY(-4px);
        }
        .stButton button {
            background: linear-gradient(90deg, #0066cc, #00aaff);
            color: white !important;
            font-weight: 600;
            border-radius: 10px;
            padding: 10px 20px;
            transition: all 0.3s ease;
        }
        .stButton button:hover {
            background: linear-gradient(90deg, #004c99, #0088cc);
            transform: scale(1.02);
        }
        .result-box {
            background-color: #e6f2ff;
            padding: 15px;
            border-radius: 10px;
            margin-top: 15px;
        }
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# ===============================
# UTILITIES
# ===============================
def enrich_people(payload):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "token": CONTACTOUT_API_TOKEN
    }
    with st.spinner("🔄 Calling ContactOut API..."):
        try:
            resp = requests.post(API_BASE, headers=headers, json=payload)
            if resp.status_code != 200:
                st.error(f"❌ API Error {resp.status_code}")
                st.json(resp.json())
            return resp.status_code, resp.json()
        except Exception as e:
            st.error(f"A network error occurred: {e}")
            return None, None

def extract_relevant_fields(response, original_payload={}):
    profile = response.get("profile", response)
    linkedin_url = profile.get("linkedin_url") or original_payload.get("linkedin_url", "")

    return {
        "name": profile.get("full_name"),
        "source_url": linkedin_url.rstrip('/'),
        "work_emails": ", ".join(profile.get("work_email", [])),
        "personal_emails": ", ".join(profile.get("personal_email", [])),
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
        db[CLEANED_COLLECTION_NAME].create_index("source_url", unique=True)
    except OperationFailure:
        pass
    finally:
        if client: client.close()

def save_to_raw_log(db, data):
    try:
        db[RAW_CONTACTOUT_COLLECTION].insert_one(data)
        st.success(f"✅ Saved '{data.get('name')}' to raw contacts log.")
    except Exception as e:
        st.error(f"❌ Error during raw save operation: {e}")

def save_to_cleaned_mongo(db, dict_data):
    source_url = dict_data.get("source_url")
    if not source_url:
        st.warning("⚠️ Skipped saving to cleaned contacts: Source URL is missing.")
        return
    try:
        result = db[CLEANED_COLLECTION_NAME].update_one(
            {'source_url': source_url},
            {'$setOnInsert': dict_data},
            upsert=True
        )
        if result.upserted_id:
            st.success(f"✨ New contact added: {dict_data.get('name')}")
        else:
            st.info(f"ℹ️ Contact already exists: {dict_data.get('name')}")
    except Exception as e:
        st.error(f"❌ Error during cleaned save operation: {e}")

def process_enrichment(payload):
    if not payload:
        st.warning("⚠️ No valid input provided.")
        return
    status, response = enrich_people(payload)
    if status != 200 or not isinstance(response, dict):
        if status == 404: st.warning("🟡 Contact Not Found.")
        return

    enriched_data = extract_relevant_fields(response, payload)
    st.markdown("### ✅ Enriched Data:")
    st.json(enriched_data)

    client, db = get_db_connection()
    if not client: return
    try:
        save_to_raw_log(db, enriched_data)
        save_to_cleaned_mongo(db, enriched_data)
    except Exception as error:
        st.error(f"❌ Error during database operation: {error}")
    finally:
        client.close()

# ===============================
# MAIN APP
# ===============================
def main():
    st.markdown("<h1>📇 Contact Information Collector</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center; color:#555;'>Enrich professional data effortlessly using ContactOut API.</p>", unsafe_allow_html=True)
    setup_database_indexes()

    st.divider()
    choice = st.selectbox(
        "Choose an input type to enrich:",
        ("LinkedIn URL", "Email", "Name + Company", "Company Domain")
    )

    include_fields = ["work_email", "personal_email", "phone"]
    payload = {}

    # Input fields styled in cards
    with st.container():
        if choice == 'LinkedIn URL':
            linkedin_url = st.text_input("🔗 Enter LinkedIn URL:")
            if st.button("✨ Enrich from LinkedIn URL"):
                if linkedin_url:
                    payload = {"linkedin_url": linkedin_url, "include": include_fields}
                    process_enrichment(payload)

        elif choice == 'Email':
            email = st.text_input("📧 Enter Email Address:")
            if st.button("✨ Enrich from Email"):
                if email:
                    payload = {"email": email, "include": include_fields}
                    process_enrichment(payload)

        elif choice == 'Name + Company':
            name = st.text_input("👤 Full Name:")
            company = st.text_input("🏢 Company Name:")
            if st.button("✨ Enrich from Name + Company"):
                if name and company:
                    payload = {"full_name": name, "company": [company], "include": include_fields}
                    process_enrichment(payload)

        elif choice == 'Company Domain':
            domain = st.text_input("🌐 Company Domain (e.g. apple.com):")
            if st.button("✨ Enrich from Company Domain"):
                if domain:
                    payload = {"company_domain": domain, "include": include_fields}
                    process_enrichment(payload)

    

if __name__ == '__main__':
    main()

