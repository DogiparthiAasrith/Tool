import streamlit as st
from serpapi import GoogleSearch
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from datetime import datetime
import datetime as dt
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
import os
from dotenv import load_dotenv

load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

RAW_SCRAPED_COLLECTION = "scraped_contacts"
CLEANED_COLLECTION_NAME = "cleaned_contacts"

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
PHONE_REGEX = r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"

PERSONAL_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "protonmail.com", "zoho.com", "gmx.com"
]

# ===============================
# FUNCTIONS
# ===============================
def get_db_connection():
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None, None

def google_search(query, num_results=5):
    params = {"q": query, "api_key": SERPAPI_API_KEY, "num": num_results}
    search = GoogleSearch(params)
    results = search.get_dict().get("organic_results", [])
    return [{"title": r.get("title"), "url": r.get("link"), "snippet": r.get("snippet")} for r in results]

def find_contact_page(website_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(website_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href_text = a.get_text(strip=True).lower()
            href_url = a["href"].lower()
            if "contact" in href_url or "contact" in href_text:
                return requests.compat.urljoin(website_url, a["href"])
    except requests.exceptions.RequestException:
        pass
    return website_url

def scrape_contact_page(contact_url):
    emails, phones = [], []
    if not contact_url:
        return {"emails": [], "phones": []}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(contact_url, headers=headers, timeout=10)
        text = resp.text
        emails = list(set(re.findall(EMAIL_REGEX, text)))
        phones = list(set(re.findall(PHONE_REGEX, text)))
    except requests.exceptions.RequestException:
        pass
    return {"emails": emails, "phones": phones}

def save_to_raw_scraped_log(db, data):
    try:
        db[RAW_SCRAPED_COLLECTION].insert_one(data)
    except Exception as e:
        st.error(f"❌ Error saving to raw scrape log: {e}")

def save_to_cleaned_mongo(db, dict_data):
    source_url = dict_data.get("source_url")
    if not source_url:
        st.warning(f"⚠️ Skipped saving '{dict_data.get('name', 'Unknown')}' to cleaned contacts: Source URL is missing.")
        return
    try:
        result = db[CLEANED_COLLECTION_NAME].update_one(
            {'source_url': source_url},
            {'$setOnInsert': dict_data},
            upsert=True
        )
        if result.upserted_id:
            st.success(f"✅ Added new unique contact '{dict_data.get('name')}' to cleaned data.")
        else:
            st.info(f"ℹ️ Contact '{dict_data.get('name')}' already exists (duplicate source URL).")
    except Exception as e:
        st.error(f"❌ Error during cleaned save operation: {e}")

def process_and_save_results(results, query, db):
    rows_for_display = []
    for item in results:
        contact_info = item.get("contact_info", {})
        all_emails = contact_info.get("emails", [])
        website_url = (item.get("url") or "").rstrip('/')

        work_emails = [email for email in all_emails if email.split('@')[-1] not in PERSONAL_EMAIL_DOMAINS]
        personal_emails = [email for email in all_emails if email.split('@')[-1] in PERSONAL_EMAIL_DOMAINS]

        raw_scrape_data = {
            "query": query, "company_name": item.get("title", ""), "website_url": website_url,
            "snippet": item.get("snippet", ""), "scraped_emails": all_emails,
            "scraped_phones": contact_info.get("phones", []), "scraped_at": dt.datetime.now(dt.timezone.utc)
        }
        save_to_raw_scraped_log(db, raw_scrape_data)

        cleaned_data = {
            "name": item.get("title", ""),
            "source_url": website_url,
            "work_emails": ", ".join(work_emails),
            "personal_emails": ", ".join(personal_emails),
            "phones": ", ".join(contact_info.get("phones", [])),
            "domain": website_url.split('/')[2] if website_url else None,
            "source": "Web Scraper",
            "created_at": dt.datetime.now(dt.timezone.utc)
        }
        save_to_cleaned_mongo(db, cleaned_data)

        rows_for_display.append({
            "Company Name": item.get("title", ""), "Website URL": website_url,
            "Work Emails": ", ".join(work_emails),
            "Personal Emails": ", ".join(personal_emails),
            "Phones": ", ".join(contact_info.get("phones", []))
        })
    return pd.DataFrame(rows_for_display)

# ===============================
# STREAMLIT UI
# ===============================
def main():
    # Set page configuration for a wider layout and a custom title
    st.set_page_config(layout="wide", page_title="AI Web Scraper", page_icon="🕸️")

    # Custom CSS for a professional look
    st.markdown("""
        <style>
        .stApp {
            background-color: #f0f2f6; /* Light gray background */
        }
        .css-vk329t e16z3jvj2 { /* Header container - targeting a common Streamlit div for potential future use */
            background-color: #ffffff;
            padding: 20px;
            border-bottom: 1px solid #e0e0e0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #2c3e50; /* Darker blue for headings */
            text-align: center;
            font-size: 3em;
            margin-bottom: 0.5em;
        }
        h2, h3, h4, h5, h6 {
            color: #34495e; /* Slightly lighter dark blue */
        }
        .stButton button {
            background-color: #3498db; /* Blue button */
            color: white;
            border-radius: 8px;
            padding: 10px 20px;
            font-size: 1.1em;
            border: none;
            transition: all 0.2s ease-in-out;
        }
        .stButton button:hover {
            background-color: #2980b9; /* Darker blue on hover */
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }
        .stTextInput label {
            font-size: 1.1em;
            color: #34495e;
            font-weight: 500;
        }
        .stTextInput input {
            border-radius: 8px;
            border: 1px solid #cccccc;
            padding: 10px;
            font-size: 1em;
        }
        .stDataFrame {
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            overflow: hidden; /* Ensures borders are respected */
        }
        .stAlert {
            border-radius: 8px;
        }
        .stSuccess {
            background-color: #e6ffe6;
            color: #006400;
        }
        .stError {
            background-color: #ffe6e6;
            color: #cc0000;
        }
        .stWarning {
            background-color: #fff8e6;
            color: #cc6600;
        }
        .stInfo {
            background-color: #e6f7ff;
            color: #004d99;
        }
        .stSpinner > div > div {
            border-top-color: #3498db;
        }
        footer {visibility: hidden;} /* Hide default Streamlit footer */
        </style>
    """, unsafe_allow_html=True)

    # Header Section
    st.markdown("<h1 style='text-align: center; color: #2c3e50;'>🕸️ AI Web Scraper</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #555; font-size: 1.1em;'>Enter a query to find websites, extract contact information, and categorize emails. Results are saved securely to MongoDB.</p>", unsafe_allow_html=True)

    st.markdown("---") # Horizontal line for separation

    # Input Section
    st.subheader("⚙️ Search Configuration")
    query = st.text_input("What kind of businesses are you looking for?", placeholder="e.g., 'Tech startups in Silicon Valley', 'Cafes in London', 'Dentists in New York'")
    num_results = st.slider("Number of search results to process:", min_value=1, max_value=20, value=5)

    search_button = st.button("🚀 Start Scraping", use_container_width=True)

    st.markdown("---")

    # Display Results Section
    if search_button:
        if not SERPAPI_API_KEY:
            st.error("❌ **SerpAPI Key Missing!** Please add your `SERPAPI_API_KEY` to your Streamlit secrets (`.streamlit/secrets.toml`) to continue.")
            st.stop()
        if not query:
            st.warning("⚠️ Please enter a search query to begin!")
            return

        client, db = get_db_connection()
        if not client:
            st.error("Cannot connect to MongoDB. Please check your `MONGO_URI` and network connection.")
            return

        try:
            with st.spinner("Searching Google for relevant websites..."):
                results = google_search(query, num_results=num_results)

            if not results:
                st.info("No organic search results found for your query. Try a different query.")
                return

            st.subheader("🌐 Scraping Websites for Contacts...")
            progress_text = "Scraping in progress. Please wait."
            progress_bar = st.progress(0, text=progress_text)

            scraped_data_list = []
            for i, item in enumerate(results):
                website = item.get("url")
                if website:
                    progress_bar.progress((i + 1) / len(results), text=f"Scraping: {item.get('title', 'Unknown')} ({website})")
                    contact_page = find_contact_page(website)
                    item["contact_info"] = scrape_contact_page(contact_page)
                    scraped_data_list.append(item)
                else:
                    st.warning(f"Skipping a result due to missing URL: {item.get('title', 'N/A')}")

            progress_bar.empty() # Clear the progress bar after completion
            st.success("✅ Website scraping complete! Processing and saving data...")

            df = process_and_save_results(scraped_data_list, query, db)

            st.subheader("📊 Scraped Contact Data")
            if not df.empty:
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    label="⬇️ Download Scraped Data (CSV)",
                    data=df.to_csv(index=False).encode("utf-8"),
                    file_name=f"scraped_contacts_{query.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    help="Download the data displayed in the table above as a CSV file."
                )
            else:
                st.info("No contact information was successfully extracted in this session.")

        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")
        finally:
            if client: client.close()
            st.info("Database connection closed.")

    st.markdown("---")
if __name__ == '__main__':
    main()

