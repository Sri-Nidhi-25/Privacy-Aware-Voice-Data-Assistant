from pydantic import BaseModel
from typing import Dict, Any, Optional


class QueryResponse(BaseModel):
    original_audio_url: Optional[str] = ""
    obfuscated_audio_url: str
    answer_audio_url: str
    transcript: str
    answer_text: str
    metadata: Dict[str, Any]
