import os
import asyncio
import streamlit as st
from dotenv import load_dotenv

from src.question_generator import generate_questions
from src.orchestrator import run_research
from src.report_builder import build_markdown_report, build_pdf_report

load_dotenv()

def main():
    st.set_page_config(page_title="MultiAgent-Research MVP", layout="wide")
    st.title("MultiAgent-Research MVP")
    st.write("Autonomous multi-agent deep research engine.")

    topic = st.text_input("Enter research topic:")
    num_questions = st.slider("Number of questions to generate", min_value=1, max_value=20, value=5)

    custom_questions_input = st.text_area("Or enter custom questions (one per line):", help="Leave blank to auto-generate questions.")

    if st.button("Run Research"):
        if not topic and not custom_questions_input:
            st.error("Please enter a topic or custom questions.")
            return

        with st.spinner("Generating questions..."):
            if custom_questions_input.strip():
                questions = [q.strip() for q in custom_questions_input.split('\n') if q.strip()]
            else:
                questions = generate_questions(topic, num_questions)

        st.write("### Research Questions")
        for i, q in enumerate(questions, 1):
            st.write(f"{i}. {q}")

        st.write("### Agent Progress")
        progress_bars = [st.progress(0, text=f"Agent {i+1}: Waiting...") for i in range(len(questions))]

        async def run_with_progress():
            tasks = []
            for i, q in enumerate(questions):
                # We create tasks wrapping the single research call to update its own progress bar
                # Note: streamlit's asynchronous context is tricky, so we update the progress bars synchronously
                # after gather, or we can use an asyncio.as_completed loop to update them in place.
                pass

            # Better approach for Streamlit: we will modify the orchestrator call or just use a loop with run_research and a wrapper.
            # However, since run_research returns a list of results and doesn't take callbacks,
            # we'll implement a wrapper that updates the progress bar.

            max_concurrent = int(os.getenv("MAX_CONCURRENT", "5"))
            semaphore = asyncio.Semaphore(max_concurrent)

            from src.research_agent import research_question

            async def sem_task_with_ui(index, question):
                progress_bars[index].progress(10, text=f"Agent {index+1}: Starting...")
                async with semaphore:
                    progress_bars[index].progress(50, text=f"Agent {index+1}: Researching...")
                    res = await research_question(question, topic)
                    progress_bars[index].progress(100, text=f"Agent {index+1}: Complete!")
                    # Keep original order by returning index
                    return index, res

            tasks = [sem_task_with_ui(i, q) for i, q in enumerate(questions)]
            completed_results = await asyncio.gather(*tasks)

            # Sort by index to maintain order
            completed_results.sort(key=lambda x: x[0])
            return [res[1] for res in completed_results]

        results = asyncio.run(run_with_progress())

        st.success("Research complete!")

        md_report = build_markdown_report(results, topic)

        st.markdown("---")
        st.write("### Report Preview")
        st.markdown(md_report)

        pdf_path = "research_report.pdf"
        build_pdf_report(results, topic, pdf_path)

        st.markdown("---")
        with open(pdf_path, "rb") as f:
            st.download_button(
                label="Download PDF Report",
                data=f,
                file_name="research_report.pdf",
                mime="application/pdf"
            )

if __name__ == "__main__":
    main()
