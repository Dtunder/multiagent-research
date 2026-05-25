import os
import asyncio
from src.research_agent import research_question

async def run_research(questions: list[str], topic: str) -> list[dict]:
    """Runs research questions concurrently, limited by MAX_CONCURRENT."""
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "5"))
    semaphore = asyncio.Semaphore(max_concurrent)

    async def sem_task(question: str):
        async with semaphore:
            return await research_question(question, topic)

    tasks = [sem_task(q) for q in questions]
    results = await asyncio.gather(*tasks)

    return list(results)
