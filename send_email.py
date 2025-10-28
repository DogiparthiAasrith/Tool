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

def fetch_unsubscribed_emails(db):
    """Fetches emails from both unsubscribe collections."""
    unsubscribed = set()
    try:
        # Fetch from manual unsubscribe link clicks
        cursor1 = db.unsubscribed_emails.find({}, {'email': 1})
        for doc in cursor1:
            if 'email' in doc and isinstance(doc['email'], str):
                unsubscribed.add(doc['email'].strip().lower())

        # Fetch from follow-up unsubscribe list
        cursor2 = db.unsubscribe_list.find({}, {'email': 1})
        for doc in cursor2:
            if 'email' in doc and isinstance(doc['email'], str):
                unsubscribed.add(doc['email'].strip().lower())
        
        return unsubscribed
    except Exception as e:
        st.warning(f"⚠ Could not fetch unsubscribe lists. Error: {e}")
        return set()

def remove_email_from_unsubscribe_lists(db, email):
    """Removes an email from both unsubscribe collections."""
    try:
        email_lower = email.strip().lower()
        # Case-insensitive removal
        db.unsubscribed_emails.delete_many({'email': {'$regex': f'^{email_lower}$', '$options': 'i'}})
        db.unsubscribe_list.delete_many({'email': {'$regex': f'^{email_lower}$', '$options': 'i'}})
        return True
    except Exception as e:
        st.error(f"Failed to remove {email} from unsubscribe lists: {e}")
        return False

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
# UNSUBSCRIBE HELPER
# ===============================
def append_unsubscribe_link(body_text, recipient_email):
    unsubscribe_link = f"\n\nIf you prefer not to receive future emails, you can unsubscribe here: https://unsubscribe-52pwl9yyy-gowthami-gs-projects.vercel.app/unsubscribe?email={quote(recipient_email)}"
    return body_text.strip() + unsubscribe_link


# ===============================
# AI-POWERED LOGIC
# ===============================
def get_fallback_template(domain, name, email=""):
    greeting = f"Dear Sir/Madam,"
    signature = "\n\nBest regards,\nD.Aasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    if "edtech" in str(domain).lower():
        body = f"I came across your profile in the EdTech space. At Morphius AI, we personalize learning and improve educational outcomes.\n\nI would be keen to connect and share insights."
    elif "commerce" in str(domain).lower():
        body = f"I noticed your experience in e-commerce. Morphius AI creates AI-driven tools that enhance customer engagement and optimize online retail.\n\nA brief chat about industry trends could be mutually beneficial."
    elif "health" in str(domain).lower():
        body = f"Your work in healthcare is impressive. At Morphius AI, we leverage AI to streamline diagnostics and improve patient care pathways.\n\nI would value a discussion on healthcare technology."
    else:
        body = f"I came across your profile and was interested in your work in the {domain} sector. Morphius AI builds AI solutions across industries.\n\nI would be delighted to connect."

    final_body = f"{greeting}\n\n{body}{signature}"
    return append_unsubscribe_link(final_body, email)


def generate_personalized_email_body(contact_details):
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
        body = get_fallback_template(domain, name, email)

    # Append unsubscribe link
    return append_unsubscribe_link(body, email)


# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("📧 Morphius AI — Email Automation")

    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []

    client_mongo, db = get_db_connection()
    if not client_mongo:
        return

    # Fetch all contacts and unsubscribe lists
    unsubscribed_emails_set = fetch_unsubscribed_emails(db)
    all_contacts_df = fetch_cleaned_contacts(db)

    if all_contacts_df.empty:
        st.info("No contacts found in the database.")
        return

    # Helper to check if a contact's emails are in the unsubscribe set
    def is_email_subscribed(email_str):
        if not isinstance(email_str, str) or not email_str.strip():
            return True
        emails = [e.strip().lower() for e in email_str.split(',')]
        return not any(e in unsubscribed_emails_set for e in emails)

    # Separate subscribed and unsubscribed contacts
    subscribed_mask = all_contacts_df['work_emails'].apply(is_email_subscribed) & \
                      all_contacts_df['personal_emails'].apply(is_email_subscribed)
    
    contacts_df = all_contacts_df[subscribed_mask].copy()
    unsubscribed_df = all_contacts_df[~subscribed_mask].copy()

    # Display unsubscribed contacts and resubscribe option
    if not unsubscribed_df.empty:
        with st.expander(f"ℹ️ {len(unsubscribed_df)} Unsubscribed Contacts"):
            for _, row in unsubscribed_df.iterrows():
                unsubscribed_emails_in_row = []
                work_emails = row.get('work_emails', '')
                personal_emails = row.get('personal_emails', '')

                if isinstance(work_emails, str):
                    for email in work_emails.split(','):
                        if email.strip().lower() in unsubscribed_emails_set:
                            unsubscribed_emails_in_row.append(email.strip())
                
                if isinstance(personal_emails, str):
                    for email in personal_emails.split(','):
                        if email.strip().lower() in unsubscribed_emails_set:
                            unsubscribed_emails_in_row.append(email.strip())
                
                for email_to_resubscribe in set(unsubscribed_emails_in_row):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{row.get('name', 'N/A')}**: {email_to_resubscribe}")
                    with col2:
                        if st.button("Resubscribe", key=f"resub_{email_to_resubscribe}"):
                            if remove_email_from_unsubscribe_lists(db, email_to_resubscribe):
                                st.toast(f"'{email_to_resubscribe}' has been resubscribed.")
                                st.rerun()
                            # Error is handled within the function

    st.header("Step 1: Select Contacts & Generate Drafts")
    if contacts_df.empty:
        st.info("No available contacts to display.")
        client_mongo.close()
        return

    display_df = contacts_df.copy()
    if 'Select' not in display_df.columns:
        display_df.insert(0, "Select", False)

    select_all = st.checkbox("Select All Contacts", value=False)
    if select_all:
        display_df['Select'] = True

    edited_df = st.data_editor(display_df, hide_index=True, disabled=list(display_df.columns.drop("Select")), key="data_editor")
    selected_rows = edited_df[edited_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty, use_container_width=True):
        st.session_state.edited_emails = []
        with st.spinner("Generating email drafts..."):
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
                body = generate_personalized_email_body(row)
                st.session_state.edited_emails.append({
                    "id": i, "name": row['name'], "to_email": to_email,
                    "subject": "Connecting from Morphius AI", "body": body,
                    "contact_details": row.to_dict(),
                    "regen_counter": 0
                })
        st.rerun()

    if st.session_state.edited_emails:
        st.header("Step 2: Review & Edit Drafts")
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

    client_mongo.close()

if __name__ == "__main__":
    main()
