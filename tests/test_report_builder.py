import pytest
import os
from src.report_builder import build_markdown_report, build_pdf_report

@pytest.fixture
def sample_results():
    return [
        {
            "question": "What is A?",
            "answer": "A is the first letter.",
            "sources_mentioned": ["Alphabet Book"],
            "confidence": 0.99,
            "status": "done"
        },
        {
            "question": "What is B?",
            "answer": "Agent failed to retrieve answer after retries.",
            "sources_mentioned": [],
            "confidence": 0.0,
            "status": "failed"
        }
    ]

def test_build_markdown_report_structure(sample_results):
    md = build_markdown_report(sample_results, "Letters")
    assert "# Research Report: Letters" in md
    assert "## Executive Summary" in md
    assert "## Detailed Q&A" in md
    assert "## Conclusion" in md
    assert "### 1. What is A?" in md
    assert "### 2. What is B?" in md
    assert "[AGENT FAILED TO RETRIEVE ANSWER]" in md
    assert "A is the first letter." in md

def test_build_markdown_report_counts(sample_results):
    md = build_markdown_report(sample_results, "Letters")
    # 2 questions
    assert "addresses 2 distinct questions" in md

def test_build_pdf_report_creates_file(sample_results, tmp_path):
    output_file = str(tmp_path / "test_report.pdf")
    res = build_pdf_report(sample_results, "Letters", output_file)

    assert res == output_file
    assert os.path.exists(output_file)
    assert os.path.getsize(output_file) > 0

def test_empty_results_report():
    md = build_markdown_report([], "Empty")
    assert "addresses 0 distinct questions" in md
    assert "## Conclusion" in md
