from fastapi import FastAPI, Depends, HTTPException, UploadFile, File,Header
import shutil
import tempfile
import uuid
from typing import Optional
from pydantic import BaseModel
from backend.database import (
    create_db_and_table,
    seed_initial_data,
    get_session,
    engine,
    User,
    Lead,
    AgentTrace,
    Tenant,
)
import os
from agent.rag import process_document
from agent.agent import run_agent
from contextlib import asynccontextmanager
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from backend.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    require_admin,
    UserContext,
)
import jwt

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_table()
    seed_initial_data()
    yield
app = FastAPI(title="SAIBAP-Imperium-Prototype-V2", description="Multi-tenant AI Business Assistant Platform", version="2.0.0", lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str
    history: list = []
    customer_id: Optional[str] = None

class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "staff"
    tenant_id: int

class CreateTenantRequest(BaseModel):
    name: str

#endpoints
@app.post("/register")
def register_user(
    request: RegisterRequest,
    session: Session = Depends(get_session),
    current_user: UserContext = Depends(require_admin)
):
    """Create a new staff account. Admin only."""
    existing = session.exec(select(User).where(User.username==request.username)).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    tenant = session.get(Tenant, request.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant {request.tenant_id} not found.")

    new_user = User(
        username=request.username,
        password_hash=get_password_hash(request.password),
        role=request.role,
        tenant_id=request.tenant_id,
    )
    session.add(new_user)
    session.commit()
    return {"message": f"Staff account '{request.username}' created for tenant {request.tenant_id}."}


@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    """Staff login. Returns a JWT token."""
    user = session.exec(select(User).where(User.username == form_data.username)).first()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": user.username, "role": user.role, "tenant_id": user.tenant_id})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me")
def get_me(current_user: UserContext = Depends(get_current_user)):
    """Returns the current user's info. Useful for the frontend to confirm login."""
    return {
        "username": current_user.username,
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
    }

@app.post("/upload")
async def upload_doc(file: UploadFile = File(...), current_user: UserContext = Depends(get_current_user)):
    """Upload a PDF to the business knowledge base. Staff only."""

    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    temp_dir = tempfile.gettempdir()
    temp_filename = f"temp_{uuid.uuid4()}_{file.filename}"
    temp_path = os.path.join(temp_dir, temp_filename)
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        #chunk and store
        result = process_document(temp_path, current_user.tenant_id)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return {
        "message": result,
        "tenant_id": current_user.tenant_id,
        "uploaded_by": current_user.username,
    }

@app.post("/chat")
def chat(request: ChatRequest, x_tenant_id: Optional[str] = Header(default=None)):
    """
    Public chat endpoint. No authentication required.
    Customers must send X-Tenant-ID header to identify which business
    they are chatting with.
    """
    try:
        tenant_id = int(x_tenant_id) if x_tenant_id else 1
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be an integer.")

    session_id = str(uuid.uuid4())

    customer_id = request.customer_id or session_id

    response = run_agent(
        user_input=request.message,
        history=request.history,
        tenant_id=tenant_id,
        session_id=session_id,
        customer_id=customer_id,
    )
    return {"reply": response, "session_id": session_id}

@app.get("/leads")
def get_leads(current_user: UserContext = Depends(get_current_user)):
    """
    Get leads.
    Super Admin (Tenant ID 1, Admin) sees all leads across the platform;
    Standard tenant staff/admins only see leads captured for their own business.
    """
    with Session(engine) as session:
        if current_user.tenant_id == 1 and current_user.role == "admin":
            leads = session.exec(select(Lead)).all()
        else:
            leads = session.exec(
                select(Lead).where(Lead.tenant_id == current_user.tenant_id)
            ).all()

    return [
        {
            "id": lead.id,
            "name": lead.name,
            "email": lead.email,
            "intent": lead.intent,
            "notes": lead.notes,
            "tenant_id": lead.tenant_id,  # Exposes the tenant ID for dashboard visibility
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        }
        for lead in leads
    ]


@app.get("/traces")
def get_traces(limit: int = 50, current_user: UserContext = Depends(get_current_user)):
    """
    Get agent performance traces.
    Super Admin (Tenant ID 1, Admin) sees all system traces across the platform;
    Standard tenant staff/admins only see traces logged for their own business.
    """
    with Session(engine) as session:
        if current_user.tenant_id == 1 and current_user.role == "admin":
            traces = session.exec(
                select(AgentTrace)
                .order_by(AgentTrace.created_at.desc())
                .limit(limit)
            ).all()
        else:
            traces = session.exec(
                select(AgentTrace)
                .where(AgentTrace.tenant_id == current_user.tenant_id)
                .order_by(AgentTrace.created_at.desc())
                .limit(limit)
            ).all()

    return [
        {
            "id": t.id,
            "session_id": t.session_id,
            "user_input": t.user_input[:100],
            "final_response": t.final_response[:200],
            "latency_ms": round(t.latency_ms, 1),
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "estimated_cost_usd": round(t.estimated_cost, 6),
            "faithfulness": round(t.faithfulness, 2),
            "hallucination_rate": round(t.hallucination_rate, 2),
            "retrieval_quality": round(t.retrieval_quality, 2),
            "tenant_id": t.tenant_id,  # Exposes the tenant ID for dashboard visibility
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in traces
    ]

@app.get("/tenants/public")
def get_tenants_public(session: Session = Depends(get_session)):
    """Public endpoint to list tenant metadata safely."""
    tenants = session.exec(select(Tenant)).all()
    return [{"id": t.id, "name": t.name} for t in tenants]

@app.get("/tenants")
def get_tenants(
    session: Session = Depends(get_session),
    current_user: UserContext = Depends(require_admin)
):
    """List all tenants. Admin only. Useful for the frontend tenant selector."""
    tenants = session.exec(select(Tenant)).all()
    return [{"id": t.id, "name": t.name} for t in tenants]

@app.post("/tenants")
def create_tenant(
    request: CreateTenantRequest,
    session: Session = Depends(get_session),
    current_user: UserContext = Depends(require_admin),
):
    """Creates a new dynamic tenant database workspace."""
    existing = session.exec(select(Tenant).where(Tenant.name == request.name)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Tenant '{request.name}' already exists.")

    new_tenant = Tenant(name=request.name)
    session.add(new_tenant)
    session.commit()
    session.refresh(new_tenant)

    return {
        "message": f"Tenant '{new_tenant.name}' created.",
        "id": new_tenant.id,
        "name": new_tenant.name,
    }

@app.get("/health")
def health_check():
    """Quick ping to verify the backend is running."""
    return {"status": "ok", "version": "2.0.0"}