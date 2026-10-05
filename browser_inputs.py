"""browser_inputs.py: Helper functions and data structures for resolving run inputs in Streamlit UI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RunInputs:
    """Resolved inputs ready to pass to the research pipeline."""
    topic: str
    context: str
    is_valid: bool = True
    error_message: Optional[str] = None


def resolve_run_inputs(
    topic: str = "",
    context: str = "",
    problem_file_name: Optional[str] = None,
    problem_file_text: Optional[str] = None,
    max_first_line_len: int = 120,
) -> RunInputs:
    """Combines user-provided topic, context, and optional uploaded problem file.

    Combining rules:
    - If only the topic/context fields are filled: topic is the stripped topic,
      context is the stripped context.
    - If a problem file is uploaded and the topic field is empty: use the file's
      first non-empty line (trimmed to max_first_line_len chars) as the topic,
      and the full file text appended to the context.
    - If a problem file is uploaded and the topic field is also filled: keep the
      typed topic, and append the full file text to the context (with separator:
      '--- From uploaded file: <filename> ---').
    - If neither topic nor file is present (or file is whitespace-only and topic is empty):
      returns is_valid=False.
    """
    clean_topic = topic.strip() if topic else ""
    clean_context = context.strip() if context else ""
    has_file = problem_file_text is not None and len(problem_file_text.strip()) > 0
    clean_file_text = problem_file_text.strip() if problem_file_text else ""
    filename = problem_file_name.strip() if problem_file_name else "uploaded_file"

    if not clean_topic and not has_file:
        return RunInputs(
            topic="",
            context=clean_context,
            is_valid=False,
            error_message="Please enter a research topic or upload a problem file.",
        )

    if has_file:
        file_block = f"--- From uploaded file: {filename} ---\n{clean_file_text}"
        combined_context = f"{clean_context}\n\n{file_block}" if clean_context else file_block

        if clean_topic:
            final_topic = clean_topic
        else:
            # Extract first non-empty line
            lines = [line.strip() for line in problem_file_text.splitlines() if line.strip()]
            first_line = lines[0] if lines else ""
            if not first_line:
                return RunInputs(
                    topic="",
                    context=clean_context,
                    is_valid=False,
                    error_message="Uploaded problem file contains no readable text.",
                )
            final_topic = first_line[:max_first_line_len].strip()

        return RunInputs(
            topic=final_topic,
            context=combined_context,
            is_valid=True,
            error_message=None,
        )

    # Only topic (and optional context) provided
    return RunInputs(
        topic=clean_topic,
        context=clean_context,
        is_valid=True,
        error_message=None,
    )
