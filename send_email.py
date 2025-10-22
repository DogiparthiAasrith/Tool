import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from io import StringIO
from openai import OpenAI
import os
from dotenv import load_dotenv
from urllib.parse import quote

# ===============================
# LOAD CONFIG
# ===============================
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
client_ai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ===============================
# HELPERS & CALLBACKS
# ===============================
def get_db_connection():
    try:
        client = MongoClient(MONGO_URI)
        # The ping command is a cheap way to check if the connection is alive.
        client.admin.command('ping')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ Database Connection Error: {e}")
        return None, None
    except Exception as e:
        st.error(f"❌ An unexpected error occurred during database connection: {e}")
        return None, None

def get_unsubscribed_emails_from_db(db):
    """Fetches all unsubscribed emails from the 'unsubscribed_users' collection."""
    try:
        cursor = db.unsubscribed_users.find({}, {'email': 1, '_id': 0})
        return {doc['email'] for doc in cursor if 'email' in doc}
    except Exception as e:
        st.warning(f"⚠ Could not fetch unsubscribed emails. Error: {e}")
        return set()

def add_email_to_unsubscribe_db(db, email):
    """Adds an email to the 'unsubscribed_users' collection if not already present."""
    if not email or not isinstance(email, str) or '@' not in email:
        return False, "Invalid email address."
    try:
        # Check if email already exists
        if db.unsubscribed_users.count_documents({'email': email}) == 0:
            db.unsubscribed_users.insert_one({'email': email, 'timestamp': pd.Timestamp.utcnow()})
            return True, f"'{email}' added to unsubscribe list."
        else:
            return False, f"'{email}' is already in the unsubscribe list."
    except Exception as e:
        return False, f"Error adding '{email}' to unsubscribe list: {e}"

def remove_email_from_unsubscribe_db(db, email):
    """Removes an email from the 'unsubscribed_users' collection."""
    if not email or not isinstance(email, str) or '@' not in email:
        return False, "Invalid email address."
    try:
        result = db.unsubscribed_users.delete_one({'email': email})
        if result.deleted_count > 0:
            return True, f"'{email}' removed from unsubscribe list."
        else:
            return False, f"'{email}' not found in unsubscribe list."
    except Exception as e:
        return False, f"Error removing '{email}' from unsubscribe list: {e}"


def fetch_cleaned_contacts(db):
    """
    Fetches contacts and filters out those who have unsubscribed.
    """
    try:
        # First, get the list of unsubscribed emails
        unsubscribed_emails = get_unsubscribed_emails_from_db(db)

        # Fetch all contacts
        cursor = db.cleaned_contacts.find().sort('_id', -1)
        df = pd.DataFrame(list(cursor))

        if df.empty:
            return pd.DataFrame()

        # Rename _id for display
        if '_id' in df.columns:
            df.rename(columns={'_id': 'mongo_id'}, inplace=True)

        # Filter out unsubscribed contacts
        initial_count = len(df)
        if unsubscribed_emails:
            # Create a boolean mask for rows where either work_emails or personal_emails are in the unsubscribed set
            # Handle cases where 'work_emails' or 'personal_emails' might be lists or comma-separated strings
            def is_unsubscribed(row):
                all_emails_for_contact = set()
                work_emails_val = row.get('work_emails')
                if isinstance(work_emails_val, str):
                    all_emails_for_contact.update(e.strip() for e in work_emails_val.split(',') if e.strip())
                elif isinstance(work_emails_val, list):
                    all_emails_for_contact.update(e.strip() for e in work_emails_val if e.strip())

                personal_emails_val = row.get('personal_emails')
                if isinstance(personal_emails_val, str):
                    all_emails_for_contact.update(e.strip() for e in personal_emails_val.split(',') if e.strip())
                elif isinstance(personal_emails_val, list):
                    all_emails_for_contact.update(e.strip() for e in personal_emails_val if e.strip())

                return any(email in unsubscribed_emails for email in all_emails_for_contact)

            unsubscribed_mask = df.apply(is_unsubscribed, axis=1)
            df = df[~unsubscribed_mask]
            st.info(f"Filtered out {initial_count - len(df)} unsubscribed contacts.")

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
# UNSUBSCRIBE HELPER (Corrected for Better Compatibility)
# ===============================
def append_unsubscribe_link(body_text, recipient_email):
    """
    Appends a more compatible mailto link for unsubscribing. It pre-fills
    only the recipient and subject, which is more reliable across email clients.
    """
    # !!! IMPORTANT: Make sure this email address is correct !!!
    unsubscribe_inbox = "thridorbit03@gmail.com"
    
    # URL-encode only the subject. The subject line is sufficient for the request.
    # Optionally, you could include the recipient_email in the subject to make tracking easier
    subject_content = f"Unsubscribe Request from {recipient_email}" if recipient_email else "Unsubscribe Request"
    subject = quote(subject_content)
    
    # Create a simpler mailto link without the 'body' parameter.
    # This is much more likely to work correctly everywhere.
    mailto_link = f"mailto:{unsubscribe_inbox}?subject={subject}"
    
    # Create the unsubscribe text to be appended to the email body
    unsubscribe_text = f"\n\nIf you prefer not to receive future emails, you can unsubscribe here: {mailto_link}"
    
    return body_text.strip() + unsubscribe_text


# ===============================
# AI-POWERED LOGIC
# ===============================
def decode_prompt_to_domain(prompt):
    try:
        system_message = """
        You are an expert business analyst. Respond with ONLY a lowercase keyword for the domain.
        If uncertain, respond with 'general'.
        Examples:
        'top 10 colleges' -> 'edtech'
        'e-commerce startups' -> 'commerce'
        'hospital innovation' -> 'health'
        'finance management software' -> 'finance'
        'digital marketing agencies' -> 'marketing'
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
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    signature = "\n\nBest regards,\nD.Aasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    domain_lower = str(domain).lower()
    if "edtech" in domain_lower:
        body = f"I came across your profile in the EdTech space. At Morphius AI, we personalize learning and improve educational outcomes.\n\nI would be keen to connect and share insights."
    elif "commerce" in domain_lower:
        body = f"I noticed your experience in e-commerce. Morphius AI creates AI-driven tools that enhance customer engagement and optimize online retail.\n\nA brief chat about industry trends could be mutually beneficial."
    elif "health" in domain_lower:
        body = f"Your work in healthcare is impressive. At Morphius AI, we leverage AI to streamline diagnostics and improve patient care pathways.\n\nI would value a discussion on healthcare technology."
    elif "finance" in domain_lower:
        body = f"I observed your expertise in the finance sector. Morphius AI develops cutting-edge AI solutions for financial analysis and risk management.\n\nI'd be interested in discussing potential collaborations."
    elif "marketing" in domain_lower:
        body = f"Your innovative approach to marketing caught my eye. Morphius AI offers advanced AI tools to boost campaign performance and audience engagement.\n\nLet's connect to explore how we can drive results."
    else:
        body = f"I came across your profile and was interested in your work in the {domain_lower} sector. Morphius AI builds AI solutions across industries.\n\nI would be delighted to connect."

    final_body = f"{greeting}\n\n{body}{signature}"
    return append_unsubscribe_link(final_body, email)


def generate_personalized_email_body(contact_details):
    name = contact_details.get('name')
    domain = contact_details.get('domain', 'their industry')
    linkedin = contact_details.get('linkedin_url', '')
    email = contact_details.get('work_emails') or contact_details.get('personal_emails', '')
    
    # Ensure email is a string, take the first one if multiple are present
    if isinstance(email, list) and email:
        email = email[0]
    elif not isinstance(email, str):
        email = ""

    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    signature = "\n\nBest regards,\nD.Aasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    try:
        prompt = f"""
        Write a professional outreach email for {name} in the {domain} sector. LinkedIn: {linkedin}.
        Start with: "{greeting}" and end with "{signature}".
        Keep the email concise and focused on a potential collaboration or discussion related to Morphius AI's capabilities in their specific domain.
        """
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a business development assistant. Only output the email body. Do not include subject line or salutation/signature in your output."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300, temperature=0.75,
        )
        body = response.choices[0].message.content.strip()
        # Prepend greeting and append signature as they are part of the prompt structure
        full_body = f"{greeting}\n\n{body}{signature}"
    except Exception as e:
        st.warning(f"⚠ OpenAI API failed. Using fallback template. (Error: {e})")
        full_body = get_fallback_template(domain, name, email)

    # Append the dynamic unsubscribe link to every generated email body
    return append_unsubscribe_link(full_body, email)


# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.set_page_config(layout="wide")
    st.title("📧 Morphius AI: Generate & Edit Email Drafts")

    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []
    if 'filter_domain' not in st.session_state:
        st.session_state.filter_domain = None

    client_mongo, db = get_db_connection()
    if not client_mongo:
        st.error("Cannot connect to MongoDB. Please check MONGO_URI and MONGO_DB_NAME in your .env file.")
        return

    # --- Unsubscribe Management Section ---
    st.sidebar.header("🚫 Unsubscribe Management")
    unsub_email_input = st.sidebar.text_input("Enter email to unsubscribe:", key="unsub_email_input")
    col_add, col_remove = st.sidebar.columns(2)
    with col_add:
        if st.button("➕ Add to Unsubscribe", key="add_unsub_btn", use_container_width=True, help="Manually add an email to the unsubscribe list based on requests received."):
            if unsub_email_input:
                success, message = add_email_to_unsubscribe_db(db, unsub_email_input.strip().lower())
                if success:
                    st.sidebar.success(message)
                    st.session_state.unsub_email_input = "" # Clear input
                    st.rerun()
                else:
                    st.sidebar.error(message)
            else:
                st.sidebar.warning("Please enter an email address.")
    with col_remove:
        if st.button("➖ Remove from Unsubscribe", key="remove_unsub_btn", use_container_width=True, help="Remove an email from the unsubscribe list."):
            if unsub_email_input:
                success, message = remove_email_from_unsubscribe_db(db, unsub_email_input.strip().lower())
                if success:
                    st.sidebar.info(message)
                    st.session_state.unsub_email_input = "" # Clear input
                    st.rerun()
                else:
                    st.sidebar.warning(message)
            else:
                st.sidebar.warning("Please enter an email address.")

    st.sidebar.subheader("Current Unsubscribed Emails:")
    current_unsubscribed = get_unsubscribed_emails_from_db(db)
    if current_unsubscribed:
        for i, email in enumerate(sorted(list(current_unsubscribed))):
            st.sidebar.text(f"- {email}")
    else:
        st.sidebar.info("No emails in the unsubscribe list.")
    st.sidebar.markdown("---") # Separator


    st.header("Step 1: Filter Contacts by Prompt")
    prompt = st.text_input("Enter a prompt (e.g., 'top 10 colleges', 'e-commerce startups')", key="prompt_input")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Filter Contacts", use_container_width=True):
            if prompt:
                with st.spinner("Decoding prompt..."):
                    domain = decode_prompt_to_domain(prompt)
                if domain and domain != 'general':
                    st.session_state.filter_domain = domain
                    st.success(f"Filtered contacts for domain: {domain}")
                else:
                    st.session_state.filter_domain = None
                    st.info("Prompt too general or domain not found; showing all contacts.")
                st.rerun()
            else:
                st.warning("Please enter a prompt first.")
    with col2:
        if st.button("🔄 Show All Contacts", use_container_width=True):
            st.session_state.filter_domain = None
            st.rerun()

    st.header("Step 2: Select Contacts & Generate Drafts")
    contacts_df = fetch_cleaned_contacts(db)
    
    if contacts_df.empty:
        st.info("No contacts found (or all contacts are unsubscribed for the current filter).")
        client_mongo.close()
        return

    display_df = contacts_df.copy()
    if st.session_state.filter_domain:
        display_df = contacts_df[contacts_df['domain'].str.contains(st.session_state.filter_domain, case=False, na=False)].copy()
        if not display_df.empty:
            st.info(f"Showing {len(display_df)} contacts matching domain '{st.session_state.filter_domain}'")
        else:
            st.info(f"No contacts found for domain '{st.session_state.filter_domain}' after filtering unsubscribed users.")
            client_mongo.close()
            return


    if 'Select' not in display_df.columns:
        display_df.insert(0, "Select", False)

    select_all = st.checkbox("Select All Contacts", value=False)
    if select_all:
        display_df['Select'] = True

    edited_df = st.data_editor(display_df, hide_index=True, disabled=list(display_df.columns.drop("Select")), key="data_editor")
    selected_rows = edited_df[edited_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty, use_container_width=True):
        with st.spinner(f"Generating {len(selected_rows)} email drafts..."):
            st.session_state.edited_emails = []
            for i, row in selected_rows.iterrows():
                to_email = None
                
                # Prioritize work_emails
                work_email_val = row.get('work_emails')
                if isinstance(work_email_val, str) and work_email_val.strip():
                    to_email = work_email_val.split(',')[0].strip()
                elif isinstance(work_email_val, list) and work_email_val:
                    to_email = work_email_val[0].strip()

                # Fallback to personal_emails if no work_email found
                if not to_email:
                    personal_email_val = row.get('personal_emails')
                    if isinstance(personal_email_val, str) and personal_email_val.strip():
                        to_email = personal_email_val.split(',')[0].strip()
                    elif isinstance(personal_email_val, list) and personal_email_val:
                        to_email = personal_email_val[0].strip()
                
                if not to_email:
                    st.warning(f"⚠ Skipped '{row.get('name', 'Unknown')}' - no valid email found in 'work_emails' or 'personal_emails'.")
                    continue
                
                # Ensure the email is not in the unsubscribed list BEFORE generating
                if to_email.lower() in get_unsubscribed_emails_from_db(db):
                    st.info(f"Skipped '{row.get('name', 'Unknown')}' <{to_email}> - this email is unsubscribed.")
                    continue

                body = generate_personalized_email_body(row.to_dict())
                st.session_state.edited_emails.append({
                    "id": i, "name": row['name'], "to_email": to_email,
                    "subject": "Connecting from Morphius AI", "body": body,
                    "contact_details": row.to_dict(),
                    "regen_counter": 0
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
                st.text_area("Body", value=email_draft['body'], height=250,
                             key=f"body_{unique_id}_{regen_count}", on_change=update_body, args=(i, unique_id))

                b_col1, b_col2 = st.columns(2)
                with b_col1:
                    if st.button("🔄 Regenerate Body", key=f"regen_{unique_id}_{regen_count}", use_container_width=True):
                        with st.spinner("Generating a new draft..."):
                            new_body = generate_personalized_email_body(email_draft['contact_details'])
                        st.session_state.edited_emails[i]['body'] = new_body
                        st.session_state.edited_emails[i]['regen_counter'] += 1
                        st.toast(f"Generated a new draft for {email_draft['name']}!")
                        st.rerun()
                with b_col2:
                    if st.button("✍ Clear & Write Manually", key=f"clear_{unique_id}_{regen_count}", use_container_width=True):
                        manual_template = f"Hi {email_draft.get('name', '')},\n\n\n\nBest regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
                        manual_template = append_unsubscribe_link(manual_template, email_draft['to_email'])
                        st.session_state.edited_emails[i]['body'] = manual_template
                        st.session_state.edited_emails[i]['regen_counter'] += 1
                        st.toast(f"Cleared draft for {email_draft['name']}.")
                        st.rerun()

        st.markdown("### 📥 Download All Drafts")
        df_export = pd.DataFrame(st.session_state.edited_emails)[["name", "to_email", "subject", "body"]]
        csv_buffer = StringIO()
        df_export.to_csv(csv_buffer, index=False)
        st.download_button("📥 Download Drafts as CSV", data=csv_buffer.getvalue(), file_name="morphius_email_drafts.csv", mime="text/csv", use_container_width=True)
    
    client_mongo.close() # Close connection when app finishes
    

if __name__ == "__main__":
    main()
