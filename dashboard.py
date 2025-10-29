import streamlit as st
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import plotly.express as px
import time
import datetime
import os
from dotenv import load_dotenv
from zoneinfo import ZoneInfo # For modern timezone handling

# Load environment variables from .env file
load_dotenv()

# ===============================
# CONFIGURATION
# ===============================
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
DISPLAY_TIMEZONE = "Asia/Kolkata" # Set the target timezone for display

# ===============================
# DATABASE FUNCTIONS
# ===============================
@st.cache_resource
def init_connection():
    """Initializes and returns a MongoDB client."""
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ismaster')
        return client
    except ConnectionFailure as e:
        st.error(f"❌ **Database Connection Error:** {e}")
        return None

@st.cache_data(ttl=10)
def load_data(_client):
    """Loads email log data from MongoDB and converts timestamps to the local timezone."""
    if _client is None:
        return pd.DataFrame()
    try:
        db = _client[MONGO_DB_NAME]
        cursor = db.email_logs.find().sort('timestamp', -1)
        df = pd.DataFrame(list(cursor))
        if not df.empty and 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize('UTC').dt.tz_convert(DISPLAY_TIMEZONE)
        return df
    except Exception as e:
        st.warning(f"Could not load data. Error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=10)
def load_unsubscribe_count(_client):
    """
    Loads the total number of unsubscribes by summing counts from both
    'unsubscribe_list' and 'unsubscribed_emails' collections.
    """
    if _client is None:
        return 0
    try:
        db = _client[MONGO_DB_NAME]
        # Count documents in the first collection
        count_from_list = db.unsubscribe_list.count_documents({})
        # Count documents in the second collection
        count_from_emails = db.unsubscribed_emails.count_documents({})
        # Return the sum of both counts
        total_unsubscribes = count_from_list + count_from_emails
        return total_unsubscribes
    except Exception as e:
        st.warning(f"Could not load unsubscribe count. Error: {e}")
        return 0

# ===============================
# MAIN STREAMLIT APP
# ===============================
def main():
    st.set_page_config(page_title="Email Campaign Dashboard", page_icon="📊", layout="wide")
    st.title("📊 Email Campaign Dashboard")

    st.sidebar.title("⚙️ Settings")
    auto_refresh_interval = st.sidebar.slider("Auto-refresh every (seconds)", 5, 60, 10, key="refresh_slider")

    last_updated_placeholder = st.empty()
    
    mongo_client = init_connection()
    df = load_data(mongo_client)
    total_unsubscribes = load_unsubscribe_count(mongo_client)

    if mongo_client and df.empty:
        st.info("No email data to display yet. Send some emails and process replies to see the dashboard.")
        time.sleep(auto_refresh_interval)
        st.rerun()
        return

    # --- Pre-calculate all key metrics ---
    total_sent = df[df['event_type'] == 'initial_outreach'].shape[0]
    total_replies = df[df['event_type'].str.startswith('replied_', na=False)].shape[0]
    total_follow_ups = df[df['event_type'] == 'follow_up_sent'].shape[0]
    # --- REMOVED open rate calculations ---
    positive_replies = df[df['interest_level'] == 'positive'].shape[0]
    negative_replies = df[df['interest_level'] == 'negative'].shape[0]
    reply_rate = (total_replies / total_sent * 100) if total_sent > 0 else 0
    
    tab_labels = [
        "#### 📈 Campaign Funnel",
        "#### 📊 Key Metrics",
        "#### 📜 Full Activity Log"
    ]
    tab1, tab2, tab3 = st.tabs(tab_labels)

    with tab1:
        st.header("Email Outreach Funnel")
        st.markdown("This chart visualizes the journey from the initial email to a positive response.")
        # --- MODIFIED: Removed "Emails Opened" from the funnel data ---
        funnel_data = {
            'Stage': ["Initial Emails Sent", "Replies Received", "Positive Replies"],
            'Count': [total_sent, total_replies, positive_replies]
        }
        funnel_df = pd.DataFrame(funnel_data)
        bar_fig = px.bar(
            funnel_df, x='Count', y='Stage', orientation='h', text='Count',
            color='Stage', color_discrete_sequence=px.colors.sequential.Teal,
        )
        bar_fig.update_yaxes(categoryorder="total ascending")
        bar_fig.update_layout(
            title="Campaign Progress", xaxis_title="Number of Emails", yaxis_title="Funnel Stage",
            showlegend=False, margin=dict(l=20, r=20, t=40, b=20), height=400
        )
        st.plotly_chart(bar_fig, use_container_width=True)

    with tab2:
        st.header("Performance Metrics")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(label="📤 Initial Emails Sent", value=total_sent)
            st.metric(label="↪️ Follow-ups Sent", value=total_follow_ups)
        with col2:
            st.metric(label="📥 Replies Received", value=total_replies)
            st.metric(label="📈 Reply Rate", value=f"{reply_rate:.2f}%")
        with col3:
            st.metric(label="👍 Positive Replies", value=positive_replies)
            st.metric(label="👎 Negative Replies", value=negative_replies)

        # --- MODIFIED: Removed the row for Opens and Open Rate ---
        # --- Moved Unsubscribes to its own metric display for clarity ---
        st.metric(label="🚫 Unsubscribes", value=total_unsubscribes)

        st.divider() 

        st.header("Sentiment Analysis")
        col_pie, col_bar = st.columns(2)
        
        with col_pie:
            st.subheader("Reply Sentiment Breakdown")
            if 'interest_level' in df.columns:
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
            else:
                st.info("No sentiment data to analyze yet.")

        with col_bar:
            st.subheader("Activity by Type")
            if 'event_type' in df.columns:
                event_counts = df['event_type'].value_counts()
                st.bar_chart(event_counts)
            else:
                st.info("No event data to plot.")

    with tab3:
        st.header("Full Activity Log")
        st.markdown("A detailed, searchable log of all email events.")
        if '_id' in df.columns:
            df_display = df.drop(columns=['_id'])
        else:
            df_display = df
        
        if 'timestamp' in df_display.columns:
            df_display['timestamp'] = df_display['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        st.dataframe(df_display, use_container_width=True)

    now_local = datetime.datetime.now(datetime.timezone.utc).astimezone(ZoneInfo(DISPLAY_TIMEZONE))
    last_updated_placeholder.text(f"Last updated: {now_local.strftime('%Y-%m-%d %H:%M:%S')} ({DISPLAY_TIMEZONE})")
    
    time.sleep(auto_refresh_interval)
    st.rerun()

if __name__ == "__main__":
    main()
