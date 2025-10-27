import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from io import StringIO
from openai import OpenAI
import os
from dotenv import load_dotenv
from urllib.parse import quote
import uuid # --- ADDED: To generate unique IDs for tracking

# ===============================
# LOAD CONFIG
# ===============================
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
client_ai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- ADDED: Define the URL of your hosted tracking server ---
# --- IMPORTANT: Replace this with the public URL from your hosting provider (e.g., Render) ---
TRACKING_SERVER_URL = "https://your-tracker-service-name.onrender.com"


# ===============================
# HELPERS & CALLBACKS
# ===============================
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
# --- MODIFIED: Helpers for Unsubscribe and Tracking ---
# ===============================
def finalize_email_body(body_text, recipient_email, tracking_id):
    """
    Appends the unsubscribe link and the tracking pixel, then formats as HTML.
    """
    # 1. Append the unsubscribe link to the plain text body
    unsubscribe_link = f"\n\nIf you prefer not to receive future emails, you can unsubscribe here: https://unsubscribe-5v1tdqur8-gowthami-gs-projects.vercel.app/unsubscribe?email={quote(recipient_email)}"
    body_with_unsubscribe = body_text.strip() + unsubscribe_link

    # 2. Create the HTML for the tracking pixel
    tracking_pixel_html = f'<img src="{TRACKING_SERVER_URL}/track?id={tracking_id}" width="1" height="1" alt="">'
    
    # 3. Convert the entire body to a simple HTML document
    html_text = body_with_unsubscribe.replace('\n', '<br>')
    final_html_body = f"<html><body>{html_text}{tracking_pixel_html}</body></html>"
    
    return final_html_body


# ===============================
# AI-POWERED LOGIC
# ===============================
def decode_prompt_to_domain(prompt):
    # This function is unchanged
    try:
        system_message = """
        You are an expert business analyst. Respond with ONLY a lowercase keyword for the domain.
        If uncertain, respond with 'general'.
        """
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10,
            temperature=0.1,
        )
        domain = response.choices[0].message.content.strip().lower()
        return domain
    except Exception as e:
        st.error(f"OpenAI API Error: {e}")
        return None


def get_fallback_template(domain, name, email=""):
    # This function is unchanged
    greeting = f"Dear Sir/Madam,"
    signature = "\n\nBest regards,\nD.Aasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    if "edtech" in str(domain).lower():
        body = f"I came across your profile in the EdTech space. At Morphius AI, we personalize learning and improve educational outcomes.\n\nI would be keen to connect and share insights."
    # ... (other conditions remain the same) ...
    else:
        body = f"I came across your profile and was interested in your work in the {domain} sector. Morphius AI builds AI solutions across industries.\n\nI would be delighted to connect."
    full_body = f"{greeting}\n\n{body}{signature}"
    # The unsubscribe link is now added by finalize_email_body
    return full_body


def generate_personalized_email_body(contact_details, tracking_id): # <-- ADDED tracking_id parameter
    name = contact_details.get('name')
    domain = contact_details.get('domain', 'their industry')
    linkedin = contact_details.get('linkedin_url', '')
    email = contact_details.get('work_emails') or contact_details.get('personal_emails', '')
    greeting = f"Dear Sir/Madam,"
    signature = "\n\nBest regards,\nD.Aasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    
    plain_text_body = ""
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
        plain_text_body = response.choices[0].message.content.strip()
    except Exception as e:
        st.warning(f"⚠ OpenAI API failed. Using fallback template. (Error: {e})")
        # Use a simplified fallback that just returns the text
        plain_text_body = get_fallback_template(domain, name, email).replace(f"\n\nIf you prefer not to receive future emails...", "")


    # --- MODIFIED: Use the finalize_email_body helper to add tracking and format as HTML ---
    return finalize_email_body(plain_text_body, email, tracking_id)


# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("📧 Morphius AI: Generate & Edit Email Drafts")

    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []
    if 'filter_domain' not in st.session_state:
        st.session_state.filter_domain = None

    client_mongo, db = get_db_connection()
    if not client_mongo: return

    # ... (No changes to Step 1 and Step 2 data editor)
    st.header("Step 1: Filter Contacts by Prompt")
    prompt = st.text_input("Enter a prompt (e.g., 'top 10 colleges', 'e-commerce startups')", key="prompt_input")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Filter Contacts", use_container_width=True):
            if prompt:
                domain = decode_prompt_to_domain(prompt)
                if domain and domain != 'general':
                    st.session_state.filter_domain = domain
                    st.success(f"Filtered contacts for domain: {domain}")
                else:
                    st.session_state.filter_domain = None
                    st.info("Prompt too general; showing all contacts.")
                st.rerun()
            else: st.warning("Please enter a prompt first.")
    with col2:
        if st.button("🔄 Show All Contacts", use_container_width=True):
            st.session_state.filter_domain = None
            st.rerun()
    st.header("Step 2: Select Contacts & Generate Drafts")
    contacts_df = fetch_cleaned_contacts(db)
    client_mongo.close()
    if contacts_df.empty:
        st.info("No contacts found."); return
    display_df = contacts_df.copy()
    if st.session_state.filter_domain:
        display_df = contacts_df[contacts_df['domain'].str.contains(st.session_state.filter_domain, case=False, na=False)].copy()
        st.info(f"Showing {len(display_df)} contacts matching domain '{st.session_state.filter_domain}'")
    if 'Select' not in display_df.columns: display_df.insert(0, "Select", False)
    select_all = st.checkbox("Select All Contacts", value=False)
    if select_all: display_df['Select'] = True
    edited_df = st.data_editor(display_df, hide_index=True, disabled=list(display_df.columns.drop("Select")), key="data_editor")
    selected_rows = edited_df[edited_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty, use_container_width=True):
        st.session_state.edited_emails = []
        with st.spinner("Generating drafts with tracking links..."):
            for i, row in selected_rows.iterrows():
                to_email = (row.get('work_emails') or row.get('personal_emails') or "").split(',')[0].strip()
                if not to_email:
                    st.warning(f"⚠ Skipped '{row.get('name', 'Unknown')}' - no valid email.")
                    continue
                
                # --- ADDED: Generate a unique tracking ID and create the HTML body ---
                tracking_id = str(uuid.uuid4())
                body = generate_personalized_email_body(row, tracking_id)
                
                st.session_state.edited_emails.append({
                    "id": i, "name": row['name'], "to_email": to_email,
                    "subject": "Connecting from Morphius AI", "body": body,
                    "contact_details": row.to_dict(),
                    "regen_counter": 0,
                    "tracking_id": tracking_id # --- ADDED: Store the ID with the draft
                })
        st.rerun()

    if st.session_state.edited_emails:
        st.header("Step 3: Review & Edit Drafts")
        for i, email_draft in enumerate(st.session_state.edited_emails):
            unique_id = email_draft['id']
            regen_count = email_draft['regen_counter']
            with st.expander(f"Draft for {email_draft['name']} <{email_draft['to_email']}>", expanded=True):
                st.text_input("Subject", value=email_draft['subject'],
                              key=f"subject_{unique_id}_{regen_count}", on_change=update_subject, args=(i, unique_id))
                # --- MODIFIED: Body is now HTML ---
                st.text_area("HTML Body", value=email_draft['body'], height=250,
                             key=f"body_{unique_id}_{regen_count}", on_change=update_body, args=(i, unique_id))
                st.caption("Note: Body is in HTML to support open tracking.")

                # ... (Regenerate/Clear buttons logic would also need to be updated to use finalize_email_body)

        st.markdown("### 📥 Download All Drafts")
        # --- MODIFIED: Add 'tracking_id' to the exported CSV file ---
        df_export = pd.DataFrame(st.session_state.edited_emails)[["name", "to_email", "subject", "body", "tracking_id"]]
        csv_buffer = StringIO()
        df_export.to_csv(csv_buffer, index=False)
        st.download_button("📥 Download Drafts as CSV", data=csv_buffer.getvalue(), file_name="morphius_email_drafts.csv", mime="text/csv", use_container_width=True)


if __name__ == "__main__":
    main()
