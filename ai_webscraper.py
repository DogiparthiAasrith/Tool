import streamlit as st
from serpapi import GoogleSearch as SerpApiSearch 
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import datetime as dt
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import os
from dotenv import load_dotenv

load_dotenv()

# ===============================
# CONFIGURATION & CONSTANTS
# ===============================
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

RAW_SCRAPED_COLLECTION = "scraped_contacts"
CLEANED_COLLECTION_NAME = "cleaned_contacts"

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
PHONE_REGEX = r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"

# ===============================
# DATABASE & HELPER FUNCTIONS
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

# **FIX:** Function is defined here in the global scope
def perform_google_search(query, num_results=5):
    """Performs a Google search using the SerpAPI."""
    params = {"q": query, "api_key": SERPAPI_API_KEY, "num": num_results}
    # Use the renamed class
    search = SerpApiSearch(params) 
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
    if not contact_url: return {"emails": [], "phones": []}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(contact_url, headers=headers, timeout=15)
        text = resp.text
        emails = list(set(re.findall(EMAIL_REGEX, text)))
        phones = list(set(re.findall(PHONE_REGEX, text)))
    except Exception:
        pass
    return {"emails": emails, "phones": phones}


def save_to_raw_scraped_log(db, data):
    try:
        db[RAW_SCRAPED_COLLECTION].insert_one(data)
    except Exception as e:
        st.error(f"❌ Error saving to raw scrape log: {e}")


def save_to_cleaned_mongo(db, dict_data):
    source_url = dict_data.get("source_url")
    if not source_url: return
    try:
        result = db[CLEANED_COLLECTION_NAME].update_one(
            {'source_url': source_url}, {'$setOnInsert': dict_data}, upsert=True
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
        website_url = (item.get("url") or "").rstrip('/')
        
        # 1. Raw Log
        raw_scrape_data = {
            "query": query, "company_name": item.get("title", ""), "website_url": website_url,
            "snippet": item.get("snippet", ""), "scraped_emails": contact_info.get("emails", []),
            "scraped_phones": contact_info.get("phones", []), "scraped_at": dt.datetime.now(dt.timezone.utc)
        }
        save_to_raw_scraped_log(db, raw_scrape_data)
        
        # 2. Cleaned Data
        cleaned_data = {
            "name": item.get("title", ""), "source_url": website_url,
            "emails": ", ".join(contact_info.get("emails", [])), "phones": ", ".join(contact_info.get("phones", [])),
            "domain": website_url.split('/')[2] if website_url and len(website_url.split('/')) > 2 else None,
            "source": "Web Scraper",
            "created_at": dt.datetime.now(dt.timezone.utc)
        }
        save_to_cleaned_mongo(db, cleaned_data)

        rows_for_display.append({
            "company_name": item.get("title", ""), "website_url": website_url,
            "emails": ", ".join(contact_info.get("emails", [])), "phones": ", ".join(contact_info.get("phones", [])),
        })
    return pd.DataFrame(rows_for_display)


# ===============================
# STREAMLIT UI
# ===============================
def main():
    st.title("🕸 AI Web Scraper")
    st.markdown("Enter a query to find websites and scrape their contact information.")
    query = st.text_input("Enter your search query (e.g., 'Software companies in Bangalore'):")

    if st.button("Search & Scrape"):
        
        # Check for API key
        if not SERPAPI_API_KEY:
            st.error("❌ SERPAPI_API_KEY is not set!")
            st.warning("Please configure your .env file or Streamlit Secrets.")
            st.stop() 

        if not query:
            st.warning("Please enter a search query!")
            return

        client, db = get_db_connection()
        if not client:
            return

        try:
            with st.spinner("Searching Google and scraping websites..."):
                # **FIX:** Calling the correctly defined function
                results = perform_google_search(query, num_results=10)
                
                progress_bar = st.progress(0, text="Scraping websites...")
                for i, item in enumerate(results):
                    website = item.get("url")
                    if website:
                        contact_page = find_contact_page(website)
                        item["contact_info"] = scrape_contact_page(contact_page)
                    progress_bar.progress((i + 1) / len(results), text=f"Scraped: {website}")

            st.info("Saving results to the database...")
            df = process_and_save_results(results, query, db)
            st.success("✅ Scraping and saving process completed!")
            
            st.subheader("Scraped Data from this Session")
            st.dataframe(df)
            
        finally:
            if client: client.close()

if __name__ == '__main__':
    main()
