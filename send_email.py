import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from io import StringIO
from openai import OpenAI
import os
from dotenv import load_dotenv
from urllib.parse import quote
import yagmail  # For sending HTML emails with attachments/styles

# ===============================
# LOAD CONFIG
# ===============================
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
client_ai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Your Gmail credentials for sending emails
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

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
            st.session_state.edited_emails[i]['subject'] = st.session_state.get(widget_key, '')
            break

def update_body(index, email_id):
    for i, email_draft in enumerate(st.session_state.edited_emails):
        if email_draft['id'] == email_id:
            widget_key = f"body_{email_id}_{email_draft['regen_counter']}"
            st.session_state.edited_emails[i]['body'] = st.session_state.get(widget_key, '')
            break

# ===============================
# AI-POWERED LOGIC
# ===============================
def decode_prompt_to_domain(prompt):
    try:
        system_message = "You are an expert business analyst. Respond with ONLY a lowercase keyword for the domain. If uncertain, respond with 'general'."
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10, temperature=0.1,
        )
        return response.choices[0].message.content.strip().lower()
    except Exception as e:
        st.error(f"OpenAI API Error: {e}")
        return None

def get_fallback_template(domain, name):
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    signature = "\n\nBest regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    domain_str = str(domain).lower()
    if "edtech" in domain_str:
        body = "I came across your profile in the EdTech space. At Morphius AI, we personalize learning outcomes.\n\nI would be keen to connect."
    elif "commerce" in domain_str:
        body = "I noticed your experience in e-commerce. Morphius AI creates AI tools to enhance customer engagement.\n\nA brief chat could be mutually beneficial."
    else:
        body = f"I was interested in your work in the {domain} sector. Morphius AI builds AI solutions across industries.\n\nI would be delighted to connect."
    return f"{greeting}\n\n{body}{signature}"

def generate_personalized_email_body(contact_details):
    name = contact_details.get('name')
    domain = contact_details.get('domain', 'their industry')
    linkedin = contact_details.get('linkedin_url', '')
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    # The signature will be handled by the HTML wrapper, so we don't need it here.
    try:
        prompt = f"""
        Write a professional and concise outreach email body for a person named {name} in the {domain} sector. Their LinkedIn profile is {linkedin}.
        My name is Aasrith from Morphius AI.
        
        Your entire response should be ONLY the main content of the email.
        DO NOT include the greeting (like "Hi {name},") or a closing (like "Best regards,"). Just write the core paragraphs.
        Keep the main message under 120 words.
        """
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a business development assistant. You only write the core message of an email, without greetings or signatures."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300, temperature=0.75,
        )
        # Combine the greeting with the generated body
        return f"{greeting}\n\n{response.choices[0].message.content.strip()}"
    except Exception as e:
        st.warning(f"⚠ OpenAI API failed. Using fallback template. (Error: {e})")
        return get_fallback_template(domain, name)

# ===============================
# HTML EMAIL FORMATTING & SENDING
# ===============================
def wrap_body_in_html(to_email, body_text):
    """Wraps plain text in a professional HTML template with an unsubscribe link."""
    # Convert plain text line breaks to HTML paragraphs
    paragraphs = body_text.split("\n\n")
    html_paragraphs = "".join([f'<p style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">{p.strip()}</p>' for p in paragraphs if p.strip()])
    
    # URL-encode the recipient's email for the unsubscribe link
    encoded_email = quote(to_email)
    
    # This is a placeholder URL. You would need a web service to handle unsubscribe requests.
    unsubscribe_url = f"https://your-website.com/unsubscribe?email={encoded_email}"
    
    footer_html = (
        f'<p style="font-family: Arial, sans-serif; font-size: 12px; color: #777; margin-top: 30px;">'
        f'Best regards,<br>'
        f'<strong>Aasrith D.</strong><br>'
        f'Morphius AI<br>'
        f'<a href="https://www.morphius.in/">www.morphius.in</a>'
        f'</p>'
        f'<p style="font-family: Arial, sans-serif; font-size: 10px; color: #aaa; margin-top: 20px;">'
        f'If you do not wish to receive further job posting notifications, <a href="{unsubscribe_url}">unsubscribe now</a>.'
        f'</p>'
    )
    
    return f"<html><body style='line-height: 1.6;'>{html_paragraphs}{footer_html}</body></html>"

def send_email_html(to_email, subject, body_text):
    """Sends an email using yagmail, wrapping the body text in HTML."""
    try:
        # Initialize yagmail with your credentials
        yag = yagmail.SMTP(GMAIL_USER, GMAIL_APP_PASSWORD)
        # Wrap the plain text body in our HTML template
        html_content = wrap_body_in_html(to_email, body_text)
        # Send the email
        yag.send(to=to_email, subject=subject, contents=html_content)
        return True
    except Exception as e:
        st.error(f"⚠ Failed to send email to {to_email}: {e}")
        return False

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("📧 Morphius AI: Email Campaign Tool")

    # Initialize session state variables
    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []
    if 'filter_domain' not in st.session_state:
        st.session_state.filter_domain = None

    client_mongo, db = get_db_connection()
    if not client_mongo: return

    st.header("Step 1: Filter Contacts")
    prompt = st.text_input("Describe the contacts you're looking for (e.g., 'e-commerce startups')", key="prompt_input")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Filter from Prompt", use_container_width=True):
            if prompt:
                domain = decode_prompt_to_domain(prompt)
                st.session_state.filter_domain = domain if domain and domain != 'general' else None
                st.rerun()
    with col2:
        if st.button("🔄 Show All Contacts", use_container_width=True):
            st.session_state.filter_domain = None
            st.rerun()

    st.header("Step 2: Select Contacts & Generate Drafts")
    contacts_df = fetch_cleaned_contacts(db)
    client_mongo.close()
    if contacts_df.empty:
        st.info("No contacts found in the database.")
        return

    display_df = contacts_df.copy()
    if st.session_state.filter_domain:
        display_df = contacts_df[contacts_df['domain'].str.contains(st.session_state.filter_domain, case=False, na=False)].copy()
        st.info(f"Showing {len(display_df)} contacts matching '{st.session_state.filter_domain}'")

    if 'Select' not in display_df.columns:
        display_df.insert(0, "Select", False)

    edited_df = st.data_editor(display_df, hide_index=True, disabled=list(display_df.columns.drop("Select")), key="data_editor")
    selected_rows = edited_df[edited_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty):
        st.session_state.edited_emails = []
        for i, row in selected_rows.iterrows():
            to_email = None
            # Prioritize work email, then personal
            work_email = row.get('work_emails')
            if isinstance(work_email, str) and work_email.strip():
                to_email = work_email.split(',')[0].strip()
            if not to_email:
                personal_email = row.get('personal_emails')
                if isinstance(personal_email, str) and personal_email.strip():
                    to_email = personal_email.split(',')[0].strip()
            
            if not to_email:
                st.warning(f"⚠️ Skipped '{row.get('name', 'Unknown')}' - no valid email found.")
                continue

            with st.spinner(f"Generating draft for {row.get('name', 'Unknown')}..."):
                body = generate_personalized_email_body(row.to_dict())
            
            st.session_state.edited_emails.append({
                "id": i, "name": row['name'], "to_email": to_email,
                "subject": "Connecting from Morphius AI", "body": body,
                "contact_details": row.to_dict(), "regen_counter": 0
            })
        st.rerun()

    if st.session_state.edited_emails:
        st.header("Step 3: Review, Edit & Send")
        for i, email_draft in enumerate(st.session_state.edited_emails):
            unique_id = email_draft['id']
            regen_count = email_draft['regen_counter']
            with st.expander(f"Draft for {email_draft['name']} <{email_draft['to_email']}>", expanded=True):
                st.text_input("Subject", value=email_draft['subject'], key=f"subject_{unique_id}_{regen_count}", on_change=update_subject, args=(i, unique_id))
                st.text_area("Body (Plain Text for Editing)", value=email_draft['body'], height=250, key=f"body_{unique_id}_{regen_count}", on_change=update_body, args=(i, unique_id))
        
        st.divider()
        if st.button(f"🚀 Send {len(st.session_state.edited_emails)} Emails Now", type="primary", use_container_width=True):
            if not GMAIL_USER or not GMAIL_APP_PASSWORD:
                st.error("GMAIL_USER and GMAIL_APP_PASSWORD are not set in your environment variables.")
                return

            success_count = 0
            progress_bar = st.progress(0, text="Initializing...")
            for i, email_to_send in enumerate(st.session_state.edited_emails):
                progress_text = f"Sending email {i+1}/{len(st.session_state.edited_emails)} to {email_to_send['name']}..."
                progress_bar.progress((i + 1) / len(st.session_state.edited_emails), text=progress_text)
                if send_email_html(email_to_send['to_email'], email_to_send['subject'], email_to_send['body']):
                    success_count += 1
            
            st.success(f"Campaign complete! Sent {success_count} out of {len(st.session_state.edited_emails)} emails.")
            st.session_state.edited_emails = []
            st.rerun()

if __name__ == "__main__":
    main()
