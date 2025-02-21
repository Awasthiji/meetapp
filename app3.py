import streamlit as st
from groq import Groq
from dotenv import load_dotenv
import os
from supabase import create_client, Client
import json
from fuzzywuzzy import process

# Load environment variables
load_dotenv()

# Retrieve API keys
groq_api_key = os.getenv("GROQ_API_KEY") or st.secrets.get("GROQ_API_KEY", None)
supabase_url = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", None)
supabase_key = os.getenv("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY", None)

if not all([groq_api_key, supabase_url, supabase_key]):
    st.error("Missing API keys. Set GROQ_API_KEY, SUPABASE_URL, and SUPABASE_KEY in .env or Streamlit secrets.")
    st.stop()

# Initialize clients
groq_client = Groq(api_key=groq_api_key)
supabase: Client = create_client(supabase_url, supabase_key)

# Streamlit app configuration
st.set_page_config(page_title="Meet App", page_icon="📝", layout="wide")

# Custom CSS for beautification (background aligns with system theme)
st.markdown("""
    <style>
    /* General styling */
    .stApp {
        padding: 20px;
    }
    /* Title styling */
    .title {
        color: #2c3e50;
        font-size: 42px;
        font-weight: bold;
        text-align: center;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
    }
    /* Caption styling */
    .caption {
        color: #7f8c8d;
        font-size: 18px;
        font-style: italic;
        text-align: center;
        margin-bottom: 30px;
    }
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 30px;
        justify-content: center;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 20px;
        font-weight: 500;
        padding: 15px 30px;
        background-color: #ffffff;
        border-radius: 12px 12px 0 0;
        color: #34495e;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        transition: all 0.3s;
    }
    .stTabs [aria-selected="true"] {
        background-color: #3498db;
        color: white;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }
    .stTabs [data-baseweb="tab"]:hover {
        background-color: #ecf0f1;
    }
    /* Form styling */
    .stTextInput > div > div > input {
        width: 100%;
        padding: 12px;
        font-size: 16px;
        border-radius: 8px;
        border: 1px solid #bdc3c7;
        background-color: #ffffff;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stTextArea > div > div > textarea {
        width: 100%;
        height: 200px;
        padding: 12px;
        font-size: 16px;
        border-radius: 8px;
        border: 1px solid #bdc3c7;
        background-color: #ffffff;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stButton > button {
        width: 100%;
        padding: 12px;
        font-size: 16px;
        background-color: #3498db;
        color: white;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        transition: background-color 0.3s;
    }
    .stButton > button:hover {
        background-color: #2980b9;
    }
    /* Output styling */
    .interaction-box {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        margin-top: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# Beautified title and caption
st.markdown('<div class="title">📝 Meet App</div>', unsafe_allow_html=True)
st.markdown('<div class="caption">Log interactions with people and retrieve them using natural language!</div>', unsafe_allow_html=True)

# Initialize Supabase table if not exists
def initialize_supabase_table():
    try:
        supabase.table("interactions").select("*").limit(1).execute()
    except Exception:
        schema = """
        CREATE TABLE interactions (
            name TEXT PRIMARY KEY,
            details TEXT NOT NULL
        );
        """
        supabase.rpc("execute_sql", {"query": schema}).execute()
        st.success("Initialized 'interactions' table in Supabase.")

# Normalize name (lowercase and trim spaces)
def normalize_name(name):
    return name.strip().lower()

# Load interactions from Supabase
def load_interactions():
    response = supabase.table("interactions").select("*").execute()
    return {normalize_name(row["name"]): row["details"] for row in response.data}

# Save interaction to Supabase
def save_interaction(name, details):
    try:
        normalized_name = normalize_name(name)
        existing = supabase.table("interactions").select("name").execute()
        existing_names = {normalize_name(row["name"]) for row in existing.data}
        
        if normalized_name in existing_names:
            st.error(f"Interaction with '{name}' (normalized: '{normalized_name}') already exists. Use a unique name.")
            return False
        
        supabase.table("interactions").insert({"name": name, "details": details}).execute()
        return True
    except Exception as e:
        st.error(f"Error saving interaction: {str(e)}")
        return False

# Load specific interaction with fuzzy matching
def load_interaction(name):
    interactions = load_interactions()
    normalized_name = normalize_name(name)
    exact_match = interactions.get(normalized_name)
    
    if exact_match:
        return exact_match
    else:
        all_names = list(interactions.keys())
        if all_names:
            best_match, score = process.extractOne(normalized_name, all_names)
            if score >= 80:
                return interactions[best_match]
        return None

# Parse query with Groq LLM
def parse_query_with_groq(query):
    messages = [
        {"role": "system", "content": "Extract a person's name from a natural language query to retrieve past interactions. Always respond with valid JSON using double quotes: {\"name\": \"person_name\", \"message\": null} if a name is found, or {\"name\": null, \"message\": \"response_text\"} if no name is identified. Recognize queries like 'show me interactions with [name]' or 'what did I discuss with [name]'. For courtesy words like 'hi' or 'hello', return {\"name\": null, \"message\": \"Hello! How can I assist you? Try 'show me interactions with [name]' or 'what did I discuss with [name]' to retrieve an interaction.\"}. For other queries without a name, return {\"name\": null, \"message\": null}. Examples: 'what did I discuss with John' -> {\"name\": \"John\", \"message\": null}, 'hello' -> {\"name\": null, \"message\": \"Hello! How can I assist you? ...\"}."},
        {"role": "user", "content": query}
    ]
    try:
        response = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=messages,
            temperature=0.5,
            max_tokens=100
        )
        raw_content = response.choices[0].message.content.strip()
        
        if not raw_content:
            st.error("Groq returned an empty response.")
            return {"name": None, "message": None}
        
        parsed_result = json.loads(raw_content)
        if not isinstance(parsed_result, dict) or "name" not in parsed_result:
            st.error(f"Parsed result invalid: {parsed_result}")
            return {"name": None, "message": None}
        
        return parsed_result
    except json.JSONDecodeError as e:
        st.error(f"Failed to parse Groq response as JSON: '{raw_content}' (Error: {str(e)})")
        return {"name": None, "message": None}
    except Exception as e:
        st.error(f"Error calling Groq API: {str(e)}")
        return {"name": None, "message": None}

# Initialize table on app start
initialize_supabase_table()

# Tabs for logging and retrieving with icons
tab1, tab2 = st.tabs(["✍️ Log Interaction", "🔍 Retrieve Interactions"])

# Tab 1: Log Interaction
with tab1:
    st.subheader("Log a New Interaction")
    with st.form(key="interaction_form", clear_on_submit=True):
        person_name = st.text_input("Person's Name", placeholder="Enter name here...")
        interaction_details = st.text_area("Interaction Details", placeholder="Describe the interaction...")
        submit_button = st.form_submit_button(label="Save Interaction")

    if submit_button:
        if not person_name or not interaction_details:
            st.error("Please provide both a name and interaction details.")
        else:
            if save_interaction(person_name, interaction_details):
                st.success(f"Interaction with '{person_name}' saved successfully!")

# Tab 2: Retrieve Interactions
with tab2:
    st.subheader("Retrieve Past Interactions")
    with st.form(key="retrieve_form"):
        query = st.text_input("Ask in natural language", placeholder="e.g., 'what did I discuss with Pritha'")
        retrieve_button = st.form_submit_button(label="Retrieve")

    if retrieve_button:
        if not query:
            st.error("Please enter a query.")
        else:
            with st.spinner("Retrieving interaction..."):
                result = parse_query_with_groq(query)
                person_name = result.get("name")
                message = result.get("message")
                
                if person_name is not None:
                    details = load_interaction(person_name)
                    if details:
                        st.write(f"**Interaction with {person_name}:**")
                        st.markdown(f"<div class='interaction-box'>{details}</div>", unsafe_allow_html=True)
                    else:
                        st.error(f"No interaction found with '{person_name}' or a close match (case-insensitive).")
                elif message is not None:
                    st.info(message)
                else:
                    st.error("Couldn’t identify a person’s name. Try 'show me interactions with [name]' or 'what did I discuss with [name]'.")