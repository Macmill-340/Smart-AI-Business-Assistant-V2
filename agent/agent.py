import os
import time
import uuid
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from dotenv import load_dotenv
from agent.rag import retrieve_context
from agent.memory import get_preference,extract_and_save_preferences
from agent.tools import all_tools, save_lead, search_web, send_email, get_current_datetime
from backend.database import engine, AgentTrace
from sqlmodel import Session

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite",
    api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0.3,
)

llm_with_tools = llm.bind_tools(all_tools)

#state
class AgentState(TypedDict):
    user_input: str
    tenant_id: int
    session_id: str
    customer_id: str
    messages: list
    intent: str
    retrieved_docs: str
    tool_results: str
    final_answer: str
    start_time: float
    input_tokens: int
    output_tokens: int

#node1
def planner_node(state: AgentState) -> dict:
    """
    Analyzes the user's intent and routes to the right node.
    Also loads long-term memory and extracts new preferences.
    """
    query = state["user_input"]
    tenant_id = state["tenant_id"]
    customer_id = state["customer_id"]
    long_term_memory = get_preference(customer_id, tenant_id)
    try:
        extract_and_save_preferences(customer_id, tenant_id, query, llm)
    except Exception:
        pass
    classification_message = [
        SystemMessage(content=f"""
        You are an intent router for a business AI assistant.
     
        {long_term_memory}
         
        Classify the user's message into exactly one of: RAG, LEAD, TOOL, or CHAT.

        RAG — user asks a factual question about products, services, pricing, policies, or documents.
          Examples: "What are your laptop prices?", "Do you offer warranties?",
                    "What was AeroFlux founded?", "Tell me about your return policy"
        
        LEAD — user wants to buy, place an order, or shares contact info.
          Examples: "I want to buy 5 laptops", "I am John and I want to order bicycles",
                    "My email is john@example.com", "I'd like to purchase your premium plan"
        
        TOOL — user needs real-time info, current date/time, or web search.
          Examples: "What's today's date?", "Search for the latest iPhone price",
                    "What time is it?", "Find me competitors of this product"
        
        CHAT — small talk, greetings, or general questions with no business intent.
          Examples: "Hello!", "How are you?", "Thanks", "What can you do?"
        
        Reply with ONLY the single intent word. No explanation, no punctuation."""),
        HumanMessage(content=query)
    ]
    response = llm.invoke(classification_message)
    intent_raw = response.text.strip().upper()
    if "RAG"in intent_raw:
        intent = "RAG"
    elif "LEAD" in intent_raw:
        intent = "LEAD"
    elif "TOOL" in intent_raw:
        intent = "TOOL"
    else:
        intent = "CHAT"

    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

    return {
        "intent": intent,
        "input_tokens": state.get("input_tokens", 0) + input_tokens,
        "output_tokens": state.get("output_tokens", 0) + output_tokens,
    }

#node2
def retriever_node(state: AgentState) -> dict:
    """
    Performs hybrid retrieval (BM25 + vector + rerank) for RAG queries.
    Only called when the Planner sets intent to RAG.
    """
    query = state["user_input"]
    tenant_id = state["tenant_id"]

    retrieved = retrieve_context(query, tenant_id, k=3)
    return {"retrieved_docs": retrieved}

#node3
def executor_node(state: AgentState) -> dict:
    intent = state["intent"]
    query = state["user_input"]
    tenant_id = state["tenant_id"]
    messages = state.get("messages", [])
    total_input_tokens = state.get("input_tokens", 0)
    total_output_tokens = state.get("output_tokens", 0)
    tool_results = ""

    if intent == "RAG":
        tool_results = state.get("retrieved_docs", "")

    elif intent == "LEAD":
        customer_id = state.get("customer_id", "anonymous")
        customer_email_hint = ""
        # Inform the LLM if we already know the customer's email from the input form
        if "@" in customer_id:
            customer_email_hint = f"The customer's email is already known as: {customer_id}."

        lead_messages = [
            SystemMessage(content=f"""You are a lead capture assistant.
Extract the customer's details and save them using the save_lead tool.
The tenant_id is {tenant_id}. You MUST always pass exactly this tenant_id value.
Do not guess or change the tenant_id.
{customer_email_hint}
Use intent 'hot' if they want to buy now, 'warm' if interested, 'cold' if just browsing."""),
            *messages[-4:],
            HumanMessage(content=query)
        ]
        response = llm_with_tools.invoke(lead_messages)

        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                # Automatically fallback to inject the sidebar email if missing from the LLM arguments
                if tool_name == "save_lead":
                    if "@" in customer_id and not tool_args.get("email"):
                        tool_args["email"] = customer_id

                tool_map = {t.name: t for t in all_tools}
                if tool_name in tool_map:
                    result = tool_map[tool_name].invoke(tool_args)
                    tool_results += f"{tool_name} result: {result}\n"

                    if tool_name == "save_lead" and tool_args.get("intent") == "hot":
                        notification_email = os.getenv("NOTIFICATION_EMAIL", "admin@example.com")
                        if notification_email:
                            # Clean, human-readable email format instead of a raw dictionary
                            body_str = f"""A hot lead was captured for your workspace.

                    Lead Details:
                    - Name: {tool_args.get('name', 'Unknown')}
                    - Email: {tool_args.get('email', 'Not provided')}
                    - Intent: {tool_args.get('intent', 'hot').upper()}
                    - Notes: {tool_args.get('notes', 'None')}
                    - Tenant ID: {tool_args.get('tenant_id', tenant_id)}

                    Please review this lead in your Staff Dashboard."""

                            email_result = send_email.invoke({
                                "recipient_email": notification_email,
                                "subject": f"Hot Lead Captured: {tool_args.get('name', 'Unknown')}",
                                "body": body_str
                            })
                            tool_results += f"Email notification: {email_result}\n"
        else:
            tool_results = "Lead details could not be extracted. Please ask the customer for their name."

        usage = getattr(response, "usage_metadata", None)
        total_input_tokens += getattr(usage, "input_tokens", 0) if usage else 0
        total_output_tokens += getattr(usage, "output_tokens", 0) if usage else 0

    elif intent == "TOOL":
        tool_messages = [
            SystemMessage(content="""You are a helpful assistant with access to tools.
Use the right tool for the question:
- get_current_datetime: for any question about today's date or current time
- search_web: for questions needing current information not in the knowledge base
- send_email: only when explicitly asked to send a notification or email"""),
            *messages[-4:],
            HumanMessage(content=query)
        ]
        response = llm_with_tools.invoke(tool_messages)

        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_map = {t.name: t for t in all_tools}
                if tool_name in tool_map:
                    result = tool_map[tool_name].invoke(tool_args)
                    tool_results += f"{tool_name}: {result}\n"
        else:
            tool_results = response.text

        usage = getattr(response, "usage_metadata", None)
        total_input_tokens += getattr(usage, "input_tokens", 0) if usage else 0
        total_output_tokens += getattr(usage, "output_tokens", 0) if usage else 0

    return {
        "tool_results": tool_results,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    }

#node4
def critic_node(state: AgentState) -> dict:
    """
    Generates the final polished response, evaluates quality,
    and writes an AgentTrace to the database.
    """
    query = state["user_input"]
    intent = state["intent"]
    retrieved_docs = state.get("retrieved_docs", "")
    tool_results = state.get("tool_results", "")
    messages = state.get("messages", [])
    tenant_id = state["tenant_id"]
    session_id = state["session_id"]

    total_input_tokens = state.get("input_tokens", 0)
    total_output_tokens = state.get("output_tokens", 0)

    #step1: generate final answer
    if intent == "RAG":
        system_prompt = """You are a helpful business assistant. Answer the user's
        question using ONLY the provided context. If the context doesn't contain
        the answer, say "I don't have that information in my knowledge base."
        Always cite which source your answer came from."""
        context_block = f"\n\nContext from knowledge base:\n{retrieved_docs}"
    elif intent == "LEAD":
        system_prompt = """You are a friendly sales assistant. A lead was just captured.
        Write a warm, professional 1-2 sentence confirmation to the customer."""
        context_block = f"\n\nSystem action taken: {tool_results}"
    elif intent == "TOOL":
        system_prompt = """You are a helpful assistant. Use the tool results provided
        to give the user a clear, direct answer."""
        context_block = f"\n\nTool results: {tool_results}"
    else:
        system_prompt = """You are a friendly AI assistant for a business.
        Respond naturally and helpfully to the user's message."""
        context_block = ""

    final_messages = [
        SystemMessage(content=system_prompt),
        *messages[-6:],
        HumanMessage(content=query + context_block)
    ]

    response = llm.invoke(final_messages)
    final_answer = response.text

    usage = getattr(response, "usage_metadata", None)
    total_input_tokens += getattr(usage, "input_tokens", 0) if usage else 0
    total_output_tokens += getattr(usage, "output_tokens", 0) if usage else 0

    #step2: llm as judge
    faithfulness = 1.0
    hallucination_rate= 0.0
    retrieval_quality = 1.0

    if intent == "RAG" and retrieved_docs:
        try:
            eval_prompt =f"""
            Evaluate this AI response on a scale of 0.0 to 1.0.
             
            Context provided: {retrieved_docs[:600]}
            User question: {query}
            AI response: {final_answer}
             
            Respond with ONLY these three lines, no extra text:
            faithfulness: [0.0-1.0]
            hallucination: [0.0-1.0]
            retrieval_quality: [0.0-1.0]
             
            faithfulness: 1.0 means the response is fully supported by the context.
            hallucination: 0.0 means no hallucination (good). 1.0 means fully hallucinated.
            retrieval_quality: 1.0 means the context was highly relevant to the question.
            """
            eval_response = llm.invoke(eval_prompt)
            eval_text = eval_response.text.strip()

            for line in eval_text.split("\n"):
                if "faithfulness:" in line:
                    faithfulness = float(line.split(":")[1].strip())
                elif "hallucination:" in line:
                    hallucination_rate = float(line.split(":")[1].strip())
                elif "retrieval_quality:" in line:
                    retrieval_quality = float(line.split(":")[1].strip())

            eval_usage = getattr(eval_response, "usage_metadata", None)
            total_input_tokens += getattr(eval_usage, "input_tokens", 0) if eval_usage else 0
            total_output_tokens += getattr(eval_usage, "output_tokens", 0) if eval_usage else 0
        except Exception:
            pass

    #calculate cost and latency, write AgentTrace
    # Gemini 3.1 Flash Lite approximate pricing (as of 2026):
    # Input: $0.25 per 1M tokens → $0.00000025 per token
    # Output: $1.50 per 1M tokens → $0.0000015 per token
    COST_PER_INPUT_TOKEN = 0.00000025
    COST_PER_OUTPUT_TOKEN = 0.0000015
    estimated_cost = (
            total_input_tokens * COST_PER_INPUT_TOKEN +
            total_output_tokens * COST_PER_OUTPUT_TOKEN
    )
    #latency
    start_time = state.get("start_time", time.time())
    latency_ms = (time.time() - start_time) * 1000

    #write trace to db
    try:
        with Session(engine) as session:
            trace = AgentTrace(
                session_id=session_id,
                user_input=query,
                final_response=final_answer,
                latency_ms=latency_ms,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                estimated_cost=estimated_cost,
                faithfulness=faithfulness,
                hallucination_rate=hallucination_rate,
                retrieval_quality=retrieval_quality,
                tenant_id=tenant_id
            )
            session.add(trace)
            session.commit()
    except Exception as e:
        print(f"Failed to write AgentTrace: {e}")
    return {
        "final_answer": final_answer,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    }

def route_after_planner(state: AgentState) -> str:
    if state["intent"] == "RAG":
        return "retriever"
    return "executor"

#graph
workflow = StateGraph(AgentState)

workflow.add_node("planner", planner_node)
workflow.add_node("retriever", retriever_node)
workflow.add_node("executor", executor_node)
workflow.add_node("critic", critic_node)

workflow.set_entry_point("planner")

workflow.add_conditional_edges(
    "planner",
    route_after_planner,
    {
        "retriever": "retriever",
        "executor": "executor",
    }
)
workflow.add_edge("retriever", "executor")
workflow.add_edge("executor", "critic")
workflow.add_edge("critic", END)

graph = workflow.compile()

def run_agent(
    user_input: str,
    history: list,
    tenant_id: int = 1,
    session_id: str = None,
    customer_id: str = "anonymous"
) -> str:
    """
    Main entry point called by the FastAPI /chat endpoint.

    Args:
        user_input:  The customer's latest message.
        history:     List of past messages: [{"role": "user"/"assistant", "content": "..."}]
        tenant_id:   Which business workspace this chat belongs to.
        session_id:  Unique ID for this session (generated if not provided).
        customer_id: Customer identifier (email if known, else session_id).

    Returns:
        The agent's final response as a plain string.
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    lc_message = []
    for msg in history[-8:]:
        if msg["role"] == "user":
            lc_message.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_message.append(AIMessage(content=msg["content"]))

    result = graph.invoke({
        "user_input": user_input,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "customer_id": customer_id,
        "messages": lc_message,
        "intent": "",
        "retrieved_docs": "",
        "tool_results": "",
        "final_answer": "",
        "start_time": time.time(),
        "input_tokens": 0,
        "output_tokens": 0,
    })

    answer = result.get("final_answer", "I'm sorry, I couldn't process that request.")
    if isinstance(answer, list):
        answer = " ".join(str(a) for a in answer)
    elif not isinstance(answer, str):
        answer = str(answer)

    return answer.strip()