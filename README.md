# PDF Annotation Extractor & Review Generator

A Python toolkit for extracting Adobe Acrobat annotations (highlights + comments) from PDFs, converting PDFs to markdown, and generating professional academic paper reviews using an LLM.

## Features

- **Annotation extraction** — Extracts highlighted text and linked comments from PDFs annotated in Adobe Acrobat. Supports Highlight, Underline, StrikeOut, Squiggly, Text Note, and FreeText annotations.
- **Markdown conversion** — Converts PDFs to markdown via [MarkItDown](https://github.com/microsoft/markitdown) for easy reading and LLM processing.
- **Review generation** — Uses an LLM (DeepSeek, OpenAI/ChatGPT, or Anthropic Claude) to synthesize a professional academic review from the paper content and reviewer annotations.
- **No API key required** — The core extraction and markdown conversion work without any API key. Review generation is an optional extra step.

## Requirements

- Python 3.10 or later
- The dependencies listed in `requirements.txt`

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/pdf-review-toolkit.git
cd pdf-review-toolkit

# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate      # macOS / Linux
# or: venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose |
|---|---|
| `pymupdf` | Reading PDFs and accessing Adobe Acrobat annotations |
| `markitdown` | Converting PDFs to markdown |
| `openai` | Calling DeepSeek and OpenAI APIs for review generation |
| `anthropic` | Calling Anthropic Claude API for review generation |

## Usage

### Step 1: Extract Annotations & Convert to Markdown

```bash
# Basic: extract annotations only
python extract_pdf_annotations.py paper.pdf

# Extract annotations + convert to markdown
python extract_pdf_annotations.py paper.pdf -m

# Process all PDFs in a directory recursively
python extract_pdf_annotations.py ./pdfs/ -r -m

# Specify a custom output directory
python extract_pdf_annotations.py paper.pdf -m -o ./reports

# Verbose logging
python extract_pdf_annotations.py paper.pdf -m --verbose
```

**Output files** (written alongside each PDF by default):
- `{paper_name}_annotations.txt` — extracted highlights and comments
- `{paper_name}.md` — markdown version of the PDF (if `-m` is used)

### Step 2: Generate a Review (Optional — Requires LLM API Key)

```bash
# Set your API key
# DeepSeek (default):
export DEEPSEEK_API_KEY="sk-your-key-here"       # macOS / Linux
set DEEPSEEK_API_KEY=sk-your-key-here            # Windows CMD
$env:DEEPSEEK_API_KEY = "sk-your-key-here"       # Windows PowerShell

# Run review generation
python generate_review.py paper.md paper_annotations.txt

# Use a different provider
python generate_review.py paper.md paper_annotations.txt -p openai
python generate_review.py paper.md paper_annotations.txt -p claude

# Custom output path
python generate_review.py paper.md paper_annotations.txt -o my_review.md
```

**Output**: `{paper_name}_review.md` — a structured academic review.

### Supported LLM Providers

| Provider | `-p` flag | Environment Variable | Model Used |
|---|---|---|---|
| DeepSeek | `deepseek` (default) | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| OpenAI / ChatGPT | `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| Anthropic Claude | `claude` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5-20250901` |

### No API Key?

If you don't have an LLM API key, the tool still works — just skip Step 2. You'll get the markdown paper and extracted annotations, which you can use for manual review or paste into any LLM chat interface.

## Review Output Format

The generated review follows a flexible structure:

- **Summary** — Overview of the paper plus an overall assessment and recommendation (e.g., "I would suggest the following revisions…").
- **Major Comments** — Included only when there are substantive concerns about methodology, assumptions, or contributions.
- **Minor Comments** — Smaller issues like typos, notation, figure quality, or suggestions.

Each comment point references its location in the paper using page numbers, section names, or quoted text — no artificial titles or internal annotation IDs.

## Annotation Report Format

```
================================================================================
PDF ANNOTATION REPORT
File: paper.pdf
Total Annotations: 15
================================================================================

--- Page 6 (label: "6") ---

[1] HIGHLIGHT
    Text: "We consider two activity patterns for the interfering source..."
    Comment: any results for spatial and temporal?

[2] HIGHLIGHT
    Text: "In contrast, we consider a different model mismatch..."
    Comment: ever existed before? any literature for this problem?
...
================================================================================
END OF REPORT
================================================================================
```

## How It Works

### Annotation Linking

Adobe Acrobat stores annotations in the PDF using several linking mechanisms. The extractor resolves highlight-to-comment relationships through three strategies:

1. **Direct content** — The highlight annotation itself contains the comment in its `/Contents` entry.
2. **Popup reference** — The highlight links to a popup Text annotation via `/Popup`.
3. **Reply chain** — A Text annotation points back to the highlight via `/IRT` (In Reply To).

### Text Extraction

Highlighted text is extracted from the PDF using the annotation's bounding rectangle, with fallbacks through multiple extraction modes (`text` → `words` → `blocks`) to handle different font encodings.

## Limitations

- Annotations must be created in Adobe Acrobat (other PDF editors may use different annotation structures).
- Encrypted/password-protected PDFs are skipped.
- The review quality depends on the chosen LLM and the thoroughness of the annotations.
- Very long papers may be truncated to fit within the LLM's context window (80,000 characters by default).

## License

MIT

## Contributing

Issues and pull requests are welcome.
