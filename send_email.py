import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from io import StringIO
from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ===============================
# HELPER & CALLBACK FUNCTIONS
# ===============================
def get_db_connection():
    try:
        client_mongo = MongoClient(MONGO_URI)
        client_mongo.admin.command('ismaster')
        db = client_mongo[MONGO_DB_NAME]
        return client_mongo, db
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
# AI-POWERED LOGIC
# ===============================
def decode_prompt_to_domain(prompt):
    try:
        system_message = """
        You are an expert business analyst. Your task is to analyze the user's prompt and identify the core business domain.
        Respond with ONLY a single, lowercase keyword for the domain. If unclear, respond 'general'.
        """
        response = client.chat.completions.create(
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
        st.error(f"Could not analyze prompt due to an API error: {e}")
        return None

def get_fallback_marketing_template(domain, name, unsubscribe_link, help_link):
    greeting = f"Hi {name}," if name.strip() else "Dear Sir/Madam,"
    body = f"""{greeting}

I noticed your work in the {domain} sector. At Morphius AI, we help companies like yours improve workflows and reduce manual effort. I'd love to share a quick 2-slide overview showing how you can achieve better results in less time.

Would you be open to a 15-min chat next week?

Best regards,
Aasrith
Employee, Morphius AI
https://www.morphius.in/

---
To unsubscribe: {unsubscribe_link}
Need help? {help_link}
"""
    return body

def generate_personalized_email_body(contact_details):
    """Generates marketing-style email with compliance footer."""
    name = contact_details.get('name', '')
    domain = contact_details.get('domain', 'their industry')
    company_name = contact_details.get('company_name', '')
    role = contact_details.get('role', '')
    linkedin = contact_details.get('linkedin_url', '')

    unsubscribe_link = f"https://yourdomain.com/unsubscribe?email={contact_details.get('work_emails', '')}"
    help_link = "https://yourdomain.com/help"

    greeting = f"Hi {name}," if name.strip() else "Dear Sir/Madam,"
    signature = f"""

Best regards,
Aasrith
Employee, Morphius AI
https://www.morphius.in/

---
To unsubscribe from future emails, click here: {unsubscribe_link}
Need help? Visit: {help_link}
"""

    prompt = f"""
Write a professional, concise marketing outreach email (≤120 words) in a friendly, engaging tone.
- Personalize with: Name={name}, Role={role}, Company={company_name}, Industry={domain}
- Include: 1 clear CTA (15-min call), problem statement, and value proposition
- Include compliance footer with unsubscribe & help links
- Start with greeting: "{greeting}"
- End with signature: "{signature}"
- Output ONLY email body text, ready to copy-paste
LinkedIn: {linkedin}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional marketing copywriter. Write clear, concise outreach emails."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=350,
            temperature=0.7,
        )
        email_body = response.choices[0].message.content.strip()
        return email_body

    except Exception as e:
        st.warning(f"⚠ OpenAI API failed. Using fallback marketing template. (Error: {e})")
        return get_fallback_marketing_template(domain, name, unsubscribe_link, help_link)

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("Internal Client Acquisition Tool – Email Generator")

    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []
    if 'filter_domain' not in st.session_state:
        st.session_state.filter_domain = None

    client_mongo, db = get_db_connection()
    if not client_mongo:
        return

    st.header("Step 1: Find Contacts with AI")
    prompt = st.text_input("Enter prompt to filter contacts (e.g., 'top 10 colleges in Hyderabad')", key="prompt_input")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Filter from Prompt"):
            if prompt:
                with st.spinner("Analyzing prompt and filtering..."):
                    domain = decode_prompt_to_domain(prompt)
                    if domain and domain != 'general':
                        st.session_state.filter_domain = domain
                        st.success(f"Filtered for domain: *{domain}*")
                    else:
                        st.session_state.filter_domain = None
                        st.info("Prompt too general. Showing all contacts.")
                st.rerun()
            else:
                st.warning("Please enter a prompt first.")
    with col2:
        if st.button("🔄 Show All Contacts"):
            st.session_state.filter_domain = None
            st.rerun()

    st.header("Step 2: Select Contacts & Generate Drafts")
    contacts_df = fetch_cleaned_contacts(db)
    client_mongo.close()

    if contacts_df.empty:
        st.info("No cleaned contacts found.")
        return

    display_df = contacts_df.copy()
    if st.session_state.filter_domain:
        display_df = display_df[display_df['domain'].str.contains(st.session_state.filter_domain, case=False, na=False)]
        st.info(f"Showing {len(display_df)} contacts matching domain '{st.session_state.filter_domain}'")

    if 'Select' not in display_df.columns:
        display_df.insert(0, "Select", False)

    select_all = st.checkbox("Select All Contacts", value=display_df['Select'].all())
    display_df['Select'] = select_all or display_df['Select']

    editor_key = f"data_editor_{st.session_state.filter_domain or 'all'}_{len(contacts_df)}"
    disabled_cols = list(display_df.columns.drop("Select"))

    edited_df = st.data_editor(display_df, hide_index=True, disabled=disabled_cols, key=editor_key)
    selected_rows = edited_df[edited_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty):
        st.session_state.edited_emails = []
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
                st.warning(f"⚠️ Skipped '{row.get('name', 'Unknown')}', no valid email found.")
                continue

            with st.spinner(f"Generating draft for {row['name']}..."):
                body = generate_personalized_email_body(row)
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
            unique_id_for_keys = email_draft['id']
            regen_count = email_draft['regen_counter']
            with st.expander(f"Draft for: {email_draft['name']} <{email_draft['to_email']}>", expanded=True):
                st.text_input(
                    "Subject",
                    value=email_draft['subject'],
                    key=f"subject_{unique_id_for_keys}_{regen_count}",
                    on_change=update_subject,
                    args=(i, unique_id_for_keys)
                )
                st.text_area(
                    "Body",
                    value=email_draft['body'],
                    height=250,
                    key=f"body_{unique_id_for_keys}_{regen_count}",
                    on_change=update_body,
                    args=(i, unique_id_for_keys)
                )

                b_col1, b_col2 = st.columns(2)
                with b_col1:
                    if st.button("🔄 Regenerate Body", key=f"regen_{unique_id_for_keys}_{regen_count}", use_container_width=True):
                        with st.spinner("Generating new AI draft..."):
                            new_body = generate_personalized_email_body(email_draft['contact_details'])
                            st.session_state.edited_emails[i]['body'] = new_body
                            st.session_state.edited_emails[i]['regen_counter'] += 1
                        st.rerun()
                with b_col2:
                    if st.button("✍ Clear & Write Manually", key=f"clear_{unique_id_for_keys}_{regen_count}", use_container_width=True):
                        manual_template = f"Hi {email_draft.get('name', '')},\n\n\n\nBest regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/\n\nTo unsubscribe: [link]\nHelp: [link]"
                        st.session_state.edited_emails[i]['body'] = manual_template
                        st.session_state.edited_emails[i]['regen_counter'] += 1
                        st.rerun()

        st.markdown("### 📥 Download All Drafts")
        df_export = pd.DataFrame(st.session_state.edited_emails)[["name", "to_email", "subject", "body"]]
        csv_buffer = StringIO()
        df_export.to_csv(csv_buffer, index=False)
        st.download_button(
            label="⬇ Download Drafts as CSV",
            data=csv_buffer.getvalue(),
            file_name="morphius_email_drafts.csv",
            mime="text/csv"
        )

        st.success("✅ All changes saved. Review and send emails via the final preview.")

if __name__ == "__main__":
    main()
