import streamlit as st
from contactout import main as contactout_main
from ai_webscraper import main as web_scraper_main
from send_email import main as send_email_main
from email_preview import main as email_preview_main
from reply import main as reply_main
from dashboard import main as dashboard_main
from clean_data import main as clean_data_main
from download_all_data import main as download_data_main # <-- IMPORT THE NEW MODULE
import os

# ===============================
# PAGE CONFIGURATION
# ===============================
st.set_page_config(
    page_title="Morphius AI - Email Automator",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ===============================
# CUSTOM STYLING
# ===============================
st.markdown("""
    <style>
    /* --- Styles are unchanged --- */
    [data-testid="stAppViewContainer"] { background-color: #f9fbfd; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #003366, #004aad); color: white; }
    [data-testid="stSidebar"] * { color: white !important; }
    div[role="radiogroup"] label { background-color: rgba(255, 255, 255, 0.08); border-radius: 8px; padding: 8px 12px; margin: 4px 0px; cursor: pointer; transition: all 0.2s ease-in-out; font-size: 1rem; }
    div[role="radiogroup"] label:hover { background-color: rgba(255, 255, 255, 0.15); transform: scale(1.02); }
    .main-header { background: linear-gradient(90deg, #004aad, #007bff); color: white; padding: 1.5rem; border-radius: 12px; text-align: center; margin-bottom: 25px; box-shadow: 0px 3px 10px rgba(0,0,0,0.1); }
    .main-header h1 { font-size: 2.2rem !important; font-weight: 700 !important; color: white !important; letter-spacing: 0.5px; }
    .sidebar .stImage > img { border-radius: 50%; box-shadow: 0px 3px 8px rgba(0,0,0,0.2); transition: transform 0.2s ease-in-out; width: 80px; max-width: 40vw; margin-bottom: 1rem; }
    .sidebar .stImage > img:hover { transform: scale(1.05); }
    </style>
""", unsafe_allow_html=True)

# ===============================
# SIDEBAR WITH LOGO & NAVIGATION
# ===============================
with st.sidebar:
    st.image("Morphius_AI_logo.png")
    st.markdown("### ⚙ *Morphius AI Email Automator*")
    st.markdown("---")

    # **MODIFICATION:** Add "Download Data" to the navigation options
    page = st.radio(
        "📍 Navigate to:",
        ("Collect Contacts", "AI Web Scraper", "Show Cleaned Data", "Generate & Edit Emails", "Email Preview", "Handle Replies", "Dashboard", "Download Data")
    )

    st.markdown("---")
    st.markdown("""
        <div style="text-align:center; font-size:0.9rem; color:#ddd;">
        © 2025 Morphius AI <br>
        </div>
    """, unsafe_allow_html=True)

# ===============================
# MAIN CONTENT AREA
# ===============================
st.markdown('<div class="main-header"><h1> Morphius AI — Email Automation</h1></div>', unsafe_allow_html=True)

if page == "Collect Contacts":
    contactout_main()
elif page == "AI Web Scraper":
    web_scraper_main()
elif page == "Show Cleaned Data":
    clean_data_main()
elif page == "Generate & Edit Emails":
    send_email_main()
elif page == "Email Preview":
    email_preview_main()
elif page == "Handle Replies":
    reply_main()
elif page == "Dashboard":
    dashboard_main()
# **MODIFICATION:** Add the logic to display the new page
elif page == "Download Data":
    download_data_main()

# ===============================
# FOOTER
# ===============================
st.markdown('<div class="footer">📬 Efficient. Smart. Automated — Powered by Morphius AI</div>', unsafe_allow_html=True)


