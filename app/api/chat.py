from fastapi import APIRouter

from app.schemas import ChatRequest, ChatResponse
from app.services.conversation_service import generate_plain_reply

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return generate_plain_reply(
        user_id=request.user_id,
        message=request.message,
        channel=request.channel,
    )
