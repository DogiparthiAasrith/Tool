import streamlit as st
from serpapi import GoogleSearch
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from datetime import datetime
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

# Define collection names for raw scraped data and the final cleaned list
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

# ... (google_search, find_contact_page, scrape_contact_page functions are the same)

def save_to_raw_scraped_log(db, data):
    """Saves the raw, unprocessed data from the web scraper."""
    try:
        db[RAW_SCRAPED_COLLECTION].insert_one(data)
    except Exception as e:
        st.error(f"❌ Error saving to raw scrape log: {e}")

def save_to_cleaned_mongo(db, dict_data):
    """Saves the standardized data to the final cleaned collection, ensuring uniqueness."""
    # **FIX:** The website URL is now the unique key, not LinkedIn.
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
    """Handles the two-step save process: first to raw log, then to cleaned collection."""
    rows_for_display = []
    
    for item in results:
        contact_info = item.get("contact_info", {})
        website_url = (item.get("url") or "").rstrip('/')
        
        # 1. Prepare and save the raw data log
        raw_scrape_data = {
            "query": query,
            "company_name": item.get("title", ""),
            "website_url": website_url,
            "snippet": item.get("snippet", ""),
            "scraped_emails": contact_info.get("emails", []),
            "scraped_phones": contact_info.get("phones", []),
            "scraped_at": dt.datetime.now(dt.timezone.utc)
        }
        save_to_raw_scraped_log(db, raw_scrape_data)
        
        # 2. Prepare standardized data for the cleaned collection
        cleaned_data = {
            "name": item.get("title", ""),
            "source_url": website_url, # The website is the unique source
            "emails": ", ".join(contact_info.get("emails", [])),
            "phones": ", ".join(contact_info.get("phones", [])),
            "domain": website_url.split('/')[2] if website_url else None,
            "source": "Web Scraper",
            "created_at": dt.datetime.now(dt.timezone.utc)
        }
        save_to_cleaned_mongo(db, cleaned_data)

        rows_for_display.append({
            "company_name": item.get("title", ""),
            "website_url": website_url,
            "emails": ", ".join(contact_info.get("emails", [])),
            "phones": ", ".join(contact_info.get("phones", [])),
        })

    return pd.DataFrame(rows_for_display)
# ===============================
# STREAMLIT UI
# ===============================
def main():
    st.title("🕸 AI Web Scraper")
    st.markdown("Enter a query to find websites and scrape their contact information. Results are saved to a raw log, and unique contacts are added to the cleaned data list.")
    query = st.text_input("Enter your search query (e.g., 'Hospitals in Hyderabad'):")

    if st.button("Search & Scrape"):
        if not query:
            st.warning("Please enter a search query!")
            return

        client, db = get_db_connection()
        if not client:
            return

        try:
            with st.spinner("Searching Google and scraping websites..."):
                results = google_search(query, num_results=10)
                
                progress_bar = st.progress(0, text="Scraping websites...")
                for i, item in enumerate(results):
                    website = item.get("url")
                    contact_page = find_contact_page(website)
                    item["contact_info"] = scrape_contact_page(contact_page)
                    progress_bar.progress((i + 1) / len(results), text=f"Scraped: {website}")

            st.info("Saving results to the database...")
            df = process_and_save_results(results, query, db)
            st.success("✅ Scraping and saving process completed!")
            
            st.subheader("Scraped Data from this Session")
            st.dataframe(df)
            
            if not df.empty:
                st.download_button(
                    "Download Session Data (CSV)", 
                    df.to_csv(index=False).encode("utf-8"), 
                    file_name=f"scraped_{query.replace(' ','_')}.csv"
                )
        finally:
            if client: client.close()

if __name__ == '__main__':
    main()
