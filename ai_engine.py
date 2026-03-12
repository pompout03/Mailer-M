import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# -- Configure Groq client safely -----------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

def categorize_and_summarize_email(subject: str, sender: str, body: str) -> dict:
    """
    Categorizes and summarizes an email using Groq/Llama.
    Aligned with the schema used in gemini_service.py.
    """
    if not client:
        print("[AIEngine] GROQ_API_KEY not set — returning default analysis.")
        return {
            "priority": "low",
            "summary": "AI service unavailable (no API key).",
            "category": "fyi"
        }

    prompt = f"""
    You are an AI Executive Assistant. 
    Analyze the following email and return a JSON object with these keys:
    1. "priority": One of: "high", "medium", or "low".
    2. "category": One of: "urgent", "meeting", "action", "form", "newsletter", or "fyi".
    3. "summary": A 15-word maximum summary of the email.
    
    Email Details:
    Sender: {sender}
    Subject: {subject}
    Body:
    {body}
    
    Return ONLY valid JSON.
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a specialized JSON-only output assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        response_content = completion.choices[0].message.content
        result = json.loads(response_content)
        
        # Normalize to ensure compatibility
        if result.get("priority") not in ["high", "medium", "low"]:
            result["priority"] = "low"
        if result.get("category") not in ["urgent", "meeting", "action", "form", "newsletter", "fyi"]:
            result["category"] = "fyi"
            
        return result
    except Exception as e:
        print(f"AI Error parsing email from {sender}: {e}")
        return {"priority": "low", "summary": "Error processing summary.", "category": "fyi"}

def answer_email_question(context: str, question: str) -> str:
    prompt = f"""
    You are an AI assistant. Answer the user's question based strictly on the provided email context.
    
    Email Context:
    {context}
    
    User Question:
    {question}
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"AI Error answering question: {e}")
        return "I'm sorry, I couldn't process your request right now."
