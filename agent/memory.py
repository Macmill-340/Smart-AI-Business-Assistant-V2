from datetime import datetime, timezone
from sqlmodel import Session, select
from backend.database import CustomerPreference, engine

def get_preference(customer_id: str, tenant_id: int) -> str:
    with Session(engine) as session:
        preferences = session.exec(
            select(CustomerPreference).where(
                CustomerPreference.customer_id == customer_id,
                CustomerPreference.tenant_id == tenant_id,
            )
        ).all()

    if not preferences:
        return "No customer preferences found."

    lines = [f"{p.preference_key}: {p.preference_value}" for p in preferences]
    return "Known customer preferences:\n" + "\n".join(lines)

def save_preference(
        customer_id: str,
        tenant_id: int,
        key: str,
        value: str,
) -> None:
    with Session(engine) as session:
        existing = session.exec(
            select(CustomerPreference).where(
                CustomerPreference.customer_id == customer_id,
                CustomerPreference.tenant_id == tenant_id,
                CustomerPreference.preference_key == key
            )
        ).first()

        if existing:
            existing.preference_value = value
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
        else:
            new_pref = CustomerPreference(
                customer_id=customer_id,
                tenant_id=tenant_id,
                preference_key=key,
                preference_value=value,
            )
            session.add(new_pref)

        session.commit()

def extract_and_save_preferences(
    customer_id: str,
    tenant_id: int,
    user_input: str,
    llm
)-> None:

    extraction_prompt = f"""
Analyze this customer message and extract any concrete preferences.
Output ONLY key:value pairs on separate lines (e.g. "budget_limit: 45000").
Use snake_case keys. If there is nothing preference-worthy, output exactly: NONE
 
Customer message: "{user_input}"
 
Possible preference types: budget_limit, preferred_brand, product_category,
contact_preference, timeline, location, or any other relevant preference.
"""

    response = llm.invoke(extraction_prompt)
    result = response.text.strip()

    if result.upper() == "NONE" or not result:
        return

    for line in result.split("\n"):
        if ":" in line:
            parts = line.split(":",1)
            key = parts[0].strip().lower().replace(" ", "_")
            value = parts[1].strip()
            if key and value:
                save_preference(customer_id, tenant_id, key, value)
                