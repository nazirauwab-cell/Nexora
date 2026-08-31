from fastapi import FastAPI
from pydantic import BaseModel
import os


app = FastAPI(title="Nexora AI API")


class ChatRequest(BaseModel):
    message: str


@app.get("/")
def home():
    return {
        "name": "Nexora",
        "status": "online"
    }


@app.post("/chat")
def chat(request: ChatRequest):

    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        return {
            "error": "OpenRouter API key is not configured."
        }

    result = ask_nexora(
        api_key,
        request.message
    )

    if result is None:
        return {
            "error": "Nexora could not get a response."
        }

    answer = get_answer(result)

    return {
        "answer": answer
    }
