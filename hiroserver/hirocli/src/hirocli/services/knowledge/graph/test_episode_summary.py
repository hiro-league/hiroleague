"""Unit tests for the graph-episode transcript cleaner (picker tooltip)."""

from hirocli.services.knowledge.graph.episode_summary import clean_episode_transcript

# A default 3-exchange window as rendered by memory.windowing._render_body.
_WINDOW = (
    "[2026-07-08 09:56] Misho: Ya id like to hear a joke\n"
    "[2026-07-08 09:56] Hiro (AI): You got it, Misho! Here's one.\n"
    "[2026-07-08 09:58] Misho: note: make it about cats\n"
    "[2026-07-08 09:58] Hiro (AI): Why was the cat sitting on the computer?\n"
)


def test_strips_inline_stamps_but_keeps_turns_and_line_breaks() -> None:
    out = clean_episode_transcript(_WINDOW)
    assert "[" not in out and "]" not in out  # no bracketed dates remain
    assert out.splitlines()[0] == "Misho: Ya id like to hear a joke"
    assert out.splitlines()[1] == "Hiro (AI): You got it, Misho! Here's one."
    assert out.count("\n") == 3  # four turns → three line breaks


def test_message_text_with_colon_is_preserved() -> None:
    assert clean_episode_transcript("[2026-07-08 09:58] Misho: note: buy milk").endswith(
        "Misho: note: buy milk"
    )


def test_knowledge_free_text_passes_through() -> None:
    body = "The Eiffel Tower is a wrought-iron lattice tower in Paris, completed in 1889."
    assert clean_episode_transcript(body) == body


def test_blank_lines_dropped() -> None:
    assert clean_episode_transcript("\n\n[2026-07-08 09:56] Misho: hi\n\n") == "Misho: hi"


def test_empty_content() -> None:
    assert clean_episode_transcript("") == ""


def test_clipped_with_ellipsis() -> None:
    out = clean_episode_transcript("x" * 5000)
    assert out.endswith("…")
    assert len(out) <= 701
