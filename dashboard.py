import streamlit as st
import pandas as pd
import psycopg2
import plotly.graph_objects as go
import plotly.express as px
import time
import datetime
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
POSTGRES_URL = os.getenv("POSTGRES_URL")

# ===============================
# DATABASE FUNCTIONS
# ===============================
def get_db_connection():
    """Establishes connection to the PostgreSQL database."""
    try:
        return psycopg2.connect(POSTGRES_URL)
    except psycopg2.OperationalError as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None

@st.cache_data(ttl=10) # Cache data for 10 seconds to improve performance
def load_data():
    """Loads email log data from the PostgreSQL database."""
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM email_logs ORDER BY timestamp DESC", conn)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        conn.close()
        return df
    except (Exception, psycopg2.DatabaseError):
        return pd.DataFrame()

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.set_page_config(page_title="Email Dashboard", page_icon="📊", layout="wide")
    st.title("📊 Email Campaign Dashboard")

    st.sidebar.title("⚙️ Settings")
    auto_refresh_interval = st.sidebar.slider("Auto-refresh every (seconds)", 5, 60, 10, key="refresh_slider")

    last_updated_placeholder = st.empty()
    
    df = load_data()

    if df.empty:
        st.info("No email data to display yet. Send some emails and process replies to see the dashboard.")
        return

    # --- Pre-calculate all key metrics ---
    total_sent = df[df['event_type'] == 'sent'].shape[0]
    total_replies = df[df['event_type'].str.startswith('replied_', na=False)].shape[0]
    total_follow_ups = df[df['event_type'] == 'follow_up_sent'].shape[0]
    
    positive_replies = df[df['interest_level'] == 'positive'].shape[0]
    negative_replies = df[df['interest_level'] == 'negative'].shape[0]
    
    reply_rate = (total_replies / total_sent * 100) if total_sent > 0 else 0
    positive_rate = (positive_replies / total_replies * 100) if total_replies > 0 else 0

    tab1, tab2, tab3 = st.tabs(["📈 Campaign Funnel", "Key Metrics", "📜 Full Activity Log"])

    with tab1:
        st.header("Email Outreach Funnel")
        st.markdown("This chart visualizes the journey from the initial email to a positive response.")

        funnel_data = {
            'Stage': ["Initial Emails Sent", "Replies Received", "Positive Replies"],
            'Count': [total_sent, total_replies, positive_replies]
        }
        funnel_df = pd.DataFrame(funnel_data)

        bar_fig = px.bar(
            funnel_df,
            x='Count',
            y='Stage',
            orientation='h',
            text='Count',
            color='Stage',
            color_discrete_sequence=px.colors.sequential.Teal,
        )
        bar_fig.update_yaxes(categoryorder="total ascending")
        bar_fig.update_layout(
            title="Campaign Progress",
            xaxis_title="Number of Emails",
            yaxis_title="Funnel Stage",
            showlegend=False,
            margin=dict(l=20, r=20, t=40, b=20),
            height=400
        )
        st.plotly_chart(bar_fig, use_container_width=True)


    with tab2:
        st.header("Performance Metrics")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(label="📤 Emails Sent", value=total_sent)
            st.metric(label="↪️ Follow-ups Sent", value=total_follow_ups)
        with col2:
            st.metric(label="📥 Replies Received", value=total_replies)
            st.metric(label="📈 Reply Rate", value=f"{reply_rate:.2f}%")
        with col3:
            st.metric(label="👍 Positive Replies (Interested)", value=positive_replies)
            st.metric(label="👎 Negative Replies", value=negative_replies)

        st.divider()

        st.header("Sentiment Analysis")
        col_pie, col_bar = st.columns(2)
        
        with col_pie:
            st.subheader("Reply Sentiment Breakdown")
            sentiment_df = df[df['interest_level'].isin(['positive', 'negative'])]['interest_level'].value_counts().reset_index()
            sentiment_df.columns = ['sentiment', 'count']
            
            if not sentiment_df.empty:
                pie_fig = px.pie(sentiment_df, names='sentiment', values='count', 
                                 color='sentiment',
                                 color_discrete_map={'positive':'#2ca02c', 'negative':'#d62728'},
                                 hole=.3)
                pie_fig.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(pie_fig, use_container_width=True)
            else:
                st.info("No positive or negative replies to analyze yet.")

        with col_bar:
            st.subheader("Activity by Type")
            event_counts = df['event_type'].value_counts()
            st.bar_chart(event_counts)

    with tab3:
        st.header("Full Activity Log")
        st.markdown("A detailed, searchable log of all email events.")
        st.dataframe(df, use_container_width=True)

    # --- FIX: Removed the non-standard '-' characters for Windows compatibility ---
    last_updated_placeholder.text(f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    time.sleep(auto_refresh_interval)
    st.rerun()

if __name__ == "__main__":
    main()
