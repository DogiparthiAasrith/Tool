import streamlit as st
import pandas as pd
import psycopg2
from io import StringIO
from openai import OpenAI

# ===============================
# CONFIGURATION
# ===============================
POSTGRES_URL = "postgresql://neondb_owner:npg_onVe8gqWs4lm@ep-solitary-bush-addf9gpm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

try:
    # Recommended for deployment: set secrets in Streamlit Cloud
    client = OpenAI(api_key=st.secrets["openai"]["api_key"])
except Exception:
    # For local development
    client = OpenAI(api_key="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")

# ===============================
# HELPER FUNCTIONS
# ===============================
def get_db_connection():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ *Database Connection Error:* {e}")
        return None

def fetch_cleaned_contacts(conn):
    try:
        return pd.read_sql("SELECT * FROM cleaned_contacts ORDER BY id DESC", conn)
    except (Exception, psycopg2.DatabaseError):
        st.warning("⚠ Could not fetch contacts. The 'cleaned_contacts' table might not exist yet.")
        return pd.DataFrame()

# ===============================
# EMAIL GENERATION LOGIC (WITH FALLBACK)
# ===============================
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
    """Tries to use OpenAI, but falls back to hardcoded templates on any failure."""
    name = contact_details.get('name')
    domain = contact_details.get('domain', 'their industry')
    linkedin = contact_details.get('linkedin_url', '')
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"

    try:
        # We still try to use the AI first.
        prompt = f"""
        Write a professional and concise outreach email. My name is Aasrith from Morphius AI (morphius.in).
        The email is for {name or 'a professional'} in the {domain} sector. Their LinkedIn is {linkedin}.
        Start with "{greeting}", briefly introduce Morphius AI's relevance to their industry, express interest in connecting, and keep it under 150 words.
        End with: "Best regards,\nAasrith\nEmployee, Morphius AI\nhttps://www.morphius.in/"
        """
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a business development expert crafting personalized outreach emails."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300, temperature=0.75,
        )
        # If this line is reached, the API call was successful.
        return response.choices[0].message.content.strip()

    except Exception as e:
        # --- CORRECTED FALLBACK LOGIC ---
        # If the API fails for ANY reason (401 key error, server down, etc.),
        # this block will run instead of showing an error.
        st.warning(f"⚠️ OpenAI API failed. Using a pre-written template instead. (Error: {e})")
        return get_fallback_template(domain, name)

# ===============================
# MAIN STREAMLIT APP (No changes below this line)
# ===============================
def main():
    st.title("Generate & Edit Email Drafts")

    if 'edited_emails' not in st.session_state:
        st.session_state.edited_emails = []

    conn = get_db_connection()
    if not conn:
        return

    contacts_df = fetch_cleaned_contacts(conn)
    conn.close()

    if contacts_df.empty:
        st.info("No cleaned contacts found. Go to 'Show Cleaned Data' to process contacts first.")
        return

    st.header("Step 1: Select Contacts & Generate Drafts")

    if 'contacts_df' not in st.session_state:
        st.session_state.contacts_df = contacts_df.copy()
        if 'Select' not in st.session_state.contacts_df.columns:
            st.session_state.contacts_df.insert(0, "Select", False)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("✅ Select All", use_container_width=True):
            st.session_state.contacts_df["Select"] = True
            st.rerun()
    with col2:
        if st.button("❌ Deselect All", use_container_width=True):
            st.session_state.contacts_df["Select"] = False
            st.rerun()

    edited_df = st.data_editor(
        st.session_state.contacts_df,
        hide_index=True,
        disabled=st.session_state.contacts_df.columns.drop("Select")
    )

    st.session_state.contacts_df = edited_df
    selected_rows = st.session_state.contacts_df[st.session_state.contacts_df['Select']]

    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty):
        st.session_state.edited_emails = []
        with st.spinner("Generating drafts..."):
            for _, row in selected_rows.iterrows():
                to_email = row.get('work_emails') or row.get('personal_emails')
                if not to_email or pd.isna(to_email):
                    continue

                body = generate_personalized_email_body(row)
                st.session_state.edited_emails.append({
                    "id": row['id'], "name": row['name'], "to_email": to_email,
                    "subject": "Connecting from Morphius AI", "body": body,
                    "contact_details": row.to_dict()
                })

    if st.session_state.edited_emails:
        st.header("Step 2: Review and Edit Drafts")
        st.info("Edit the drafts directly, use 'Regenerate Body' for a new AI version, or 'Clear & Write Manually' to start from scratch.")

        if st.button("👁 View All Drafts Together", use_container_width=True):
            st.subheader("All Generated Drafts")
            for email_draft in st.session_state.edited_emails:
                st.markdown(f"### ✉ {email_draft['name']} (<{email_draft['to_email']}>)")
                st.markdown(f"*Subject:* {email_draft['subject']}")
                st.text_area( "Body", value=email_draft['body'], height=250, key=f"viewall_body_{email_draft['id']}",)
                st.markdown("---")

        for i, email_draft in enumerate(st.session_state.edited_emails):
            with st.expander(f"Draft for: {email_draft['name']} <{email_draft['to_email']}>", expanded=True):
                st.session_state.edited_emails[i]['subject'] = st.text_input(
                    "Subject", value=email_draft['subject'], key=f"subject_{i}"
                )
                st.session_state.edited_emails[i]['body'] = st.text_area(
                    "Body", value=email_draft['body'], height=250, key=f"body_{i}"
                )

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 Regenerate Body", key=f"regen_{i}", use_container_width=True):
                        with st.spinner("Asking AI for a new version..."):
                            new_body = generate_personalized_email_body(email_draft['contact_details'])
                            st.session_state.edited_emails[i]['body'] = new_body
                            st.toast(f"Generated a new draft for {email_draft['name']}!")
                        st.rerun()

                with col2:
                    if st.button("✍ Clear & Write Manually", key=f"clear_{i}", use_container_width=True):
                        manual_template = f"Hi {email_draft.get('name', '')},\n\n\n\nBest regards,\nAasrith\nFounder, Morphius AI\nhttps://www.morphius.in/"
                        st.session_state.edited_emails[i]['body'] = manual_template
                        st.toast(f"Cleared draft for {email_draft['name']}. You can now write manually.")
                        st.rerun()

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

