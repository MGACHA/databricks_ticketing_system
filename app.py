import os
import time
import streamlit as st
import psycopg
from psycopg import sql
from databricks.sdk import WorkspaceClient

# Initialize Databricks client
w = WorkspaceClient()

# Lakebase connection details
# Try environment variables first (if Lakebase resource is configured)
# Otherwise fall back to hardcoded values
PGHOST = os.environ.get("PGHOST")
PGDATABASE = os.environ.get("PGDATABASE", "databricks_postgres")
PGUSER = os.environ.get("PGUSER")
PGPORT = os.environ.get("PGPORT", "5432")

# If environment variables not set, get connection details from endpoint
if not PGHOST:
    try:
        endpoint_name = "projects/databrick-ai-bootcamp-postgres/branches/production/endpoints/primary"
        endpoint = w.postgres.get_endpoint(name=endpoint_name)
        PGHOST = endpoint.status.hosts.host
        PGUSER = w.current_user.me().user_name
        PGDATABASE = "databricks_postgres"
        PGPORT = "5432"
    except Exception as e:
        st.error(f"Failed to get Lakebase endpoint details: {e}")
        PGHOST = None

# Token refresh management
if 'postgres_token' not in st.session_state:
    st.session_state.postgres_token = None
if 'token_refresh_time' not in st.session_state:
    st.session_state.token_refresh_time = 0

def get_postgres_token():
    """Get or refresh the Postgres OAuth token."""
    current_time = time.time()
    # Refresh token every 45 minutes (tokens expire after 1 hour)
    if (st.session_state.postgres_token is None or 
        current_time - st.session_state.token_refresh_time > 2700):
        
        endpoint_name = f"projects/databrick-ai-bootcamp-postgres/branches/production/endpoints/primary"
        token = w.postgres.generate_database_credential(endpoint=endpoint_name).token
        st.session_state.postgres_token = token
        st.session_state.token_refresh_time = current_time
    
    return st.session_state.postgres_token

def get_connection():
    """Create a database connection with current token."""
    if not PGHOST:
        raise Exception("Database host not configured. Please check Lakebase connection settings.")
    
    token = get_postgres_token()
    
    # Ensure all parameters are strings
    conn = psycopg.connect(
        host=str(PGHOST),
        dbname=str(PGDATABASE),
        user=str(PGUSER),
        port=str(PGPORT),
        password=token,
        sslmode="require"
    )
    return conn

def fetch_all_tickets():
    """Fetch all tickets with message counts."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                t.ticket_id,
                t.title,
                t.status,
                t.created_by,
                t.created_at,
                COUNT(tm.message_id) as message_count
            FROM tickets t
            LEFT JOIN ticket_messages tm ON t.ticket_id = tm.ticket_id
            GROUP BY t.ticket_id, t.title, t.status, t.created_by, t.created_at
            ORDER BY t.created_at DESC
        """)
        tickets = cur.fetchall()
    conn.close()
    return tickets

def fetch_ticket_messages(ticket_id):
    """Fetch all messages for a specific ticket."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT message_id, message_text, author, created_at
            FROM ticket_messages
            WHERE ticket_id = %s
            ORDER BY created_at ASC
        """, (ticket_id,))
        messages = cur.fetchall()
    conn.close()
    return messages

def fetch_ticket_details(ticket_id):
    """Fetch details of a specific ticket."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ticket_id, title, status, created_by, created_at
            FROM tickets
            WHERE ticket_id = %s
        """, (ticket_id,))
        ticket = cur.fetchone()
    conn.close()
    return ticket

def create_ticket(title, status, created_by):
    """Create a new ticket."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO tickets (title, status, created_by)
            VALUES (%s, %s, %s)
            RETURNING ticket_id
        """, (title, status, created_by))
        ticket_id = cur.fetchone()[0]
        conn.commit()
    conn.close()
    return ticket_id

def add_message(ticket_id, message_text, author):
    """Add a message to a ticket."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ticket_messages (ticket_id, message_text, author)
            VALUES (%s, %s, %s)
            RETURNING message_id
        """, (ticket_id, message_text, author))
        message_id = cur.fetchone()[0]
        conn.commit()
    conn.close()
    return message_id

def update_ticket_status(ticket_id, new_status):
    """Update the status of a ticket."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE tickets
            SET status = %s
            WHERE ticket_id = %s
        """, (new_status, ticket_id))
        conn.commit()
    conn.close()

# Streamlit UI
st.set_page_config(page_title="Support Ticket System", page_icon="🎫", layout="wide")

st.title("🎫 Support Ticket System")
st.markdown("---")

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Go to",
    ["📋 View All Tickets", "🔍 View Ticket Details", "➕ Create New Ticket", "💬 Add Message", "🔄 Update Status"]
)

# Page: View All Tickets
if page == "📋 View All Tickets":
    st.header("All Support Tickets")
    
    try:
        tickets = fetch_all_tickets()
        
        if tickets:
            # Display tickets in a table
            st.write(f"**Total Tickets: {len(tickets)}**")
            
            for ticket in tickets:
                ticket_id, title, status, created_by, created_at, message_count = ticket
                
                # Status badge color
                status_color = {
                    'open': '🔴',
                    'in_progress': '🟡',
                    'resolved': '🟢'
                }
                
                col1, col2, col3, col4 = st.columns([1, 3, 2, 1])
                
                with col1:
                    st.write(f"**ID: {ticket_id}**")
                with col2:
                    st.write(f"**{title}**")
                with col3:
                    st.write(f"{status_color.get(status, '⚪')} Status: **{status}**")
                with col4:
                    st.write(f"💬 {message_count} messages")
                
                st.caption(f"Created by: {created_by} | {created_at}")
                st.markdown("---")
        else:
            st.info("No tickets found.")
    
    except Exception as e:
        st.error(f"Error fetching tickets: {e}")

# Page: View Ticket Details
elif page == "🔍 View Ticket Details":
    st.header("View Ticket Details")
    
    try:
        tickets = fetch_all_tickets()
        ticket_options = {f"#{t[0]} - {t[1]}": t[0] for t in tickets}
        
        if ticket_options:
            selected_ticket = st.selectbox("Select a ticket", list(ticket_options.keys()))
            ticket_id = ticket_options[selected_ticket]
            
            if st.button("Load Ticket"):
                # Fetch ticket details
                ticket = fetch_ticket_details(ticket_id)
                
                if ticket:
                    st.subheader(f"Ticket #{ticket[0]}: {ticket[1]}")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Status:** {ticket[2]}")
                    with col2:
                        st.write(f"**Created by:** {ticket[3]}")
                    
                    st.write(f"**Created at:** {ticket[4]}")
                    st.markdown("---")
                    
                    # Fetch and display messages
                    messages = fetch_ticket_messages(ticket_id)
                    
                    st.subheader(f"Messages ({len(messages)})")
                    
                    if messages:
                        for msg in messages:
                            message_id, message_text, author, created_at = msg
                            
                            with st.container():
                                st.markdown(f"**{author}** - {created_at}")
                                st.write(message_text)
                                st.markdown("---")
                    else:
                        st.info("No messages yet.")
        else:
            st.info("No tickets available.")
    
    except Exception as e:
        st.error(f"Error loading ticket: {e}")

# Page: Create New Ticket
elif page == "➕ Create New Ticket":
    st.header("Create New Ticket")
    
    with st.form("create_ticket_form"):
        title = st.text_input("Ticket Title", max_chars=255)
        status = st.selectbox("Status", ["open", "in_progress", "resolved"])
        created_by = st.text_input("Your Email", max_chars=255)
        
        submitted = st.form_submit_button("Create Ticket")
        
        if submitted:
            if title and created_by:
                try:
                    ticket_id = create_ticket(title, status, created_by)
                    st.success(f"✅ Ticket #{ticket_id} created successfully!")
                except Exception as e:
                    st.error(f"Error creating ticket: {e}")
            else:
                st.warning("Please fill in all required fields.")

# Page: Add Message
elif page == "💬 Add Message":
    st.header("Add Message to Ticket")
    
    try:
        tickets = fetch_all_tickets()
        ticket_options = {f"#{t[0]} - {t[1]}": t[0] for t in tickets}
        
        if ticket_options:
            selected_ticket = st.selectbox("Select a ticket", list(ticket_options.keys()))
            ticket_id = ticket_options[selected_ticket]
            
            with st.form("add_message_form"):
                message_text = st.text_area("Message", height=150)
                author = st.text_input("Your Email", max_chars=255)
                
                submitted = st.form_submit_button("Add Message")
                
                if submitted:
                    if message_text and author:
                        try:
                            message_id = add_message(ticket_id, message_text, author)
                            st.success(f"✅ Message added successfully!")
                        except Exception as e:
                            st.error(f"Error adding message: {e}")
                    else:
                        st.warning("Please fill in all required fields.")
        else:
            st.info("No tickets available to add messages to.")
    
    except Exception as e:
        st.error(f"Error loading tickets: {e}")

# Page: Update Status
elif page == "🔄 Update Status":
    st.header("Update Ticket Status")
    
    try:
        tickets = fetch_all_tickets()
        ticket_options = {f"#{t[0]} - {t[1]} (Current: {t[2]})": t[0] for t in tickets}
        
        if ticket_options:
            selected_ticket = st.selectbox("Select a ticket", list(ticket_options.keys()))
            ticket_id = ticket_options[selected_ticket]
            
            with st.form("update_status_form"):
                new_status = st.selectbox("New Status", ["open", "in_progress", "resolved"])
                
                submitted = st.form_submit_button("Update Status")
                
                if submitted:
                    try:
                        update_ticket_status(ticket_id, new_status)
                        st.success(f"✅ Ticket #{ticket_id} status updated to '{new_status}'!")
                    except Exception as e:
                        st.error(f"Error updating status: {e}")
        else:
            st.info("No tickets available to update.")
    
    except Exception as e:
        st.error(f"Error loading tickets: {e}")

# Footer
st.sidebar.markdown("---")
st.sidebar.info(
    "💾 All data is stored in Lakebase PostgreSQL database.\n\n"
    "🔄 Changes persist after refresh."
)