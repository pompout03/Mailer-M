import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def categorize_and_summarize_email(subject: str, sender: str, body: str) -> dict:
    prompt = f"""
    You are an AI Executive Assistant. 
    Analyze the following email and return a JSON object exactly with these two keys:
    1. "priority": One of exactly: "URGENT", "IMPORTANT", or "LOW_PRIORITY".
    2. "summary": A 15-word maximum summary of the email.
    
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
        return json.loads(response_content)
    except Exception as e:
        print(f"AI Error parsing email from {sender}: {e}")
        return {"priority": "LOW_PRIORITY", "summary": "Error processing summary."}

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
