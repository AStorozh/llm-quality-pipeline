"""The checkpoint screen and the generation run itself."""
from __future__ import annotations

import time

from .. import (
    ai,
    api,
    checks,
    config,
    coursework,
    export,
    polish,
    requirements,
    review,
    style,
    usage,
)
from ..ui import (
    NAV_HINT,
    Color,
    Spinner,
    clear,
    error,
    option_line,
    select,
    success,
    wait_back,
    warn,
    wrap,
)
from .prompts import name_note, show_prompt_screen
from .settings import ensure_style, output_format_screen, require_ai


def prepare_and_write(session, discipline_name, topics, all_points, targets) -> None:
    """Checkpoint → AI prep screen → generate the work(s).

    The saved base prompt (from Settings) is the default. Editing the prompt
    here is a temporary override that applies only to this run; the next
    checkpoint starts again from the saved base. The output format, by
    contrast, is the same persistent setting as in AI settings, reachable
    from here so the format can be picked right before writing.
    """
    cfg = require_ai()
    if cfg is None:
        return
    if len(targets) == 1:
        subtitle = "Checkpoint: %s" % targets[0][1]["name"]
    else:
        subtitle = "Every checkpoint (%d)" % len(targets)

    style_profile = ensure_style()  # stable per user; appended to the prompt
    state = {"override": None}  # None → use the saved base from Settings

    def current_base() -> str:
        override = state["override"]
        return override if override is not None else config.get_system_prompt()

    def apply_once(text: str) -> str:
        # An empty text means "go back to the saved prompt", which is what
        # ``None`` means here; storing "" pinned the empty one instead.
        state["override"] = text or None
        return ("Back to the main prompt for this checkpoint." if not text
                else "Prompt changed for this checkpoint only.")

    labels = {"start": "Start: let the AI write",
              "formats": "Output format (.md / .docx / .pptx)",
              "prompt": "View or edit the prompt (this checkpoint only)"}
    while True:
        formats = config.get_formats()
        effective = (coursework.system_prompt(session.full_name, current_base(),
                                              slides="pptx" in formats)
                     + style.suffix(style_profile))
        note = ("main prompt" if state["override"] is None
                else "changed for this checkpoint only")
        header = [
            "  %s%s%s" % (Color.BOLD, discipline_name, Color.RESET),
            "  %s%s%s" % (Color.DIM, subtitle, Color.RESET),
            "",
            "  %sFormat:%s %s" % (Color.DIM, Color.RESET,
                                  ", ".join(export.FORMAT_LABELS[c] for c in formats)),
            "",
            "  %sAI prompt (%s):%s" % (Color.DIM, note, Color.RESET),
        ]
        header += ["  %s%s%s" % (Color.DIM, line, Color.RESET)
                   for line in wrap(effective, 72)[:3]]
        header += ["  %s…%s" % (Color.DIM, Color.RESET), ""]

        action = select(
            [("item", key) for key in labels],
            header_lines=header,
            hint=NAV_HINT,
            render_item=lambda value, selected: option_line(labels[value], selected),
            label_item=lambda value: labels[value],
        )
        if action is None:
            return
        if action == "start":
            _ai_write(session, cfg, discipline_name, topics, all_points, targets, effective)
            return
        if action == "formats":
            output_format_screen()  # the same persistent setting as in AI settings
            continue
        show_prompt_screen("AI prompt · this checkpoint only",
                       "The main prompt in AI settings stays untouched. "
                       + name_note(session.full_name),
                       current_base, apply_once)


# Shown after every generation. The model can be wrong about facts and knows
# nothing about the formatting a particular teacher expects, so the last word
# has to be the student's.
REVIEW_NOTICE = (
    "Strongly recommended before handing this in:",
    "read the work through yourself and check that the content is correct,",
    "then adjust the layout and formatting to your own requirements.",
)


def _report_checks(work: str, task_text: str, materials: str = "") -> None:
    """Run the automatic checks and show only what needs attention."""
    try:
        checklist = requirements.from_text(task_text)
        results = checks.run(work, checklist, materials)
    except Exception:  # noqa: BLE001 - a check must never break a finished run
        return
    bad = [r for r in results if r.status != checks.PASS]
    verdict = "%d/%d checks passed" % (sum(1 for r in results if r.ok), len(results))
    if not bad:
        print("     %schecks:%s %s" % (Color.DIM, Color.RESET, verdict))
        return
    print("     %schecks:%s %s" % (Color.DIM, Color.RESET, verdict))
    for result in bad:
        mark = error if result.status == checks.FAIL else warn
        mark("   %s: %s" % (result.name, result.detail))


def _second_look(cfg, session, label, answer, task_text, materials, spent):
    """One more pass over a structured work; always returns a usable text.

    A failed request, an unreadable answer or a bug here must never cost the
    finished work, so every path falls back to the text it was given.
    """
    if not config.get_self_review():
        return answer, None
    try:
        checklist = requirements.from_text(task_text)
        if not review.needs_review(checklist):
            return answer, None
        with Spinner("Checking the work against the task: %s" % label):
            outcome = review.review(cfg, answer, task_text, checklist, materials)
    except ai.AIError as exc:
        warn("%s: second look skipped: %s" % (label, exc))
        return answer, None
    except Exception:  # noqa: BLE001 - a second look must never break a run
        return answer, None
    spent.extend(outcome.replies)
    return outcome.text, outcome


def _report_review(outcome) -> None:
    """Say what the second look changed, so nothing changes silently."""
    if outcome is None:
        return
    if not outcome.changed:
        print("     %sreview:%s no changes needed" % (Color.DIM, Color.RESET))
    else:
        print("     %sreview:%s %d fix(es) applied"
              % (Color.DIM, Color.RESET, outcome.applied))
    for issue in outcome.issues[:5]:
        print("       %s- %s%s" % (Color.DIM, issue, Color.RESET))
    if outcome.rejected:
        print("     %sreview:%s %d suggestion(s) not applied, check the work by hand"
              % (Color.DIM, Color.RESET, len(outcome.rejected)))


def _ai_write(session, cfg, discipline_name, topics, all_points, targets, system):
    """Generate work for each target checkpoint, accumulating prior works."""
    directory = coursework.discipline_dir(discipline_name)
    prior_works = coursework.load_works_index(discipline_name)
    # Map a checkpoint id to its 1-based ordinal among all checkpoints.
    ordinals = {t["id"]: i + 1 for i, (_, t) in enumerate(all_points)}
    cache: dict = {}

    clear()
    print("  %s%s%s\n" % (Color.BOLD, discipline_name, Color.RESET))
    for index, checkpoint in targets:
        label = checkpoint["name"]
        number, title = coursework.checkpoint_label(label, ordinals.get(checkpoint["id"], 0))
        try:
            with Spinner("Preparing materials: %s" % label):
                prompt, task_text = coursework.build_prompt(
                    session.valid_token(), topics, index, prior_works, cache)

            started = time.time()
            spent = []
            with Spinner("AI is writing: %s" % label):
                reply = ai.complete(cfg, system, prompt)
            spent.append(reply)
            answer = polish.clean_answer(reply.text, session.full_name)
            truncated = reply.truncated

            # Models routinely undershoot a size the task states outright;
            # one follow-up request is cheaper than a work that loses marks.
            floor = coursework.volume_floor(task_text)
            if floor and len(answer.split()) < floor * coursework.VOLUME_TOLERANCE:
                with Spinner("Expanding to the required length: %s" % label):
                    reply = ai.complete(cfg, system,
                                        coursework.expansion_prompt(answer, task_text))
                spent.append(reply)
                expanded = polish.clean_answer(reply.text, session.full_name)
                # The follow-up replaces the first answer only if it really
                # grew; a shorter reply would lose work already written.
                if len(expanded.split()) > len(answer.split()):
                    answer, truncated = expanded, reply.truncated
                else:
                    warn("%s: the expanded version came back shorter, kept the first"
                         % label)

            answer, second = _second_look(cfg, session, label, answer,
                                          task_text, prompt, spent)

            run = usage.Run(cfg["model"],
                            sum(r.input_tokens for r in spent),
                            sum(r.output_tokens for r in spent),
                            label=label, seconds=time.time() - started)
            usage.record(run)
            results = export.save_all(
                directory,
                coursework.work_filename(number, discipline_name, session.initials),
                coursework.work_heading(discipline_name, number, title, session.full_name),
                answer,
                config.get_formats(),
            )

            prior_works[checkpoint["id"]] = answer
            coursework.save_works_index(discipline_name, prior_works)

            success("%s · %d words" % (label, len(answer.split())))
            if truncated:
                warn("   the answer hit the model's length limit and may be cut off,"
                     " check its ending")
            print("     %s%-5s:%s %s" % (Color.DIM, "cost", Color.RESET,
                                         usage.format_run(run, usage.prices(cfg))))
            _report_review(second)
            for code, path, err in results:
                if path:
                    print("     %s%-5s:%s %s"
                          % (Color.DIM, code, Color.RESET, path))
                else:
                    error("%s not saved: %s" % (code, err))
            _report_checks(answer, task_text, prompt)
        except ai.AIError as exc:
            error("%s: AI error: %s" % (label, exc))
        except api.ApiError as exc:
            error("%s: data error: %s" % (label, exc))
        # api.AuthError propagates: the menu asks the user to log in again.

    print("\n  %sFiles saved to:%s %s" % (Color.DIM, Color.RESET, directory))
    print()
    warn(REVIEW_NOTICE[0])
    for line in REVIEW_NOTICE[1:]:
        print("    %s%s%s" % (Color.DIM, line, Color.RESET))
    wait_back("Menu")
