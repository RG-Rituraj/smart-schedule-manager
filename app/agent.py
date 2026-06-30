import datetime
import json
import logging
import re
from typing import Any, AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.workflow import Workflow, START
from google.genai import types
from mcp import StdioServerParameters
from pydantic import BaseModel, Field

from .config import config

# Logger setup
logger = logging.getLogger("smart_scheduler")

# 1. Pydantic models for structured interaction
class MeetingProposal(BaseModel):
    title: str = Field(description="The meeting title")
    proposed_time_pst: str = Field(description="Suggested meeting time in PST/PDT timezone")
    proposed_time_est: str = Field(description="Suggested meeting time in EST/EDT timezone")
    recipient_email: str = Field(description="Email address of the participant")
    email_draft: str = Field(description="Polite drafted email body inviting the participant")

# 2. Setup MCP Toolset to connect to our local server
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp_server"],
        )
    )
)

# Specialized sub-agents with MCP tools wired in
timezone_resolver = LlmAgent(
    name="timezone_resolver",
    model=config.model,
    instruction="""
    You are a timezone coordination specialist.
    Your task is to identify the recipient's timezone and propose 2-3 optimal meeting slots.
    Coordinate between PST and EST. Check the calendar using the MCP tools to ensure no conflicts.
    """,
    description="Resolves timezone differences and suggests optimal free meeting slots.",
    tools=[mcp_toolset]
)

draft_generator = LlmAgent(
    name="draft_generator",
    model=config.model,
    instruction="""
    You are a professional email drafter.
    Your task is to write a polite and concise email invitation to the client offering the suggested meeting slots.
    """,
    description="Drafts professional email replies and calendar invitations based on suggested times.",
    tools=[mcp_toolset]
)

# 3. Main Orchestrator LLM Agent
orchestrator = LlmAgent(
    name="orchestrator",
    model=config.model,
    instruction="""
    You are the head coordinator for the Smart Schedule Manager.
    Your goal is to coordinate meeting times across timezones and draft professional replies.
    
    You have access to:
    1. timezone_resolver: to check the client's timezone and suggest optimal slots.
    2. draft_generator: to draft a professional reply email.
    
    Use timezone_resolver first to get the correct time options.
    Then, pass the selected time options to draft_generator to create the email draft.
    Finally, return the structured output matching the output schema.
    """,
    tools=[AgentTool(timezone_resolver), AgentTool(draft_generator)],
    output_schema=MeetingProposal,
    output_key="proposal"
)

# 4. Workflow nodes (functions)

def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    """Performs safety checks, PII scrubbing, and prompt injection detection."""
    text = ""
    if hasattr(node_input, 'parts'):
        text = " ".join([p.text for p in node_input.parts if p.text])
    elif isinstance(node_input, str):
        text = node_input
        
    # PII scrubbing: redact emails
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    scrubbed_text = re.sub(email_pattern, "[REDACTED_EMAIL]", text)
    ctx.state["scrubbed_input"] = scrubbed_text
    
    # Prompt injection detection
    injection_keywords = ["ignore instructions", "system prompt", "override role", "bypass security"]
    has_injection = any(kw in text.lower() for kw in injection_keywords)
    
    # Domain-specific rule (block keyword 'hack' or 'spam')
    is_blocked_topic = "hack" in text.lower() or "spam" in text.lower()
    
    audit_data = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "session_id": ctx.session.id,
        "input_length": len(text),
        "pii_redacted": text != scrubbed_text,
        "injection_detected": has_injection,
        "blocked_topic": is_blocked_topic
    }
    
    if has_injection or is_blocked_topic:
        audit_data["severity"] = "CRITICAL"
        logger.warning(json.dumps(audit_data))
        return Event(
            output="Security Violation: Input was flagged by the security checkpoint.",
            route="SECURITY_EVENT"
        )
        
    audit_data["severity"] = "INFO"
    logger.info(json.dumps(audit_data))
    return Event(
        output=scrubbed_text,
        route="proceed"
    )

async def human_approval(ctx: Context, node_input: MeetingProposal) -> AsyncGenerator[Event, None]:
    """Requests human approval for the proposed meeting and email draft."""
    if ctx.resume_inputs and "approved" in ctx.resume_inputs:
        decision = ctx.resume_inputs["approved"]
        if decision.lower() in ["yes", "approve", "y"]:
            ctx.state["approved"] = True
            yield Event(
                content=types.Content(
                    role='model',
                    parts=[types.Part.from_text(f"✅ Meeting approved! Proceeding with email draft for {node_input.recipient_email}...")],
                )
            )
            yield Event(
                output=node_input,
                route="approved"
            )
        else:
            ctx.state["approved"] = False
            yield Event(
                content=types.Content(
                    role='model',
                    parts=[types.Part.from_text("❌ Meeting request was denied by human.")],
                )
            )
            yield Event(
                output=node_input,
                route="denied"
            )
        return

    # Prompt the human for input
    yield Event(
        content=types.Content(
            role='model',
            parts=[types.Part.from_text(
                f"Proposed Meeting Details:\n"
                f"- Title: {node_input.title}\n"
                f"- Recipient: {node_input.recipient_email}\n"
                f"- Time (PST): {node_input.proposed_time_pst}\n"
                f"- Time (EST): {node_input.proposed_time_est}\n\n"
                f"Draft Email:\n```\n{node_input.email_draft}\n```\n\n"
                f"Approve this meeting? (yes/no)"
            )]
        )
    )
    yield RequestInput(
        interrupt_id="approved",
        message="Approve this meeting? (yes/no)"
    )

def final_node(ctx: Context, node_input: Any) -> Event:
    """Formats the final workflow response."""
    if isinstance(node_input, str):
        return Event(
            content=types.Content(role='model', parts=[types.Part.from_text(node_input)]),
            output=node_input
        )
        
    approved = ctx.state.get("approved", False)
    if approved:
        message = f"Process finished. The meeting '{node_input.title}' was approved and scheduled for {node_input.recipient_email}."
    else:
        message = "Process finished. The meeting request was rejected."
        
    return Event(
        content=types.Content(role='model', parts=[types.Part.from_text(message)]),
        output=message
    )

# 5. Define root agent workflow
root_agent = Workflow(
    name="smart_schedule_workflow",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {
            "proceed": orchestrator,
            "SECURITY_EVENT": final_node
        }),
        (orchestrator, human_approval),
        (human_approval, final_node)
    ]
)

# 6. Container App
app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
