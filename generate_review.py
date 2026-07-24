#!/usr/bin/env python3
"""
Paper Review Generator
======================
Generates a professional academic review from a paper (markdown) and
reviewer annotations (extracted comments).  Requires an LLM API key.

Usage:
    python generate_review.py PAPER.md ANNOTATIONS.txt [-p PROVIDER] [-o OUTPUT]

Providers:
    deepseek    DeepSeek API (default) — set DEEPSEEK_API_KEY
    openai      OpenAI / ChatGPT — set OPENAI_API_KEY
    claude      Anthropic Claude — set ANTHROPIC_API_KEY

Without an API key the script prints a message and exits gracefully;
the markdown and annotations files can still be used for manual review.
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

PROVIDERS = {
    "deepseek": {
        "env_var": "DEEPSEEK_API_KEY",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1",
        "package": "openai",
    },
    "openai": {
        "env_var": "OPENAI_API_KEY",
        "model": "gpt-4o",
        "base_url": None,  # uses openai default
        "package": "openai",
    },
    "claude": {
        "env_var": "ANTHROPIC_API_KEY",
        "model": "claude-sonnet-4-5-20250901",
        "base_url": None,
        "package": "anthropic",
    },
}

# ---------------------------------------------------------------------------
# System prompt for the review
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an editor, not a reviewer. Your task is to transform a set of \
informal reviewer annotations into a polished, well-organized review. \
Do NOT add any new thoughts, critiques, or evaluations of the paper that \
are not already present in the annotations. Do not assess the paper yourself. \
You only reorganize and rephrase what the reviewer already wrote.

Begin the review with a top-level title: **Review for "[paper title]"** — \
extract the paper title from the paper content provided.

The review body should include:

- A **Summary** that derives from the annotations' overall tone and \
substance. Briefly describe the paper's topic (as reflected in the annotated \
text) and summarize the thrust of the feedback in 2–3 sentences. \
End with the implied recommendation in 1–2 sentences — for example: "The \
paper has merit but requires revisions to strengthen its contribution. I \
suggest the following changes."

After the Summary, group the comments into sections that fit the nature of \
the annotations:

- **Major Comments** — Include this section ONLY when some annotations raise \
substantive concerns (methodology, assumptions, missing analysis, core \
clarity). Omit it completely if all comments are minor.
- **Minor Comments** — Smaller issues: typos, notation, figure quality, \
suggestions. Omit only if there are truly no minor points.

Do not force both sections. A paper with only minor notes gets only Minor \
Comments. Comment points should be numbered within each section.

Guidelines:
- **Only use the provided annotations.** Every comment in your output must \
trace back to one or more of the reviewer's annotations. Do not fabricate, \
extrapolate, or add your own opinions about the paper.
- For each comment point, do NOT invent a title or heading. Start directly \
with the location in the paper where the concern arises, using page numbers, \
section names, paragraph context, or short quotes from the original text.
- Never reference annotation numbers, comment IDs, or any artifact of the \
annotation extraction process. The review must stand alone.
- Rewrite each informal comment in professional, precise, academic language. \
Preserve the core concern or suggestion, but make it more fluent and accurate.
- If multiple annotations address the same topic, merge them into a single \
coherent point.
- Write in first-person ("I suggest…", "I find…", "I recommend…"), as if you \
are the reviewer. Never use third-person phrasing like "The reviewer \
suggests…" or "The reviewer expects…".
- Be constructive: for every criticism, suggest a path to improvement (if \
the annotation implies one).
- Maintain a professional, respectful tone throughout.
- Do not address the authors directly as "you".

Parts of the input will include reviewer annotations (highlighted text from \
the paper paired with a reviewer's informal comment). These are your ONLY \
source material for the review."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-7s %(message)s",
    )


def read_text_file(path: Path) -> str:
    """Read a text file and return its content as a string."""
    if not path.exists():
        logging.error("File not found: %s", path)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def build_user_prompt(paper_md: str, annotations: str) -> str:
    """Construct the user prompt combining the paper and reviewer annotations."""
    # Truncate the paper if it exceeds ~80k chars (reasonable context window)
    MAX_PAPER_CHARS = 80_000
    paper_section = paper_md
    if len(paper_md) > MAX_PAPER_CHARS:
        paper_section = paper_md[:MAX_PAPER_CHARS]
        paper_section += f"\n\n[... paper truncated at {MAX_PAPER_CHARS} characters; "
        paper_section += f"original length {len(paper_md)} characters ...]\n"

    prompt = f"""\
Below is a research paper (markdown) followed by reviewer annotations \
(highlighted text and informal comments extracted from the PDF). The paper \
is provided only so you can locate where each comment applies.

============================================================
PAPER (for context and locating comment references)
============================================================
{paper_section}

============================================================
REVIEWER ANNOTATIONS — your ONLY source material
============================================================
{annotations}

============================================================

Transform the reviewer annotations into a polished, well-organized review. \
Do NOT add your own opinions or evaluate the paper yourself. Only integrate, \
rephrase, and organize the annotations provided above. Every point in your \
output must come from these annotations."""

    return prompt


# ---------------------------------------------------------------------------
# LLM backends
# ---------------------------------------------------------------------------

def _call_deepseek(api_key: str, model: str, base_url: str, system: str, user: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content


def _call_openai(api_key: str, model: str, base_url: Optional[str], system: str, user: str) -> str:
    from openai import OpenAI

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content


def _call_claude(api_key: str, model: str, system: str, user: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[
            {"role": "user", "content": user},
        ],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a professional paper review from markdown + annotations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_review.py paper.md paper_annotations.txt
  python generate_review.py paper.md paper_annotations.txt -p openai
  python generate_review.py paper.md paper_annotations.txt -o review.md
        """,
    )
    parser.add_argument(
        "paper_md",
        metavar="PAPER.md",
        help="Markdown version of the paper (from extract_pdf_annotations.py -m)",
    )
    parser.add_argument(
        "annotations",
        metavar="ANNOTATIONS.txt",
        help="Extracted comments file (from extract_pdf_annotations.py)",
    )
    parser.add_argument(
        "-p", "--provider",
        default="deepseek",
        choices=list(PROVIDERS.keys()),
        help="LLM provider (default: deepseek)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output file path (default: {paper_stem}_review.md alongside the paper markdown)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    provider = PROVIDERS[args.provider]

    # --- Check API key ---
    api_key = os.environ.get(provider["env_var"], "")
    if not api_key:
        print(
            f"No API key found for provider '{args.provider}'.\n"
            f"Set the {provider['env_var']} environment variable to generate a review.\n"
            f"\n"
            f"The markdown paper and annotations files are ready for manual review:\n"
            f"  Paper:       {args.paper_md}\n"
            f"  Annotations: {args.annotations}\n"
        )
        return

    # --- Read inputs ---
    paper_md = read_text_file(Path(args.paper_md))
    annotations = read_text_file(Path(args.annotations))

    system_prompt = SYSTEM_PROMPT
    user_prompt = build_user_prompt(paper_md, annotations)

    logging.info("Paper: %d characters", len(paper_md))
    logging.info("Annotations: %d characters", len(annotations))
    logging.info("Calling %s (%s) ...", args.provider, provider["model"])

    # --- Call LLM ---
    try:
        if args.provider == "deepseek":
            review = _call_deepseek(
                api_key, provider["model"], provider["base_url"],
                system_prompt, user_prompt,
            )
        elif args.provider == "openai":
            review = _call_openai(
                api_key, provider["model"], provider["base_url"],
                system_prompt, user_prompt,
            )
        elif args.provider == "claude":
            review = _call_claude(
                api_key, provider["model"],
                system_prompt, user_prompt,
            )
        else:
            logging.error("Unknown provider: %s", args.provider)
            sys.exit(1)
    except Exception as e:
        logging.error("LLM call failed: %s", e)
        sys.exit(1)

    if not review:
        logging.error("LLM returned an empty response.")
        sys.exit(1)

    # --- Write output ---
    paper_path = Path(args.paper_md)
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = paper_path.parent / f"{paper_path.stem}_review.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(review, encoding="utf-8")
    logging.info("Review written to %s", output_path)
    print(f"\nReview generated successfully: {output_path}")


if __name__ == "__main__":
    main()
