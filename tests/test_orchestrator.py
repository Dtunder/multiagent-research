import os
import pytest
import asyncio
from src.orchestrator import run_research
from src.question_generator import generate_questions

@pytest.fixture(autouse=True)
def mock_llm_env(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "true")

def test_generate_questions():
    questions = generate_questions("Quantum Computing", 3)
    assert len(questions) == 3
    assert all("Mock Question" in q for q in questions)

def test_generate_questions_default():
    questions = generate_questions("Quantum Computing")
    assert len(questions) == 5

@pytest.mark.asyncio
async def test_run_research_returns_correct_count():
    questions = ["Q1", "Q2", "Q3"]
    results = await run_research(questions, "Topic")
    assert len(results) == 3
    for res in results:
        assert res["status"] == "done"
        assert res["answer"].startswith("Mock answer")

@pytest.mark.asyncio
async def test_run_research_empty_questions():
    results = await run_research([], "Topic")
    assert len(results) == 0

@pytest.mark.asyncio
async def test_run_research_concurrency(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT", "2")
    questions = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    results = await run_research(questions, "Topic")
    assert len(results) == 5
    assert [res["question"] for res in results] == questions

@pytest.mark.asyncio
async def test_run_research_handles_failure(monkeypatch):
    # Temporarily turn off MOCK_LLM so we can mock a failure
    monkeypatch.setenv("MOCK_LLM", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "fake_key")

    # We will patch the research_question to raise an exception or we can
    # just rely on the fact that an invalid key with no retries will fail.
    # To make it fast, we can mock the generate_content_async function.
    class MockModel:
        async def generate_content_async(self, prompt):
            raise Exception("API Error")

    import google.generativeai as genai
    monkeypatch.setattr(genai, "GenerativeModel", lambda name: MockModel())

    # Speed up sleep
    import asyncio

    # Save the original sleep
    original_sleep = asyncio.sleep
    async def mock_sleep(delay):
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    questions = ["Q1"]
    results = await run_research(questions, "Topic")

    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert results[0]["answer"] == "Agent failed to retrieve answer after retries."
