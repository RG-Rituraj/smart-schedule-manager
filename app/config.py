import os
from dataclasses import dataclass
from typing import Any
from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm

load_dotenv()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")  # Gemini API key only

@dataclass
class AgentConfig:
    # Reads model from environment GEMINI_MODEL. Default local model ollama_chat/gemma2.
    model: Any = LiteLlm(model=os.getenv("LOCAL_MODEL", "ollama_chat/gemma2"))
    mcp_server_port: int = 8090
    max_iterations: int = 3
    pii_redaction_enabled: bool = True
    injection_detection_enabled: bool = True

config = AgentConfig()

