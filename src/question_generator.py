import os
import google.generativeai as genai

def generate_questions(topic: str, num_questions: int = 5) -> list[str]:
    """Generates N research questions for a given topic."""
    if os.getenv("MOCK_LLM", "false").lower() == "true":
        return [
            f"Mock Question 1 about {topic}?",
            f"Mock Question 2 about {topic}?",
            f"Mock Question 3 about {topic}?",
            f"Mock Question 4 about {topic}?",
            f"Mock Question 5 about {topic}?",
        ][:num_questions]

    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"Generate {num_questions} deep research questions about the topic '{topic}'. Return ONLY the questions, separated by newlines."

    response = model.generate_content(prompt)
    questions = [q.strip().lstrip('0123456789.- ') for q in response.text.strip().split('\n') if q.strip()]
    return questions[:num_questions]
