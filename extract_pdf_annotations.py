#!/usr/bin/env python3
"""
PDF Annotation Extractor
=========================
Extracts highlighted text and comments from PDFs annotated in Adobe Acrobat.
Outputs a formatted text file with page numbers, highlighted text, and comments.

Usage:
    python extract_pdf_annotations.py INPUT [-o OUTPUT_DIR] [-r] [-m] [--verbose]

    INPUT             A PDF file or a directory containing PDFs.
    -o, --output-dir    Directory for output reports (default: alongside each PDF).
    -r, --recursive     Recurse into subdirectories when INPUT is a directory.
    -m, --markdown      Also convert each PDF to markdown via MarkItDown.
    --verbose           Enable debug-level logging.
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field

from pathlib import Path
from typing import List, Optional, Tuple, Dict

import fitz  # pymupdf
from markitdown import MarkItDown

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map pymupdf annot.type tuple -> human-readable name
ANNOT_TYPE_NAMES: Dict[tuple, str] = {
    (0,):  "TEXT NOTE",
    (8,):  "HIGHLIGHT",
    (9,):  "UNDERLINE",
    (10,): "STRIKEOUT",
    (11,): "SQUIGGLY",
    (12,): "FREETEXT",
}

# Annotation types that mark up underlying text (have rect-based text extraction)
MARKUP_ANNOT_TYPES = frozenset({(8,), (9,), (10,), (11,)})

# Annotation types that carry a /Contents comment body
COMMENT_ANNOT_TYPES = frozenset({(0,), (8,), (9,), (10,), (11,), (12,)})

REPORT_SEPARATOR = "=" * 80
PAGE_SEPARATOR = "-" * 80

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AnnotationEntry:
    page_number: int         # 0-based page index
    page_label: str          # Human-readable label (e.g. "1", "iii", "A-1")
    annot_type: str          # Human-readable type, e.g. "HIGHLIGHT"
    highlighted_text: str    # Text under the annotation rect
    comment_text: str        # Comment body
    author: str              # Annotation author
    subject: str             # Subject / category field


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-7s %(message)s",
    )


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

def get_page_label(page: fitz.Page) -> str:
    """Return the logical page label if PDF defines one, else 1-based number."""
    label = page.get_label()
    if label is not None and label != "":
        return label
    return str(page.number + 1)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_pdf_files(root_path: str, recursive: bool) -> List[Path]:
    """
    Given a file or directory path, return a sorted list of PDF Paths.
    """
    root = Path(root_path)
    if not root.exists():
        logging.error("Path does not exist: %s", root)
        sys.exit(1)

    if root.is_file():
        if root.suffix.lower() != ".pdf":
            logging.error("Not a PDF file: %s", root)
            sys.exit(1)
        return [root]

    # Directory
    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdfs = sorted(root.glob(pattern))
    if not pdfs:
        logging.warning("No PDF files found in %s", root)
    return pdfs


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_highlighted_text(page: fitz.Page, annot: fitz.Annot) -> str:
    """
    Extract the text underlying a markup annotation (Highlight, Underline, etc.)
    using the annotation's bounding rectangle.

    Falls back through: text mode → words mode → blocks mode.
    """
    rect = annot.rect

    # If rect is degenerate, attempt to recover from vertices
    if rect.is_empty or rect.width < 1 or rect.height < 1:
        vertices = getattr(annot, "vertices", None)
        if vertices and len(vertices) >= 4:
            try:
                # vertices is a list of point2d-like values: [x0,y0, x1,y1, x2,y2, x3,y3]
                xs = [vertices[i] for i in range(0, len(vertices), 2)]
                ys = [vertices[i] for i in range(1, len(vertices), 2)]
                rect = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
            except (IndexError, ValueError, TypeError):
                return ""

    if rect.is_empty or rect.width < 1 or rect.height < 1:
        return ""

    # Strategy 1: "text" mode — clean block-paragraph text
    text = page.get_text("text", clip=rect).strip()
    if text:
        return text

    # Strategy 2: "words" mode — join word tokens (more robust for some fonts)
    words = page.get_text("words", clip=rect)
    if words:
        # words is a list of (x0, y0, x1, y1, word_str, block_no, line_no, word_no)
        return " ".join(w[4] for w in words).strip()

    # Strategy 3: "blocks" mode — block-level extraction
    blocks = page.get_text("blocks", clip=rect)
    if blocks:
        lines = []
        for block in blocks:
            if block[6].strip():  # block[6] is the text content
                lines.append(block[6].strip())
        return " ".join(lines)

    return ""


# ---------------------------------------------------------------------------
# Comment resolution
# ---------------------------------------------------------------------------

def resolve_comment_for_markup_annot(
    annot: fitz.Annot,
    annot_by_xref: Dict[int, fitz.Annot],
    doc: fitz.Document,
) -> str:
    """
    Resolve the comment text attached to a markup annotation (Highlight,
    Underline, StrikeOut, Squiggly).

    Uses three strategies in order:
    1. Direct /Contents on the annotation itself
    2. Follow /Popup xref to a linked Text annotation
    3. Search for a Text annotation whose /IRT points to this annot's xref
    """

    # Strategy 1: /Contents directly on the highlight
    info = annot.info
    content = info.get("content", "").strip() if info else ""
    if content:
        return content

    my_xref = annot.xref

    # Strategy 2: /Popup link
    popup_xref = getattr(annot, "popup", 0)
    if popup_xref and popup_xref in annot_by_xref:
        popup_annot = annot_by_xref[popup_xref]
        popup_info = popup_annot.info
        if popup_info:
            popup_content = popup_info.get("content", "").strip()
            if popup_content:
                return popup_content

    # Strategy 3: Search for a Text annotation with /IRT pointing here
    for other_xref, other_annot in annot_by_xref.items():
        if other_annot.type[0] == 0:  # Text (sticky note)
            irt = getattr(other_annot, "irt", 0)
            if irt == my_xref:
                other_info = other_annot.info
                if other_info:
                    other_content = other_info.get("content", "").strip()
                    if other_content:
                        return other_content

    return ""


# ---------------------------------------------------------------------------
# Entry building
# ---------------------------------------------------------------------------

def build_annotation_entry(
    doc: fitz.Document,
    page: fitz.Page,
    page_num: int,
    annot: fitz.Annot,
    annot_by_xref: Dict[int, fitz.Annot],
) -> Optional[AnnotationEntry]:
    """
    Classify an annotation, extract its text and/or comment, and return an
    AnnotationEntry. Returns None for annotation types we intentionally skip.
    """
    annot_type_raw = annot.type
    # Normalise to (type,) for consistent comparisons (newer pymupdf may return (type, flags))
    annot_type = (annot_type_raw[0],)

    # Determine human-readable type name
    type_name = ANNOT_TYPE_NAMES.get(annot_type, f"OTHER({annot_type[0]})")

    info = annot.info or {}

    # Extract author and subject
    author = info.get("title", "")
    subject = info.get("subject", "")

    highlighted_text = ""
    comment_text = ""

    if annot_type in MARKUP_ANNOT_TYPES:
        # These types mark up underlying text
        highlighted_text = extract_highlighted_text(page, annot)
        comment_text = resolve_comment_for_markup_annot(annot, annot_by_xref, doc)

    elif annot_type == (0,):  # Text / sticky note
        # Standalone comment — extract text under rect if any, plus the comment
        highlighted_text = extract_highlighted_text(page, annot)
        comment_text = info.get("content", "").strip()

    elif annot_type == (12,):  # FreeText
        highlighted_text = extract_highlighted_text(page, annot)
        comment_text = info.get("content", "").strip()

    else:
        # Catch-all for Caret, Ink, Stamp, etc.
        # Try to extract whatever text/content is available
        highlighted_text = extract_highlighted_text(page, annot)
        comment_text = info.get("content", "").strip()

    # Skip entries that have no text and no comment
    if not highlighted_text and not comment_text:
        return None

    return AnnotationEntry(
        page_number=page_num,
        page_label=get_page_label(page),
        annot_type=type_name,
        highlighted_text=highlighted_text,
        comment_text=comment_text,
        author=author,
        subject=subject,
    )


# ---------------------------------------------------------------------------
# Page processing
# ---------------------------------------------------------------------------

def process_page(
    doc: fitz.Document,
    page: fitz.Page,
    page_num: int,
) -> List[AnnotationEntry]:
    """
    Process all annotations on a single page. Builds an xref→annot lookup
    for resolving popup/IRT links, then dispatches each annotation.
    """
    entries: List[AnnotationEntry] = []

    annots = list(page.annots())
    if not annots:
        return entries

    # Build xref → annot lookup (for link resolution)
    annot_by_xref: Dict[int, fitz.Annot] = {}
    for a in annots:
        if a.xref != 0:
            annot_by_xref[a.xref] = a

    for annot in annots:
        try:
            entry = build_annotation_entry(doc, page, page_num, annot, annot_by_xref)
            if entry is not None:
                entries.append(entry)
        except Exception:
            logging.warning(
                "Failed to process annotation xref=%d on page %d",
                annot.xref,
                page_num + 1,
                exc_info=True,
            )

    return entries


# ---------------------------------------------------------------------------
# PDF-level processing
# ---------------------------------------------------------------------------

def process_single_pdf(
    pdf_path: Path,
    output_dir: Optional[Path] = None,
    markdown: bool = False,
) -> Tuple[int, List[AnnotationEntry]]:
    """
    Open a PDF, iterate all pages collecting annotation entries, and write
    an output report if any entries were found.

    If output_dir is None, the report is written alongside the PDF.
    If markdown is True, also convert the PDF to markdown via MarkItDown.

    Returns (entry_count, entries_list).
    """
    logging.info("Processing: %s", pdf_path)

    try:
        doc = fitz.open(str(pdf_path))
    except fitz.FileDataError:
        logging.error("Skipping corrupted PDF: %s", pdf_path)
        return 0, []
    except fitz.FileNotFoundError:
        logging.error("Skipping unopenable PDF: %s", pdf_path)
        return 0, []
    except Exception:
        logging.error("Skipping (encrypted or unreadable): %s", pdf_path)
        return 0, []

    all_entries: List[AnnotationEntry] = []
    try:
        if doc.needs_pass:
            logging.warning("Skipping password-protected PDF: %s", pdf_path)
            return 0, []

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_entries = process_page(doc, page, page_num)
            all_entries.extend(page_entries)
            if page_entries:
                logging.debug(
                    "  Page %d: %d annotation(s)",
                    page_num + 1,
                    len(page_entries),
                )
    finally:
        doc.close()

    out_dir = output_dir or pdf_path.parent

    if all_entries:
        output_text = format_output(pdf_path, all_entries)
        out_path = write_output_file(output_text, pdf_path, out_dir)
        logging.info("  → Wrote %d entries to %s", len(all_entries), out_path)
    else:
        logging.info("  → No annotations found.")

    if markdown:
        try:
            convert_pdf_to_markdown(pdf_path, out_dir)
        except Exception:
            logging.warning("  → Markdown conversion failed", exc_info=True)

    return len(all_entries), all_entries


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_output(pdf_path: Path, entries: List[AnnotationEntry]) -> str:
    """
    Produce a human-readable string report from a list of AnnotationEntry
    objects.
    """
    lines: List[str] = []
    # Header
    lines.append(REPORT_SEPARATOR)
    lines.append("PDF ANNOTATION REPORT")
    lines.append(f"File: {pdf_path.name}")
    lines.append(f"Total Annotations: {len(entries)}")
    lines.append(REPORT_SEPARATOR)
    lines.append("")

    # Group entries by page
    prev_page = -1
    entry_num = 0

    for entry in entries:
        if entry.page_number != prev_page:
            if prev_page != -1:
                lines.append("")  # blank between pages
            lines.append(f"--- Page {entry.page_number + 1} (label: \"{entry.page_label}\") ---")
            lines.append("")
            prev_page = entry.page_number

        entry_num += 1

        # Type line
        type_line = f"[{entry_num}] {entry.annot_type}"
        lines.append(type_line)

        # Highlighted text
        if entry.highlighted_text:
            text = entry.highlighted_text
            # Wrap long text
            indent = "    "
            lines.append(f'{indent}Text: "{text}"')

        # Comment
        if entry.comment_text:
            comment = entry.comment_text
            indent = "    "
            lines.append(f"{indent}Comment: {_wrap_text(comment, indent, 76)}")
        else:
            # Only show "(no comment)" for markup types where a comment is expected
            if entry.annot_type in ANNOT_TYPE_NAMES.values() and entry.annot_type != "TEXT NOTE":
                lines.append("    Comment: (no comment)")

        lines.append("")

    # Footer
    lines.append(REPORT_SEPARATOR)
    lines.append("END OF REPORT")
    lines.append(REPORT_SEPARATOR)

    return "\n".join(lines)


def _wrap_text(text: str, indent: str, max_width: int) -> str:
    """
    Wrap multi-line comment text so each continuation line is indented.
    Lines that fit in max_width are left as-is; longer lines are hard-wrapped.
    """
    lines = text.splitlines()
    result_lines: List[str] = []

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        while len(line) > max_width:
            # Find a good break point
            break_at = line.rfind(" ", 0, max_width)
            if break_at == -1:
                break_at = max_width
            result_lines.append(line[:break_at].rstrip())
            line = " " * len(indent) + line[break_at:].lstrip()

        if i == 0:
            result_lines.append(line)
        else:
            # Continuation lines get extra indentation
            result_lines.append(" " * len(indent) + line)

    return "\n".join(result_lines) if result_lines else text


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------

def write_output_file(text_content: str, pdf_path: Path, output_dir: Path) -> Path:
    """
    Write the formatted report to disk. Creates the output directory if needed.

    Output filename: {pdf_stem}_annotations.txt
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = f"{pdf_path.stem}_annotations.txt"
    output_path = output_dir / output_name
    output_path.write_text(text_content, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Markdown conversion (MarkItDown)
# ---------------------------------------------------------------------------

def convert_pdf_to_markdown(pdf_path: Path, output_dir: Path) -> Path:
    """
    Convert a PDF to markdown using MarkItDown and write the result to disk.

    Output filename: {pdf_stem}.md

    Returns the path to the written markdown file.
    """
    logging.info("  → Converting to markdown via MarkItDown ...")
    md = MarkItDown()
    result = md.convert(str(pdf_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = f"{pdf_path.stem}.md"
    output_path = output_dir / output_name
    output_path.write_text(result.text_content, encoding="utf-8")
    logging.info("  → Wrote markdown to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract highlighted text and comments from Adobe Acrobat annotated PDFs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python extract_pdf_annotations.py review.pdf
  python extract_pdf_annotations.py review.pdf -m
  python extract_pdf_annotations.py ./pdfs/ -r -m
  python extract_pdf_annotations.py review.pdf -o ./reports
  python extract_pdf_annotations.py review.pdf --verbose
        """,
    )
    parser.add_argument(
        "input",
        metavar="INPUT",
        help="PDF file or directory containing PDFs",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Directory for output reports (default: alongside each PDF)",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Recurse into subdirectories when INPUT is a directory",
    )
    parser.add_argument(
        "-m", "--markdown",
        action="store_true",
        help="Also convert each PDF to markdown via MarkItDown",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    output_dir = Path(args.output_dir) if args.output_dir else None

    # Discover PDFs
    pdf_files = find_pdf_files(args.input, args.recursive)
    if not pdf_files:
        logging.warning("No PDF files to process.")
        return

    logging.info("Found %d PDF file(s) to process.", len(pdf_files))

    # Process each PDF
    total_entries = 0
    files_with_annotations = 0
    for pdf_path in pdf_files:
        count, _ = process_single_pdf(pdf_path, output_dir, markdown=args.markdown)
        if count > 0:
            files_with_annotations += 1
        total_entries += count

    # Summary
    print(f"\nDone. Processed {len(pdf_files)} file(s).")
    print(f"  Files with annotations: {files_with_annotations}")
    print(f"  Total annotations extracted: {total_entries}")


if __name__ == "__main__":
    main()
