# multiagent-research
Input topic → AI generates N questions → N parallel Gemini agents → structured Markdown + PDF report.

## Setup

1. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file in the root directory and add your Gemini API key and other configurations:
   ```
   GEMINI_API_KEY=your_api_key_here
   MAX_CONCURRENT=5
   MOCK_LLM=false
   ```

## Running the App

Run the Streamlit application using:

```bash
PYTHONPATH=. streamlit run app.py
```

## Running Tests

Run the test suite with:

```bash
PYTHONPATH=. pytest
```
