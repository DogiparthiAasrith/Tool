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
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        db = client[MONGO_DB_NAME]
        return client, db
    except ConnectionFailure as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None, None

def fetch_cleaned_contacts(db):
    try:
        cursor = db.cleaned_contacts.find().sort('_id', -1)
        df = pd.DataFrame(list(cursor))
        # Keep the original mongo ID for potential reference, but don't show it
        if '_id' in df.columns:
            df.rename(columns={'_id': 'mongo_id'}, inplace=True)
        return df
    except Exception as e:
        st.warning(f"⚠ Could not fetch contacts. The 'cleaned_contacts' collection might not exist yet. Error: {e}")
        return pd.DataFrame()

# --- CALLBACKS FOR STATE MANAGEMENT ---
def update_subject(index):
    """Callback to update the subject in the session state."""
    widget_key = f"subject_{index}"
    st.session_state.edited_emails[index]['subject'] = st.session_state[widget_key]

def update_body(index):
    """Callback to update the body in the session state."""
    widget_key = f"body_{index}"
    st.session_state.edited_emails[index]['body'] = st.session_state[widget_key]

# ===============================
# AI-POWERED LOGIC
# ===============================
def decode_prompt_to_domain(prompt):
    """Uses OpenAI to analyze a prompt and extract a business domain keyword."""
    try:
        system_message = """
        You are an expert business analyst. Your task is to analyze the user's prompt and identify the core business domain or industry sector.
        Respond with ONLY a single, lowercase keyword for the domain.
        Examples:
        - Prompt: "Top 10 colleges in Hyderabad" -> edtech
        - Prompt: "E-commerce startups" -> commerce
        - Prompt: "Hospitals in Delhi" -> health
        - Prompt: "Investment banks" -> finance
        - Prompt: "Car companies" -> automotive
        If you cannot determine a clear domain, respond with 'general'.
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

def get_fallback_template(domain, name):
    """Selects a pre-written template based on the contact's domain."""
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    signature = "\n\nBest regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"

    domain_lower = str(domain).lower()

    if "edtech" in domain_lower or "education" in domain_lower:
        body = f"I came across your profile and was impressed by your work in the EdTech space. At Morphius AI, we're developing innovative solutions to personalize learning and improve educational outcomes.\n\nI believe our work aligns with your expertise and would be keen to connect and share insights."
    elif "commerce" in domain_lower or "retail" in domain_lower:
        body = f"I noticed your experience in the e-commerce sector and wanted to reach out. Morphius AI specializes in creating AI-driven tools that enhance customer engagement and optimize online retail operations.\n\nGiven your background, I thought a brief chat about the trends shaping the industry could be mutually beneficial."
    elif "health" in domain_lower or "medical" in domain_lower:
        body = f"Your work in the healthcare industry is truly impressive. At Morphius AI, we are focused on leveraging artificial intelligence to streamline diagnostics and improve patient care pathways.\n\nI would value the opportunity to connect with an expert like yourself to discuss the future of healthcare technology."
    else: # This is the "common mail for other domains"
        body = f"I came across your profile and was interested in your work in the {domain} sector. At Morphius AI, we build AI solutions to tackle challenges across various industries, and I'm always keen to connect with professionals like yourself.\n\nI would be delighted to connect and learn more about your experience."

    return f"{greeting}\n\n{body}{signature}"

def generate_personalized_email_body(contact_details):
    """The PRIMARY generation function. Uses GPT-4o for the highest quality first draft."""
    name = contact_details.get('name')
    domain = contact_details.get('domain', 'their industry')
    linkedin = contact_details.get('linkedin_url', '')
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    signature = "\n\nBest regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"

    try:
        prompt = f"""
        Write a professional and concise outreach email body.
        The target is {name or 'a professional'} in the {domain} sector. LinkedIn: {linkedin}.
        My name is Aasrith from Morphius AI.

        Your entire response should be ONLY the email content, following these rules precisely:
        1. Start the email body directly with the greeting: "{greeting}"
        2. After the greeting, add the main message. Briefly introduce Morphius AI's relevance to their industry and express interest in connecting. Keep this main part under 120 words.
        3. End the email body with the exact closing: "{signature}"

        Do NOT include a "Subject:" line or any other text outside of the email body itself. Your output should be ready to be pasted directly into an email.
        """
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a business development assistant. Your only job is to write the full text for an email body as instructed, without any extra text or formatting."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300, temperature=0.75,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        st.warning(f"⚠ OpenAI API failed. Using a pre-written template instead. (Error: {e})")
        return get_fallback_template(domain, name)

def regenerate_email_body(contact_details):
    """The REGENERATION function. Uses GPT-3.5-Turbo for a fast, alternative draft."""
    name = contact_details.get('name')
    domain = contact_details.get('domain', 'their industry')
    linkedin = contact_details.get('linkedin_url', '')
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    signature = "\n\nBest regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"

    try:
        prompt = f"""
        Write a direct and concise outreach email body.
        The target is {name or 'a professional'} in the {domain} sector. LinkedIn: {linkedin}.
        My name is Aasrith from Morphius AI.

        Your entire response should be ONLY the email content, following these rules precisely:
        1. Start the email body directly with the greeting: "{greeting}"
        2. Get straight to the point about Morphius AI and why you're connecting. Keep this main part under 90 words.
        3. End the email body with the exact closing: "{signature}"

        Do NOT include a "Subject:" line or any other text.
        """
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a business development assistant who writes direct and to-the-point emails."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=250, temperature=0.7,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        st.warning(f"⚠ OpenAI API (alternative) failed. Using a pre-written template instead. (Error: {e})")
        return get_fallback_template(domain, name)

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.title("Generate & Edit Email Drafts")

    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []
    if 'filter_domain' not in st.session_state:
        st.session_state.filter_domain = None

    client, db = get_db_connection()
    if not client:
        return

    st.header("Step 1: Find Contacts with AI")
    st.markdown("Describe the contacts you're looking for to automatically filter the list by industry.")
    
    prompt = st.text_input("Enter your prompt (e.g., 'top 10 colleges in Hyderabad' or 'e-commerce startups')", key="prompt_input")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Filter from Prompt", use_container_width=True):
            if prompt:
                with st.spinner("Analyzing prompt and filtering..."):
                    domain = decode_prompt_to_domain(prompt)
                    if domain and domain != 'general':
                        st.session_state.filter_domain = domain
                        st.success(f"Successfully filtered for domain: *{domain}*")
                    else:
                        st.session_state.filter_domain = None
                        st.info("Prompt was too general or could not be analyzed. Showing all contacts.")
                st.rerun()
            else:
                st.warning("Please enter a prompt first.")
    with col2:
        if st.button("🔄 Show All Contacts", use_container_width=True):
            st.session_state.filter_domain = None
            st.rerun()

    st.header("Step 2: Select Contacts & Generate Drafts")
    
    contacts_df = fetch_cleaned_contacts(db)
    client.close()

    if contacts_df.empty:
        st.info("No cleaned contacts found. Go to 'Collect Contacts' to add some.")
        return

    if st.session_state.filter_domain:
        display_df = contacts_df[contacts_df['domain'].str.contains(st.session_state.filter_domain, case=False, na=False)].copy()
        st.info(f"Showing {len(display_df)} of {len(contacts_df)} contacts matching the domain '{st.session_state.filter_domain}'")
    else:
        display_df = contacts_df.copy()

    if 'Select' not in display_df.columns:
        display_df.insert(0, "Select", False)

    select_all = st.checkbox("Select All Contacts")
    if select_all:
        display_df['Select'] = True

    editor_key = f"data_editor_{st.session_state.filter_domain or 'all'}"
    disabled_cols = list(display_df.columns.drop("Select"))

    edited_df = st.data_editor(
        display_df, hide_index=True, disabled=disabled_cols, key=editor_key
    )
    
    selected_rows = edited_df[edited_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty):
        st.session_state.edited_emails = []
        with st.spinner("Generating drafts with GPT-4o..."):
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
                    st.warning(f"⚠️ Skipped '{row.get('name', 'Unknown Contact')}' because no valid email was found.")
                    continue

                body = generate_personalized_email_body(row)
                st.session_state.edited_emails.append({
                    "id": i, "name": row['name'], "to_email": to_email,
                    "subject": "Connecting from Morphius AI", "body": body,
                    "contact_details": row.to_dict()
                })

    if st.session_state.edited_emails:
        st.header("Step 3: Review and Edit Drafts")
        st.info("Edit the drafts directly, regenerate a new version, or clear the text to write your own.")

        def handle_regenerate(index):
            email_draft = st.session_state.edited_emails[index]
            with st.spinner("Asking AI (GPT-3.5) for a new version..."):
                new_body = regenerate_email_body(email_draft['contact_details'])
                st.session_state.edited_emails[index]['body'] = new_body
                st.toast(f"Generated a new draft for {email_draft['name']}!")

        # --- CALLBACK FOR THE CLEAR BUTTON ---
        def handle_clear(index):
            email_draft = st.session_state.edited_emails[index]
            manual_template = f"Hi {email_draft.get('name', '')},\n\n\n\nBest regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
            st.session_state.edited_emails[index]['body'] = manual_template
            st.toast(f"Cleared draft for {email_draft['name']}. You can now write manually.")

        for i, email_draft in enumerate(st.session_state.edited_emails):
            with st.expander(f"Draft for: {email_draft['name']} <{email_draft['to_email']}>", expanded=True):
                
                st.text_input(
                    "Subject",
                    value=email_draft['subject'],
                    key=f"subject_{i}",
                    on_change=update_subject,
                    args=(i,)
                )
                st.text_area(
                    "Body",
                    value=email_draft['body'],
                    height=250,
                    key=f"body_{i}",
                    on_change=update_body,
                    args=(i,)
                )

                # --- TWO-COLUMN LAYOUT FOR BUTTONS ---
                b_col1, b_col2 = st.columns(2)
                with b_col1:
                    st.button(
                        "🔄 Regenerate", 
                        key=f"regen_{i}", 
                        on_click=handle_regenerate, 
                        args=(i,), 
                        use_container_width=True
                    )
                
                with b_col2:
                    st.button(
                        "✍️ Clear & Write Manually",
                        key=f"clear_{i}",
                        on_click=handle_clear,
                        args=(i,),
                        use_container_width=True
                    )

        st.markdown("### 📥 Download All Drafts")
        if st.session_state.edited_emails:
            df_export = pd.DataFrame(st.session_state.edited_emails)[["name", "to_email", "subject", "body"]]
            csv_buffer = StringIO()
            df_export.to_csv(csv_buffer, index=False)
            st.download_button(
                label="⬇ Download Drafts as CSV", data=csv_buffer.getvalue(),
                file_name="morphius_email_drafts.csv", mime="text/csv", use_container_width=True
            )

        st.success("✅ All changes saved. Proceed to the 'Email Preview' page to send the final emails.")

if __name__ == "__main__":
    main()
