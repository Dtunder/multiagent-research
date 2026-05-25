import os
import asyncio
import json
import google.generativeai as genai

async def research_question(question: str, topic_context: str = "") -> dict:
    """Researches a question and returns a structured dictionary."""
    if os.getenv("MOCK_LLM", "false").lower() == "true":
        return {
            "question": question,
            "answer": f"Mock answer for {question}",
            "sources_mentioned": ["mock source 1", "mock source 2"],
            "confidence": 0.95,
            "status": "done"
        }

    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"""
    Topic context: {topic_context}
    Question: {question}

    Provide a detailed answer to the question. Return the response as a JSON object with the following keys:
    - answer: The detailed answer.
    - sources_mentioned: A list of general sources, references, or entities mentioned.
    - confidence: A float between 0.0 and 1.0 indicating confidence.

    Output ONLY valid JSON.
    """

    backoffs = [2, 4, 8]

    for delay in backoffs:
        try:
            # We use to_async to wrap the synchronous generate_content call if the library doesn't expose an async method directly,
            # or just use generate_content_async if it does. generate_content_async is preferred.
            response = await model.generate_content_async(prompt)

            try:
                # Remove markdown formatting if present
                text = response.text.strip()
                if text.startswith("```json"):
                    text = text[7:]
                if text.endswith("```"):
                    text = text[:-3]

                data = json.loads(text.strip())
                return {
                    "question": question,
                    "answer": data.get("answer", ""),
                    "sources_mentioned": data.get("sources_mentioned", []),
                    "confidence": data.get("confidence", 0.0),
                    "status": "done"
                }
            except json.JSONDecodeError:
                # If JSON parsing fails, just return text as answer
                return {
                    "question": question,
                    "answer": response.text,
                    "sources_mentioned": [],
                    "confidence": 0.5,
                    "status": "done"
                }

        except Exception as e:
            if delay != backoffs[-1]:
                await asyncio.sleep(delay)

    return {
        "question": question,
        "answer": "Agent failed to retrieve answer after retries.",
        "sources_mentioned": [],
        "confidence": 0.0,
        "status": "failed"
    }
