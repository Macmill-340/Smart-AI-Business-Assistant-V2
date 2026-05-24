# frontend/app.py
import os
import uuid
import time
import streamlit as st
import requests
import pandas as pd

BASE_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="Smart AI Business Assistant Platform v2",
    page_icon="🤖",
    layout="wide"
)
st.title("🤖 Smart AI Business Assistant Platform v2")

# Session state initialisation
defaults = {
    "token": None,
    "messages": [],
    "session_id": str(uuid.uuid4()),
    "selected_tenant_id": 1,
    "selected_tenant_name": "Acme Corp",
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


def auth_headers() -> dict:
    if st.session_state.token:
        return {"Authorization": f"Bearer {st.session_state.token}"}
    return {}


# Load dynamic tenants for selectors
@st.cache_data(ttl=30)
def load_tenants():
    try:
        resp = requests.get(f"{BASE_URL}/tenants/public", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return [{"id": 1, "name": "Acme Corp"}]


tenants = load_tenants()
tenant_options = {t["name"]: t["id"] for t in tenants}

# TABS
tab1, tab2, tab3, tab4 = st.tabs([
    "💬 Customer Chat",
    "📁 Upload Documents",
    "📊 Staff Dashboard",
    "🔐 Staff Login",
])

# TAB 1: CUSTOMER CHAT
with tab1:
    st.markdown("### Customer Chat Interface")
    st.caption("No login required. Select a business and start chatting.")

    col1, col2 = st.columns([1, 3])

    with col1:
        selected_name = st.selectbox(
            "Select business",
            options=list(tenant_options.keys()),
            help="Choose which business's AI assistant you want to chat with."
        )
        st.session_state.selected_tenant_id = tenant_options[selected_name]
        st.session_state.selected_tenant_name = selected_name

        customer_email = st.text_input(
            "Your email (optional)",
            help="If provided, the assistant will remember your preferences."
        )

        if st.button("🔄 New Conversation"):
            st.session_state.messages = []
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()

    with col2:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("Ask about products, pricing, or say 'I want to order 5 units'"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Agent is thinking..."):
                    try:
                        payload = {
                            "message": prompt,
                            "history": st.session_state.messages[:-1],
                            "customer_id": customer_email if customer_email else None,
                        }
                        headers = {
                            "X-Tenant-ID": str(st.session_state.selected_tenant_id)
                        }
                        response = requests.post(
                            f"{BASE_URL}/chat",
                            json=payload,
                            headers=headers,
                            timeout=60
                        )
                        if response.status_code == 200:
                            data = response.json()
                            reply = data.get("reply", "No response received.")
                        else:
                            reply = f"❌ Server error {response.status_code}: {response.text}"

                    except requests.exceptions.Timeout:
                        reply = "⏱️ The agent took too long. Please try again."
                    except requests.exceptions.ConnectionError:
                        reply = "🔌 Cannot connect to backend. Is it running on port 8000?"
                    except Exception as e:
                        reply = f"❌ Error: {e}"

                    st.markdown(reply)

            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.rerun()

# TAB 2: UPLOAD DOCUMENTS
with tab2:
    st.markdown("### Upload Business Documents")
    st.caption("Staff only. PDFs you upload become the AI knowledge base for your business.")

    if not st.session_state.token:
        st.warning("⚠️ Please log in via the **Staff Login** tab to upload documents.")
        st.info("Customers do not upload documents. Staff upload the business's product catalogs, FAQs, and policies.")
    else:
        st.success("✅ Logged in. Documents will be tagged to your business automatically.")

        uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"])

        if st.button("📤 Upload to Knowledge Base"):
            if uploaded_file is not None:
                with st.spinner(f"Processing '{uploaded_file.name}'..."):
                    try:
                        files = {
                            "file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)
                        }
                        response = requests.post(
                            f"{BASE_URL}/upload",
                            files=files,
                            headers=auth_headers(),
                            timeout=120
                        )
                        if response.status_code == 200:
                            data = response.json()
                            st.success(f"✅ {data.get('message', 'Upload successful!')}")
                            st.info(f"Uploaded by: {data.get('uploaded_by')} | Tenant ID: {data.get('tenant_id')}")
                        elif response.status_code == 401:
                            st.error("Session expired. Please log in again.")
                            st.session_state.token = None
                        else:
                            st.error(f"Upload failed: {response.text}")
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.warning("Please select a PDF file first.")

# TAB 3: STAFF DASHBOARD
with tab3:
    st.markdown("### Staff Dashboard")

    if not st.session_state.token:
        st.warning("⚠️ Please log in via the **Staff Login** tab to view the dashboard.")
    else:
        try:
            me_resp = requests.get(f"{BASE_URL}/me", headers=auth_headers(), timeout=5)
            if me_resp.status_code == 200:
                me = me_resp.json()
                st.info(f"Showing data for: **{me['username']}** | Tenant ID: {me['tenant_id']} | Role: {me['role']}")
        except Exception:
            pass

        # --- Leads section ---
        st.subheader("📋 Captured Leads")
        st.caption("Only leads captured by your business are shown (filtered by your tenant ID).")

        # Fetch leads automatically on render
        leads = []
        try:
            response = requests.get(f"{BASE_URL}/leads", headers=auth_headers(), timeout=5)
            if response.status_code == 200:
                leads = response.json()
        except Exception as e:
            st.error(f"Failed to fetch leads: {e}")

        if leads:
            df_leads = pd.DataFrame(leads)


            def intent_badge(intent):
                badges = {"hot": "🔴 hot", "warm": "🟡 warm", "cold": "🔵 cold"}
                return badges.get(intent, f"⚪ {intent}")


            df_leads["intent"] = df_leads["intent"].apply(intent_badge)
            st.dataframe(df_leads, width="stretch")
            st.caption(f"Total leads: {len(leads)}")
        else:
            st.info("No leads yet. Test lead capture in the chat tab.")

        if st.button("🔄 Refresh Leads"):
            st.rerun()

        st.divider()

        # --- Traces section ---
        st.subheader("🔍 Agent Traces — Observability & Evaluation")
        st.caption("Every conversation logged with latency, tokens, cost, and quality scores.")

        col_btn, col_limit, _ = st.columns([1, 1, 3])
        with col_limit:
            trace_limit = st.selectbox("Show last", [10, 25, 50, 100], index=0)

        # Fetch traces automatically on render
        traces = []
        try:
            response = requests.get(
                f"{BASE_URL}/traces?limit={trace_limit}",
                headers=auth_headers(),
                timeout=5
            )
            if response.status_code == 200:
                traces = response.json()
        except Exception as e:
            st.error(f"Failed to fetch traces: {e}")

        if traces:
            df_traces = pd.DataFrame(traces)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Avg Latency", f"{df_traces['latency_ms'].mean():.0f} ms")
            col2.metric("Total Cost", f"${df_traces['estimated_cost_usd'].sum():.4f}")
            col3.metric("Avg Faithfulness", f"{df_traces['faithfulness'].mean():.2f}")
            col4.metric("Avg Hallucination", f"{df_traces['hallucination_rate'].mean():.2f}")
            st.dataframe(df_traces, width="stretch")
            st.caption(f"Showing {len(traces)} most recent traces.")
        else:
            st.info("No traces yet. Chat with the assistant to generate traces.")

        with col_btn:
            if st.button("🔄 Refresh Traces"):
                st.rerun()

        st.divider()

        # Tenant management (admin only)
        st.subheader("🏢 Tenant Management")
        st.caption("Admin only. Create new business workspaces.")

        with st.expander("Create new business tenant"):
            # Wrapped in st.form to bind hitting Enter to submission
            with st.form("create_tenant_form", clear_on_submit=True):
                new_tenant_name = st.text_input("Business name", placeholder="e.g. Wayne Enterprises")
                submitted_tenant = st.form_submit_button("➕ Create Tenant")

                if submitted_tenant:
                    if new_tenant_name.strip():
                        try:
                            resp = requests.post(
                                f"{BASE_URL}/tenants",
                                json={"name": new_tenant_name.strip()},
                                headers=auth_headers(),
                                timeout=10
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                st.success(f"✅ Created tenant '{data['name']}' with ID: {data['id']}")
                                st.cache_data.clear()
                                time.sleep(1.5)  # Pause for 1.5s so success is readable before refreshing
                                st.rerun()
                            elif resp.status_code == 403:
                                st.error("Admin access required to create tenants.")
                            else:
                                st.error(f"Failed: {resp.text}")
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.warning("Please enter a business name.")

# TAB 4: STAFF LOGIN
with tab4:
    st.markdown("### Staff Login")

    if st.session_state.token:
        try:
            me_response = requests.get(f"{BASE_URL}/me", headers=auth_headers(), timeout=5)
            if me_response.status_code == 200:
                me = me_response.json()
                st.success(f"✅ Logged in as **{me['username']}** | Role: {me['role']} | Tenant ID: {me['tenant_id']}")

                # Dynamic Staff Registration for Multi-Tenant Testing
                if me.get("role") == "admin":
                    st.divider()
                    st.subheader("👥 Register Staff for Any Tenant")
                    st.caption(
                        "Super Admin only. Create staff/admin accounts for other business workspaces to test multi-tenant isolation.")

                    tenants_list = load_tenants()
                    tenant_options_reg = {t["name"]: t["id"] for t in tenants_list}

                    with st.form("register_staff_form", clear_on_submit=True):
                        reg_username = st.text_input("New Username", placeholder="e.g. wayne_staff")
                        reg_password = st.text_input("New Password", type="password")
                        reg_role = st.selectbox("Role", ["staff", "admin"])
                        reg_tenant = st.selectbox("Assign to Business", options=list(tenant_options_reg.keys()))
                        reg_submitted = st.form_submit_button("➕ Register Staff")

                        if reg_submitted:
                            if reg_username.strip() and reg_password.strip():
                                try:
                                    payload = {
                                        "username": reg_username.strip(),
                                        "password": reg_password.strip(),
                                        "role": reg_role,
                                        "tenant_id": tenant_options_reg[reg_tenant]
                                    }
                                    res = requests.post(
                                        f"{BASE_URL}/register",
                                        json=payload,
                                        headers=auth_headers(),
                                        timeout=10
                                    )
                                    if res.status_code == 200:
                                        st.success(
                                            f"✅ Successfully registered account '{reg_username}' assigned to {reg_tenant}!")
                                        time.sleep(1.5)
                                    else:
                                        st.error(f"Registration failed: {res.text}")
                                except Exception as e:
                                    st.error(f"Error during registration: {e}")
                            else:
                                st.warning("Please fill in both fields.")

        except Exception:
            st.info("Logged in.")

        if st.button("🚪 Logout"):
            st.session_state.token = None
            st.rerun()

    else:
        st.info("Default credentials: **admin** / **admin123** (created automatically on first run)")

        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

        if submitted:
            if not username or not password:
                st.error("Please enter both username and password.")
            else:
                try:
                    response = requests.post(
                        f"{BASE_URL}/login",
                        data={"username": username, "password": password},
                        timeout=10
                    )
                    if response.status_code == 200:
                        st.session_state.token = response.json().get("access_token")
                        st.success("✅ Logged in!")
                        st.rerun()
                    elif response.status_code == 400:
                        st.error("❌ Incorrect username or password.")
                    else:
                        st.error(f"Login failed: {response.text}")
                except requests.exceptions.ConnectionError:
                    st.error("🔌 Cannot connect to backend.")
                except Exception as e:
                    st.error(f"Error: {e}")

        st.divider()
        st.caption(
            "To create additional staff accounts, an admin must use the `/register` API endpoint. "
            "See the Swagger docs at `http://localhost:8000/docs`."
        )