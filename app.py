import streamlit as st
from contactout import main as contactout_main
from ai_webscraper import main as webscraper_main
from send_email import main as send_email_main
from email_preview import main as email_preview_main
from reply import main as reply_main
from dashboard import main as dashboard_main
from clean_data import main as clean_data_main
import os

# ===============================
# PAGE CONFIGURATION
# ===============================
st.set_page_config(
    page_title="Morphius AI - Email Automator",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="collapsed"  # auto-collapse sidebar on mobile
)

# ===============================
# CUSTOM STYLING
# ===============================
st.markdown("""
    <style>
    /* --- GLOBAL BACKGROUND --- */
    [data-testid="stAppViewContainer"] {
        background-color: #f9fbfd;
    }

    /* --- SIDEBAR STYLING --- */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #003366, #004aad);
        color: white;
    }
    [data-testid="stSidebar"] * {
        color: white !important;
    }

    /* --- SIDEBAR RADIO BUTTONS --- */
    div[role="radiogroup"] label {
        background-color: rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 8px 12px;
        margin: 4px 0px;
        cursor: pointer;
        transition: all 0.2s ease-in-out;
        font-size: 1rem;
    }
    div[role="radiogroup"] label:hover {
        background-color: rgba(255, 255, 255, 0.15);
        transform: scale(1.02);
    }

    /* --- MAIN TITLE BAR --- */
    .main-header {
        background: linear-gradient(90deg, #004aad, #007bff);
        color: white;
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        margin-bottom: 25px;
        box-shadow: 0px 3px 10px rgba(0,0,0,0.1);
    }
    .main-header h1 {
        font-size: 2.2rem !important;
        font-weight: 700 !important;
        color: white !important;
        letter-spacing: 0.5px;
    }

    /* --- CARD CONTAINERS --- */
    .card {
        background-color: white;
        padding: 25px 30px;
        border-radius: 16px;
        box-shadow: 0 3px 10px rgba(0,0,0,0.08);
        margin-bottom: 25px;
        transition: all 0.3s ease;
    }
    .card:hover {
        box-shadow: 0 6px 15px rgba(0,0,0,0.12);
        transform: scale(1.01);
    }

    /* --- BUTTONS --- */
    button[data-testid="baseButton-primary"] {
        background-color: #007bff !important;
        color: white !important;
        border-radius: 8px !important;
        border: none !important;
        font-weight: 600 !important;
    }
    button[data-testid="baseButton-primary"]:hover {
        background-color: #0056d6 !important;
        transform: scale(1.02);
    }

    /* --- FOOTER --- */
    .footer {
        text-align: center;
        color: #888;
        font-size: 0.9rem;
        padding-top: 15px;
        border-top: 1px solid #ddd;
        margin-top: 40px;
    }

    /* --- LOGO CUSTOM CSS --- */
    .sidebar .stImage > img {
        border-radius: 50%;       
        box-shadow: 0px 3px 8px rgba(0,0,0,0.2); 
        transition: transform 0.2s ease-in-out;
        width: 80px;             /* smaller desktop size */
        max-width: 40vw;          
        margin-bottom: 1rem;
    }
    .sidebar .stImage > img:hover {
        transform: scale(1.05);   
    }

    /* --- RESPONSIVE STYLING --- */
    @media only screen and (max-width: 600px) {
        .main-header h1 {
            font-size: 1.5rem !important;
        }
        div[role="radiogroup"] label {
            font-size: 0.9rem;
            padding: 6px 10px;
        }
        .sidebar .stImage > img {
            width: 60px;    /* smaller mobile size */
            max-width: 30vw;
        }
    }
    </style>
""", unsafe_allow_html=True)

# ===============================
# SIDEBAR WITH LOGO & NAVIGATION
# ===============================
with st.sidebar:
    # Display local logo using st.image
    st.image("Morphius_AI_logo.png")  # place your logo in project folder
    st.markdown("### ⚙ *Morphius AI Email Automator*")
    st.markdown("---")

    page = st.radio(
        "📍 Navigate to:",
        ("Collect Contacts", "AI Web Scraper", "Show Cleaned Data", "Generate & Edit Emails", "Email Preview", "Handle Replies", "Dashboard")
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

# ===============================
# FOOTER
# ===============================

st.markdown('<div class="footer">📬 Efficient. Smart. Automated — Powered by Morphius AI</div>', unsafe_allow_html=True)


