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


def generate_personalized_email_body(contact_details):
    name = contact_details.get('name')
    greeting = f"Hi {name}," if pd.notna(name) and name.strip() else "Dear Sir/Madam,"
    domain = contact_details.get('domain', 'your industry')
    linkedin = contact_details.get('linkedin_url', '')

    prompt = f"""
    Write a professional and concise outreach email. My name is Gowthami from Morphius AI (morphius.in).
    The email is for {name or 'a professional'} in the {domain} sector. Their LinkedIn is {linkedin}.
    Start with "{greeting}", briefly introduce Morphius AI's relevance to their industry, express interest in connecting, and keep it under 150 words.
    End with: "Best regards,\nGowthami\nEmployee, Morphius AI\nhttps://www.morphius.in/"
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a business development expert crafting personalized outreach emails."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300, temperature=0.75,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"❌ OpenAI Error for {name}: {e}")
        return "Error generating email. Please try again."


# ===============================
# MAIN STREAMLIT APP
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

    # ===============================
    # STEP 1: SELECT CONTACTS & GENERATE DRAFTS
    # ===============================
    st.header("Step 1: Select Contacts & Generate Drafts")

    if 'contacts_df' not in st.session_state:
        st.session_state.contacts_df = contacts_df.copy()
        if 'Select' not in st.session_state.contacts_df.columns:
            st.session_state.contacts_df.insert(0, "Select", False)

    # --- Add Select / Deselect All Buttons ---
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("✅ Select All", use_container_width=True):
            st.session_state.contacts_df["Select"] = True
    with col2:
        if st.button("❌ Deselect All", use_container_width=True):
            st.session_state.contacts_df["Select"] = False

    # --- Editable Table ---
    edited_df = st.data_editor(
        st.session_state.contacts_df,
        hide_index=True,
        disabled=st.session_state.contacts_df.columns.drop("Select")
    )

    # Update session data when edits happen manually
    st.session_state.contacts_df = edited_df

    # --- Get Selected Rows ---
    selected_rows = st.session_state.contacts_df[st.session_state.contacts_df['Select']]

    # --- Generate Drafts Button ---
    if st.button(f"Generate Drafts for {len(selected_rows)} Selected Contacts", disabled=selected_rows.empty):
        st.session_state.edited_emails = []
        with st.spinner("Generating personalized drafts..."):
            for _, row in selected_rows.iterrows():
                to_email = row.get('work_emails') or row.get('personal_emails')
                if not to_email or pd.isna(to_email):
                    continue

                body = generate_personalized_email_body(row)
                st.session_state.edited_emails.append({
                    "id": row['id'],
                    "name": row['name'],
                    "to_email": to_email,
                    "subject": "Connecting from Morphius AI",
                    "body": body,
                    "contact_details": row.to_dict()
                })

    # ===============================
    # STEP 2: REVIEW AND EDIT DRAFTS
    # ===============================
    if st.session_state.edited_emails:
        st.header("Step 2: Review and Edit Drafts")
        st.info("Edit the drafts directly, use 'Regenerate Body' for a new AI version, or 'Clear & Write Manually' to start from scratch.")

        # --- View All Drafts Together ---
        if st.button("👁 View All Drafts Together", use_container_width=True):
            st.subheader("All Generated Drafts")
            for email_draft in st.session_state.edited_emails:
                st.markdown(f"### ✉ {email_draft['name']} (<{email_draft['to_email']}>)")
                st.markdown(f"*Subject:* {email_draft['subject']}")
                st.text_area(
                    "Body",
                    value=email_draft['body'],
                    height=250,
                    key=f"viewall_body_{email_draft['id']}",
                )
                st.markdown("---")

        # --- Individual Draft Editors ---
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

        # --- DOWNLOAD ALL DRAFTS AS CSV ---
        st.markdown("### 📥 Download All Drafts")
        if st.session_state.edited_emails:
            df_export = pd.DataFrame(st.session_state.edited_emails)[["name", "to_email", "subject", "body"]]
            csv_buffer = StringIO()
            df_export.to_csv(csv_buffer, index=False)
            st.download_button(
                label="⬇ Download Drafts as CSV",
                data=csv_buffer.getvalue(),
                file_name="morphius_email_drafts.csv",
                mime="text/csv",
                use_container_width=True
            )

        st.success("✅ All changes saved. Proceed to the 'Email Preview' page to send the final emails.")


# ===============================
# RUN APP
# ===============================
if __name__ == "__main__":

    main()
