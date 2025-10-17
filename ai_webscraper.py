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
# CONFIGURATION & CONSTANTS
# ===============================
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
CLEANED_COLLECTION_NAME = "cleaned_contacts"

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
PHONE_REGEX = r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"

# ===============================
# DATABASE & HELPER FUNCTIONS
# ===============================
def get_db_connection():
    """Establishes and returns a connection to the MongoDB database."""
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None, None

def google_search(query, num_results=5):
    """Performs a Google search using the SerpAPI."""
    params = {"q": query, "api_key": SERPAPI_API_KEY, "num": num_results}
    search = GoogleSearch(params)
    results = search.get_dict().get("organic_results", [])
    return [{"title": r.get("title"), "url": r.get("link"), "snippet": r.get("snippet")} for r in results]

def find_contact_page(website_url):
    """Finds a 'contact' page link from a website's homepage."""
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
        return None
    return website_url # Return base url if no contact page is found

def scrape_contact_page(contact_url):
    """Scrapes emails and phone numbers from a contact page."""
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

def save_to_cleaned_mongo(db, dict_data):
    """Saves a single contact record to the cleaned_contacts collection, avoiding duplicates based on source_url."""
    # **FIX:** Ensure source_url exists before saving
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
        contact_name = dict_data.get("name") or "Unknown"
        if result.upserted_id:
            st.success(f"✅ Added new unique contact '{contact_name}' from Web Scraper.")
        else:
            st.info(f"ℹ️ Contact '{contact_name}' already exists in cleaned data.")
    except Exception as e:
        # Catch the specific duplicate key error on the off-chance it happens
        if "E11000" in str(e):
             st.warning(f"ℹ️ Contact '{dict_data.get('name', 'Unknown')}' already exists (duplicate source URL).")
        else:
            st.error(f"❌ Error during cleaned save operation: {e}")

def save_and_process_results(results, query, db):
    """Processes scraped results, saves them to MongoDB, and returns a DataFrame for display."""
    rows_for_display = []
    
    for item in results:
        contact_info = item.get("contact_info", {})
        
        # **FIX:** Prepare data for the unified 'cleaned_contacts' collection
        cleaned_data = {
            "name": item.get("title", ""),
            "source_url": (item.get("url") or "").rstrip('/'), # This is the unique key
            "emails": ", ".join(contact_info.get("emails", [])),
            "phones": ", ".join(contact_info.get("phones", [])),
            "domain": (item.get("url") or "").split('/')[2] if item.get("url") else None,
            "source": "Web Scraper", # **FIX:** Add the data source
            "created_at": dt.datetime.now(dt.timezone.utc)
        }
        save_to_cleaned_mongo(db, cleaned_data)

        # Prepare a row for the session's results table
        row_for_display = {
            "query": query,
            "company_name": item.get("title", ""),
            "website_url": item.get("url", ""),
            "emails": ", ".join(contact_info.get("emails", [])),
            "phones": ", ".join(contact_info.get("phones", [])),
        }
        rows_for_display.append(row_for_display)

    return pd.DataFrame(rows_for_display)

# ===============================
# STREAMLIT UI
# ===============================
def main():
    """Main function to run the Streamlit UI for the AI Web Scraper."""
    st.title("🕸 AI Web Scraper")
    st.markdown("Enter a query (e.g., 'Manufacturing companies in California') to find websites and scrape their contact information.")
    query = st.text_input("Enter your search query:")

    if st.button("Search & Scrape"):
        if not query:
            st.warning("Please enter a search query!")
            return

        client, db = get_db_connection()
        if not client:
            return

        try:
            with st.spinner("Searching Google and scraping websites... This may take a moment."):
                results = google_search(query, num_results=10)
                
                progress_bar = st.progress(0, text="Scraping websites...")
                for i, item in enumerate(results):
                    website = item.get("url")
                    contact_page = find_contact_page(website)
                    item["contact_info"] = scrape_contact_page(contact_page)
                    progress_bar.progress((i + 1) / len(results), text=f"Scraped: {website}")

            st.info("Saving results to the database...")
            df = save_and_process_results(results, query, db)
            st.success("✅ Scraping and saving process completed!")
            st.dataframe(df)
            
            if not df.empty:
                st.download_button(
                    "Download Scraped Session Data (CSV)", 
                    df.to_csv(index=False).encode("utf-8"), 
                    file_name=f"scraped_{query.replace(' ','_')}.csv"
                )
        finally:
            if client:
                client.close()

if __name__ == '__main__':
    main()
