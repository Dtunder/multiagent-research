import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

def build_markdown_report(results: list[dict], topic: str) -> str:
    """Builds a Markdown report from research results."""
    md = f"# Research Report: {topic}\n\n"
    md += "## Executive Summary\n"
    md += f"This report contains automated research findings for the topic: **{topic}**. It addresses {len(results)} distinct questions.\n\n"

    md += "## Detailed Q&A\n\n"
    for i, result in enumerate(results, 1):
        md += f"### {i}. {result['question']}\n\n"
        if result['status'] == 'failed':
            md += "**[AGENT FAILED TO RETRIEVE ANSWER]**\n\n"
        else:
            md += f"{result['answer']}\n\n"
            if result['sources_mentioned']:
                md += "**Sources:** " + ", ".join(result['sources_mentioned']) + "\n\n"
            md += f"*Confidence: {result.get('confidence', 0.0):.2f}*\n\n"

    md += "## Conclusion\n"
    md += "End of automated research report.\n"

    return md

def build_pdf_report(results: list[dict], topic: str, output_path: str) -> str:
    """Builds a PDF report from research results."""
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    Story = []

    Story.append(Paragraph(f"Research Report: {topic}", styles['Title']))
    Story.append(Spacer(1, 12))

    Story.append(Paragraph("Executive Summary", styles['Heading2']))
    Story.append(Paragraph(f"This report contains automated research findings for the topic: {topic}. It addresses {len(results)} distinct questions.", styles['Normal']))
    Story.append(Spacer(1, 12))

    Story.append(Paragraph("Detailed Q&A", styles['Heading2']))
    Story.append(Spacer(1, 12))

    for i, result in enumerate(results, 1):
        Story.append(Paragraph(f"{i}. {result['question']}", styles['Heading3']))

        if result['status'] == 'failed':
            Story.append(Paragraph("[AGENT FAILED TO RETRIEVE ANSWER]", styles['Normal']))
        else:
            Story.append(Paragraph(result['answer'].replace('\n', '<br />'), styles['Normal']))
            Story.append(Spacer(1, 6))
            if result['sources_mentioned']:
                Story.append(Paragraph(f"<b>Sources:</b> {', '.join(result['sources_mentioned'])}", styles['Normal']))
            Story.append(Paragraph(f"<i>Confidence: {result.get('confidence', 0.0):.2f}</i>", styles['Normal']))
        Story.append(Spacer(1, 12))

    Story.append(Paragraph("Conclusion", styles['Heading2']))
    Story.append(Paragraph("End of automated research report.", styles['Normal']))

    doc.build(Story)
    return output_path
