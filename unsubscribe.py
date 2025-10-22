import streamlit as st
from pymongo import MongoClient
from datetime import datetime
from urllib.parse import unquote
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
unsubscribe_collection = db["unsubscribe_list"]

query_params = st.experimental_get_query_params()
email_param = query_params.get("email", [None])[0]

if email_param:
    email = unquote(email_param)
    unsubscribe_collection.update_one(
        {"email": email},
        {"$set": {"unsubscribed": True, "unsubscribed_at": datetime.utcnow()}},
        upsert=True
    )
    st.success(f"✅ {email} has been unsubscribed successfully.")
    st.write("You will no longer receive emails from Morphius AI.")
else:
    st.warning("❌ No email provided in the link.")
