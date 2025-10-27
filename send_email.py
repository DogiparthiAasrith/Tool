import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from io import StringIO
from openai import OpenAI
import os
from dotenv import load_dotenv
from urllib.parse import quote
import uuid # --- IMPORT UUID FOR UNIQUE TRACKING IDS ---

# ===============================
# LOAD CONFIG
# ===============================
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
client_ai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- ADD YOUR TRACKING SERVER URL ---
TRACKING_SERVER_URL = "http://127.0.0.1:5001" # Use your server's public IP/domain in production

# ... (rest of your helper functions: get_db_connection, fetch_cleaned_contacts, etc.) ...
def get_db_connection():
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ Database Connection Error: {e}")
        return None, None


def fetch_cleaned_contacts(db):
    try:
        cursor = db.cleaned_contacts.find().sort('_id', -1)
        df = pd.DataFrame(list(cursor))
        if '_id' in df.columns:
            df.rename(columns={'_id': 'mongo_id'}, inplace=True)
        return df
    except Exception as e:
        st.warning(f"⚠ Could not fetch contacts. Error: {e}")
        return pd.DataFrame()


def update_subject(index, email_id):
    for i, email_draft in enumerate(st.session_state.edited_emails):
        if email_draft['id'] == email_id:
            widget_key = f"subject_{email_id}_{email_draft['regen_counter']}"
            st.session_state.edited_emails[i]['subject'] = st.session_state[widget_key]
            break


def update_body(index, email_id):
    for i, email_draft in enumerate(st.session_state.edited_emails):
        if email_draft['id'] == email_id:
            widget_key = f"body_{email_id}_{email_draft['regen_counter']}"
            st.session_state.edited_emails[i]['body'] = st.session_state[widget_key]
            break


# ===============================
# MODIFIED UNSUBSCRIBE & TRACKING HELPER
# ===============================
def finalize_email_body(body_text, recipient_email, tracking_id):
    # 1. Add the unsubscribe link
    unsubscribe_link = f"\n\nIf you prefer not to receive future emails, you can unsubscribe here: https://unsubscribe-5v1tdqur8-gowthami-gs-projects.vercel.app/unsubscribe?email={quote(recipient_email)}"
    final_body = body_text.strip() + unsubscribe_link

    # 2. Add the tracking pixel (as HTML)
    tracking_pixel_html = f'<img src="{TRACKING_SERVER_URL}/track?id={tracking_id}" width="1" height="1" alt="">'
    
    # Wrap body in HTML tags to ensure pixel is rendered
    html_body = f"<html><body><p>{final_body.replace(chr(10), '<br>')}</p>{tracking_pixel_html}</body></html>"
    
    return html_body


# ===============================
# MODIFIED AI-POWERED LOGIC
# ===============================
def generate_personalized_email_body(contact_details, tracking_id): # <-- Pass tracking_id
    name = contact_details.get('name')
    domain = contact_details.get('domain', 'their industry')
    linkedin = contact_details.get('linkedin_url', '')
    email = contact_details.get('work_emails') or contact_details.get('personal_emails', '')
    greeting = f"Dear Sir/Madam,"
    signature = "\n\nBest regards,\nD.Aasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    try:
        prompt = f"""
        Write a professional outreach email for {name} in the {domain} sector. LinkedIn: {linkedin}.
        Start with: "{greeting}" and end with "{signature}".
        """
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a business development assistant. Only output the email body."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300, temperature=0.75,
        )
        body = response.choices[0].message.content.strip()
    except Exception as e:
        st.warning(f"⚠ OpenAI API failed. Using fallback template. (Error: {e})")
        # --- A simplified fallback ---
        body = f"{greeting}\n\nI came across your profile and was interested in your work. At Morphius AI, we build AI solutions and I would be delighted to connect.{signature}"

    # Finalize body with unsubscribe link and tracking pixel
    return finalize_email_body(body, email, tracking_id)


# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("📧 Morphius AI: Generate & Edit Email Drafts")

    # ... (rest of your main function up to the "Generate Drafts" button) ...
    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []
    if 'filter_domain' not in st.session_state:
        st.session_state.filter_domain = None

    client_mongo, db = get_db_connection()
    if not client_mongo:
        return

    st.header("Step 1: Filter Contacts by Prompt")
    prompt = st.text_input("Enter a prompt (e.g., 'top 10 colleges', 'e-commerce startups')", key="prompt_input")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Filter Contacts", use_container_width=True):
            if prompt:
                # Assuming decode_prompt_to_domain exists and works
                # domain = decode_prompt_to_domain(prompt) 
                domain = "general" # Simplified for example
                if domain and domain != 'general':
                    st.session_state.filter_domain = domain
                    st.success(f"Filtered contacts for domain: {domain}")
                else:
                    st.session_state.filter_domain = None
                    st.info("Prompt too general; showing all contacts.")
                st.rerun()
            else:
                st.warning("Please enter a prompt first.")
    with col2:
        if st.button("🔄 Show All Contacts", use_container_width=True):
            st.session_state.filter_domain = None
            st.rerun()

    st.header("Step 2: Select Contacts & Generate Drafts")
    contacts_df = fetch_cleaned_contacts(db)
    client_mongo.close()
    if contacts_df.empty:
        st.info("No contacts found.")
        return

    display_df = contacts_df.copy()
    if st.session_state.filter_domain:
        display_df = contacts_df[contacts_df['domain'].str.contains(st.session_state.filter_domain, case=False, na=False)].copy()
        st.info(f"Showing {len(display_df)} contacts matching domain '{st.session_state.filter_domain}'")

    if 'Select' not in display_df.columns:
        display_df.insert(0, "Select", False)

    select_all = st.checkbox("Select All Contacts", value=False)
    if select_all:
        display_df['Select'] = True

    edited_df = st.data_editor(display_df, hide_index=True, disabled=list(display_df.columns.drop("Select")), key="data_editor")
    selected_rows = edited_df[edited_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty, use_container_width=True):
        st.session_state.edited_emails = []
        with st.spinner("Generating personalized drafts..."):
            for i, row in selected_rows.iterrows():
                to_email = None
                work_email_val = row.get('work_emails')
                if isinstance(work_email_val, str) and work_email_val.strip():
                    to_email = work_email_val.split(',')[0].strip()
                if not to_email:
                    personal_email_val = row.get('personal_emails')
                    if isinstance(personal_email_val, str) and personal_email_val.strip():
                        to_email = personal_email_val.split(',')[0].strip()
                if not to_email:
                    st.warning(f"⚠ Skipped '{row.get('name', 'Unknown')}' - no valid email.")
                    continue
                
                # --- GENERATE A UNIQUE TRACKING ID ---
                tracking_id = str(uuid.uuid4())
                
                # --- PASS ID TO BODY GENERATOR ---
                body = generate_personalized_email_body(row, tracking_id) 
                
                st.session_state.edited_emails.append({
                    "id": i, "name": row['name'], "to_email": to_email,
                    "subject": "Connecting from Morphius AI", 
                    "body": body, # This body now contains HTML
                    "contact_details": row.to_dict(),
                    "regen_counter": 0,
                    "tracking_id": tracking_id # --- STORE THE ID ---
                })
        st.rerun()

    if st.session_state.edited_emails:
        st.header("Step 3: Review & Edit Drafts")
        # --- Display HTML in the text area ---
        for i, email_draft in enumerate(st.session_state.edited_emails):
             with st.expander(f"Draft for {email_draft['name']} <{email_draft['to_email']}>", expanded=True):
                st.text_input("Subject", value=email_draft['subject'], key=f"subject_{email_draft['id']}")
                st.text_area("HTML Body", value=email_draft['body'], height=300, key=f"body_{email_draft['id']}")
                st.caption("Note: The body is now in HTML to support open tracking.")

        st.markdown("### 📥 Download All Drafts")
        # --- ADD tracking_id to the CSV ---
        df_export = pd.DataFrame(st.session_state.edited_emails)[["name", "to_email", "subject", "body", "tracking_id"]]
        csv_buffer = StringIO()
        df_export.to_csv(csv_buffer, index=False)
        st.download_button("📥 Download Drafts as CSV", data=csv_buffer.getvalue(), file_name="morphius_email_drafts.csv", mime="text/csv", use_container_width=True)


if __name__ == "__main__":
    main()
