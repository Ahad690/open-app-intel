"""User-facing reminders (e.g. the post-run contribute nudge).

Colors are applied only when writing to a real terminal, so CI/log output stays
clean (no escape codes). The reminder is on by default and can be silenced via
``federation.contribute_reminder = false`` in config.json.
"""
from __future__ import annotations

import sys

# ANSI colors (only emitted to a TTY).
_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"


def _supports_color(stream) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def contribute_reminder_text(dataset_repo: str, color: bool) -> str:
    """Build the reminder block (colored or plain).

    Intentionally ASCII-only (besides optional ANSI color codes) so it never
    raises UnicodeEncodeError on a legacy Windows code page (cp1252).
    """

    def c(code: str, text: str) -> str:
        return f"{code}{text}{_RESET}" if color else text

    bar = c(_MAGENTA, "=" * 64)
    return "\n".join(
        [
            bar,
            f"{c(_BOLD + _CYAN, '>> Help sharpen estimates for everyone -- contribute your anchors!')}",
            f"   Your captured install-bucket deltas become {c(_GREEN, 'public calibration anchors')}",
            "   that tighten download estimates for the whole community.",
            "",
            f"     {c(_YELLOW, 'python -m appscope.federation.contribute --dry-run')}        # preview what is shared",
            f"     {c(_YELLOW, 'python -m appscope.federation.contribute --contributor <you>')}  # open a PR (needs HF_TOKEN)",
            "",
            f"   Only {c(_GREEN, 'public app-store facts')} are shared -- never ads, creators, or identity.",
            f"   Dataset: {c(_CYAN, dataset_repo)}",
            f"   {c(_BOLD, 'Silence this:')} set federation.contribute_reminder = false in config.json",
            bar,
        ]
    )


def print_contribute_reminder(cfg, stream=None) -> None:
    """Print the contribute reminder if enabled in config (no-op otherwise).

    Never lets a console-encoding issue crash the caller (the reminder is a
    courtesy, not core work).
    """
    if not getattr(cfg.federation, "contribute_reminder", True):
        return
    stream = stream or sys.stdout
    text = contribute_reminder_text(cfg.federation.dataset_repo, _supports_color(stream))
    try:
        print(text, file=stream)
    except UnicodeEncodeError:  # pragma: no cover - defensive on exotic consoles
        print(text.encode("ascii", "replace").decode("ascii"), file=stream)
