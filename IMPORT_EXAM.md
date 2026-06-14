# 📖 Exam Import Documentation

This document outlines the procedures and technical steps for importing official IGCSE exam papers into the ExamQ platform.

## 🚀 General Import Workflow

1.  **Locate Resources:** Ensure the Question Paper (QP) and Mark Scheme (MS) PDFs are available in the `resources/` folder.
2.  **Trigger API:** Use the `/api/admin/process-exam` endpoint (via the Admin UI or `curl`).
3.  **Background Processing:**
    *   **Text Extraction:** `pdftotext` extracts raw text.
    *   **Page Mapping:** AI and Regex identify question markers.
    *   **Image Generation:** `pdf2image` converts PDF pages to PNGs for the player.
    *   **Detail Extraction:** AI parses the Mark Scheme to match criteria with questions.

---

## 🏴󠁧󠁢󠁥󠁮󠁧󠁿 English Exam Import (Special Case)

English papers (e.g., 4EB1) differ significantly from Science/Maths papers in structure and marking.

### 1. Question Marker Identification
English papers often use descriptive phrasing instead of just numbers.
*   **Standard Regex:** `^\s*(\d+)\s+[A-Z]`
*   **English-Specific Regex:** `^\s*(\d+)\s+(?:In lines|State|Using|Identify|Explain|Describe|Discuss)`
*   **Manual Override:** If the AI fails to find questions, the `exam_server.py` regex must be updated to include the specific verb starting the question.

### 2. Extracts Booklet Detection
English papers usually come with a separate "Source Booklet" for reading texts.
*   **Detection Logic:** The importer looks for keywords like "Source Booklet" or "Do not return this booklet" to identify the starting page of the reading material.
*   **Storage:** These pages are stored in the `extract_pages` array in the JSON file to be displayed separately in the player.

### 3. Subject-Specific Logic
*   **Subject:** Must contain "English" in the title/path to trigger English-specific formatting.
*   **Import Command Example:**
    ```bash
    curl -X POST http://localhost:5001/api/admin/process-exam \
         -H "Content-Type: application/json" \
         -d '{
           "qp_path": "path/to/english_qp.pdf",
           "ms_path": "path/to/english_ms.pdf",
           "id": "English_June_2021_Heart_of_Darkness"
         }'
    ```

---

## 🧬 Science & Maths Exam Import

These papers are more structured and typically follow a predictable pattern.

### 1. Question Marker Identification
*   Follows a hierarchical structure: `1(a)(i)`, `1(a)(ii)`, etc.
*   The default regex `^\s*(\d+)\s+[A-Z]` and AI mapping handle these with high accuracy.

### 2. Question Types
*   **MCQ:** Automatically identified if options A-D are present.
*   **Calculation:** Identified by "Calculate" or "Show that" keywords; triggers a numeric input box in the player.
*   **Draw:** Triggered by "Complete the diagram" or "Draw"; awards full marks automatically with a visual check reminder.

### 3. Mathematical Formatting
*   Uses LaTeX-style rendering in some cases, though primarily relies on the PNG images of the original paper for accuracy.

---

## 🛠 Troubleshooting Failed Imports

*   **0 Questions Found:** Usually means the regex didn't match the paper's specific numbering style. Update `exam_server.py` and restart.
*   **Truncated Mark Scheme:** The AI might hit a token limit. The system includes a retry mechanism for low-quality `ms_text`.
*   **Image Path Errors:** Ensure the `id` provided during import matches the folder name in `static/exams/`.

---
*Last Updated: March 24, 2026*
