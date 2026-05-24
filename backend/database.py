from sqlmodel import Field, SQLModel, Session, create_engine, select
from typing import Optional
import bcrypt
from datetime import datetime, timezone

#tenant table
class Tenant(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)

# user table
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = Field(default="staff")
    tenant_id: int = Field(foreign_key="tenant.id")

# lead table
class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: Optional[str] = None
    intent: str = Field(default="cold")
    notes: Optional[str] = None
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    created_at: datetime = Field(default_factory=datetime.now)

class CustomerPreference(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: str = Field(index=True)
    preference_key: str
    preference_value: str
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    updated_at: datetime = Field(default_factory=datetime.now)

class AgentTrace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    user_input: str
    final_response: str
    #observe
    latency_ms: float
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    estimated_cost: float = Field(default=0.0)

    #evaluate
    faithfulness: float = Field(default=1.0)
    hallucination_rate: float = Field(default=0.0)
    retrieval_quality: float = Field(default=1.0)

    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    created_at: datetime = Field(default_factory=datetime.now)



#Connect
sqlite_url = "sqlite:///./assistant.db"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def create_db_and_table():
    SQLModel.metadata.create_all(engine)

def seed_initial_data():
    with Session(engine) as session:
        existing_tenant = session.exec(select(Tenant).where(Tenant.name == "Acme Corp")).first()
        if not existing_tenant:
            default_tenant = Tenant(name="Acme Corp")
            session.add(default_tenant)
            session.commit()
            session.refresh(default_tenant)
            tenant_id = default_tenant.id
        else:
            tenant_id = existing_tenant.id

        existing_user = session.exec(select(User).where(User.username == "admin")).first()
        if not existing_user:
            hashed_pw = bcrypt.hashpw("admin123".encode("utf8"), bcrypt.gensalt()).decode("utf8")
            admin_user = User(
                username="admin",
                password_hash=hashed_pw,
                role="admin",
                tenant_id=tenant_id,
            )
            session.add(admin_user)
            session.commit()
            print("Seeded default tenant 'Acme Corp' and admin user (admin/admin123)")

def get_session():
    with Session(engine) as session:
        yield session