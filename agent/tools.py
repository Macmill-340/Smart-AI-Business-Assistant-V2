import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from langchain_core.tools import tool
from langchain_community.tools.tavily_search import TavilySearchResults
from sqlmodel import Session
from dotenv import load_dotenv
from backend.database import Lead, engine

load_dotenv()

#save lead to database
@tool
def save_lead(
        name: str,
        tenant_id: int,
        email: Optional[str]=None,
        intent: str = "warm",
        notes: Optional[str]=None,
) -> str:
    """
    Save a potential customer (lead) to the database when they express
    interest in a product or service. Use this when a customer asks about
    pricing, availability, or shows clear purchase intent.

    Args:
        name: The customer's name as they introduced themselves.
        tenant_id: The business workspace ID (from the chat session).
        email: Customer's email address if they shared it.
        intent: How ready they are to buy — 'hot' (ready now),
                'warm' (interested), or 'cold' (just browsing).
        notes: A brief summary of what they're interested in.

    Returns:
        Confirmation message with the assigned lead ID.
    """
    with Session(engine) as session:
        lead = Lead(
            name=name,
            email=email,
            intent=intent,
            notes=notes,
            tenant_id=tenant_id,
        )
        session.add(lead)
        session.commit()
        session.refresh(lead)
        return f"Lead saved successfully. ID: {lead.id}, Name: {name}, Intent: {intent}"

#search the web for latest information
@tool
def search_web(query: str) -> str:
    """
    Search the web for current information about products, services,
    competitors, or anything not found in the business knowledge base.
    Use this when the customer asks about something you don't have
    documents for, or when they need up-to-date information.

    Args:
        query: A clear, specific search query string.

    Returns:
        A summary of the most relevant search results.
    """
    try:
        tavily_tool = TavilySearchResults(max_results=3, tavily_api_key=os.getenv("TAVILY_API_KEY"))
        results = tavily_tool.invoke(query)
        if not results:
            return "No relevant search results found."

        formatted = []
        for i, r in enumerate(results, 1):
            content = r.get("content", "")[:400]
            url = r.get("url", "")
            formatted.append(f"[{i}] {content}\nSource: {url}")
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Web search failed: {str(e)}. Please answer from available knowledge."

#send mail
@tool
def send_email(
        recipient_email: str,
        subject: str,
        body: str,
) -> str:
    """
    Send an email notification to a staff member or manager. Use this
    when a hot lead is captured, when an urgent customer issue arises,
    or when the customer explicitly requests a follow-up email.

    Args:
        recipient_email: The email address to send the notification to.
        subject: A clear, concise email subject line.
        body: The full email body text with relevant customer details.

    Returns:
        Success or failure confirmation message.
    """
    sender_email = os.getenv("NOTIFICATION_EMAIL")
    app_password = os.getenv("EMAIL_PASSWORD")
    if not sender_email or not app_password:
        log_msg = (
            f"\n[EMAIL NOT CONFIGURED]- would have sent\n"
            f"To: {recipient_email}\n"
            f"Subject: {subject}\n"
            f"Body: {body[:200]}...\n"
        )
        print(log_msg)
        return "Email notification logged successfully (email not configured in .env)."
    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())

        return f"Email sent successfully to {recipient_email}."
    except smtplib.SMTPAuthenticationError:
        return "Email failed: authentication error. Check NOTIFICATION_EMAIL and EMAIL_APP_PASSWORD in .env."
    except Exception as e:
        return f"Email failed: {str(e)}"

#get current date and time
@tool
def get_current_datetime() -> str:
    """
    Get the current date and time. Use this when the customer asks about
    timing, scheduling, deadlines, ongoing sales, or anything that
    requires knowing today's date. Always call this before making any
    date-relative statements.

    Returns:
        Current date and time in a human-readable format.
    """
    now = datetime.now()
    return now.strftime("Current date: %A, %B %d, %Y | Current time: %I:%M %p")

#tool registry
all_tools = [
    save_lead,
    search_web,
    send_email,
    get_current_datetime,
]