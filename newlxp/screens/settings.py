"""AI settings: provider key, model, output formats and writing style."""
from __future__ import annotations

import sys

from .. import ai, config, export, style, usage
from ..session import Session
from ..ui import (
    NAV_HINT,
    Color,
    Spinner,
    clear,
    error,
    info,
    option_line,
    secret_input,
    select,
    success,
    wait_back,
)
from .prompts import edit_saved_prompt


def configure_ai(session: Session | None = None) -> None:
    """AI settings menu: token, model, system prompt, style and formats."""
    student_name = session.full_name if session else ""
    labels = {"token": "Enter or change the AI key",
              "model": "Choose the AI model",
              "prompt": "System prompt (view or edit)",
              "style": "Writing style (random profile)",
              "formats": "Output format (.md / .docx / .pptx)",
              "usage": "Usage and cost"}
    screens = {"token": _set_token,
               "model": _model_screen,
               "prompt": lambda: edit_saved_prompt(student_name),
               "style": _style_screen,
               "formats": output_format_screen,
               "usage": usage_screen}
    while True:
        cfg = config.load()
        formats = ", ".join(export.FORMAT_LABELS[c] for c in config.get_formats())
        header = [
            "  %sAI settings%s" % (Color.BOLD, Color.RESET),
            "  %sKey:%s    %s" % (Color.DIM, Color.RESET,
                                  config.PROVIDERS[cfg["provider"]]["label"]
                                  if cfg else "not connected"),
            "  %sModel:%s  %s" % (Color.DIM, Color.RESET, cfg["model"] if cfg else "—"),
            "  %sFormat:%s %s" % (Color.DIM, Color.RESET, formats),
            "",
        ]
        action = select(
            [("item", key) for key in labels],
            header_lines=header,
            hint=NAV_HINT,
            render_item=lambda value, selected: option_line(labels[value], selected),
            label_item=lambda value: labels[value],
        )
        if action is None:
            return
        screens[action]()


def _set_token() -> None:
    """Prompt for a provider, API key and model, and store them."""
    provider = select(
        [("item", key) for key in config.PROVIDERS],
        header_lines=["  %sAI provider%s\n" % (Color.BOLD, Color.RESET)],
        hint=NAV_HINT,
        render_item=lambda key, selected: option_line(
            config.PROVIDERS[key]["label"], selected),
        label_item=lambda key: config.PROVIDERS[key]["label"],
    )
    if provider is None:
        return

    clear()
    print("  %s%s%s" % (Color.BOLD, config.PROVIDERS[provider]["label"], Color.RESET))
    print("  %s(empty line or q cancels)%s\n" % (Color.DIM, Color.RESET))
    try:
        key = secret_input("  API key: ").strip()
    except (KeyboardInterrupt, EOFError):
        return
    if not key or key.lower() == "q":
        return

    # Leaving the model list keeps the default model.
    model = _choose_model(provider, key) or config.default_model(provider)
    clear()
    if config.save(provider, key, model):
        success("Key saved. Model: %s" % model)
    else:
        error("Could not write %s." % config.CONFIG_FILE)
    wait_back("Back")


def _model_screen() -> None:
    """Settings: switch the model of the connected provider."""
    cfg = config.load()
    if cfg is None:
        clear()
        info("Enter an AI key first: the model belongs to a provider.")
        wait_back("Back")
        return
    model = _choose_model(cfg["provider"], cfg["api_key"], cfg["model"])
    if model is None:
        return
    clear()
    if config.set_model(model):
        success("Model saved: %s" % model)
    else:
        error("Could not write %s." % config.CONFIG_FILE)
    wait_back("Back")


def _model_line(model: str, note: str, current: str, selected: bool) -> str:
    """A model row: id, optional description and a mark on the current one."""
    text = model + (" — " + note if note else "")
    if model == current:
        text += "  ✓"
    return option_line(text, selected)


def _choose_model(provider: str, api_key: str, current: str = "") -> str | None:
    """Pick a model: a recommended one, any the key can use, or a typed id.

    Returns the model id, or ``None`` when the user backs out.
    """
    entries = [("item", ("model", model, note))
               for model, note in config.PROVIDERS[provider]["models"]]
    entries += [("item", ("all", "All available models…", "")),
                ("item", ("manual", "Type a model id…", ""))]
    header = [
        "  %sAI model · %s%s"
        % (Color.BOLD, config.PROVIDERS[provider]["label"], Color.RESET),
        "  %sA stronger model writes better but costs more and takes longer.%s"
        % (Color.DIM, Color.RESET),
        "",
    ]

    def render(value, selected):
        kind, model, note = value
        if kind == "model":
            return _model_line(model, note, current, selected)
        return option_line(model, selected)

    while True:
        choice = select(entries, header_lines=header, hint=NAV_HINT,
                        render_item=render, label_item=lambda value: value[1])
        if choice is None:
            return None
        kind, model, _note = choice
        if kind == "model":
            return model
        picked = (_choose_listed_model(provider, api_key, current) if kind == "all"
                  else _type_model())
        if picked:
            return picked


def _choose_listed_model(provider: str, api_key: str, current: str) -> str | None:
    """Load the provider's model list for this key and pick one."""
    try:
        with Spinner("Loading the model list"):
            models = ai.list_models(provider, api_key)
    except ai.AIError as exc:
        clear()
        error("Could not load the model list: %s" % exc)
        wait_back("Back")
        return None
    header = [
        "  %sAll models · %s%s"
        % (Color.BOLD, config.PROVIDERS[provider]["label"], Color.RESET),
        "  %sNewest first.%s\n" % (Color.DIM, Color.RESET),
    ]
    return select(
        [("item", model) for model in models],
        header_lines=header,
        hint=NAV_HINT,
        render_item=lambda model, selected: _model_line(model, "", current, selected),
        label_item=lambda model: model,
    )


def _type_model() -> str | None:
    """Ask for a model id typed by hand."""
    clear()
    print("  %sModel id%s" % (Color.BOLD, Color.RESET))
    print("  %s(empty line or q cancels)%s\n" % (Color.DIM, Color.RESET))
    try:
        model = input("  Model: ").strip()
    except (KeyboardInterrupt, EOFError):
        return None
    return None if not model or model.lower() == "q" else model


def require_ai() -> dict | None:
    """Return the AI config; if missing, send the user to AI setup first."""
    cfg = config.load()
    if cfg:
        return cfg
    clear()
    info("Connect an AI first: enter a key.")
    wait_back("Continue")
    configure_ai()
    return config.load()


def usage_screen() -> None:
    """What every run has cost so far, from the usage log."""
    runs = usage.read_log()
    price_table = usage.prices(config.load())
    clear()
    print("  %sUsage and cost%s\n" % (Color.BOLD, Color.RESET))
    if not runs:
        info("Nothing recorded yet. Totals appear after the first work is written.")
        wait_back("Back")
        return

    total = usage.summarise(runs, price_table)
    print("  %sRequests:%s %d" % (Color.DIM, Color.RESET, total["requests"]))
    print("  %sTokens:%s   %s in + %s out = %s"
          % (Color.DIM, Color.RESET, _group(total["input_tokens"]),
             _group(total["output_tokens"]), _group(total["total_tokens"])))
    if total["cost"] is None:
        print("  %sCost:%s     unknown: no price configured for these models"
              % (Color.DIM, Color.RESET))
    else:
        note = ("" if total["priced_requests"] == total["requests"]
                else "  (%d of %d requests priced)"
                % (total["priced_requests"], total["requests"]))
        print("  %sCost:%s     $%.4f%s" % (Color.DIM, Color.RESET, total["cost"], note))

    print("\n  %sLast runs%s" % (Color.BOLD, Color.RESET))
    for run in runs[-8:]:
        print("    %s%-34s%s %s" % (Color.DIM, run.label[:34], Color.RESET,
                                    usage.format_run(run, price_table)))
    print("\n  %sLog: %s%s" % (Color.DIM, usage.LOG_FILE, Color.RESET))
    print("  %sPrices per million tokens can be set in %s under \"prices\".%s"
          % (Color.DIM, config.CONFIG_FILE, Color.RESET))
    wait_back("Back")


def _group(number: int) -> str:
    return "{:,}".format(number).replace(",", " ")


def output_format_screen() -> None:
    """Toggle which output formats are produced (persisted immediately)."""
    while True:
        enabled = set(config.get_formats())
        header = [
            "  %sOutput format%s" % (Color.BOLD, Color.RESET),
            "  %sEnter toggles a format. At least one must stay on.%s"
            % (Color.DIM, Color.RESET),
            "  %s.docx needs python-docx, .pptx needs python-pptx (pip).%s"
            % (Color.DIM, Color.RESET),
            "",
        ]

        def label(code):
            return "%s %s" % ("[x]" if code in enabled else "[ ]",
                              export.FORMAT_LABELS[code])

        action = select(
            [("item", code) for code, _ in export.FORMATS],
            header_lines=header,
            hint=NAV_HINT,
            render_item=lambda code, selected: option_line(label(code), selected),
            label_item=label,
        )
        if action is None:
            return
        if action in enabled:
            enabled.discard(action)
        else:
            enabled.add(action)
        if not enabled:
            enabled = {"md"}
        config.set_formats([c for c, _ in export.FORMATS if c in enabled])


def ensure_style() -> dict:
    """Return the user's style profile, creating a stable one on first use."""
    profile = config.get_style()
    if profile:
        return style.normalise(profile)
    profile = style.random_profile()
    config.set_style(profile)  # fixed for this user until re-rolled
    return profile


def _print_profile(profile: dict, landed: bool = True) -> None:
    """Print a style profile as three labelled, coloured lines."""
    for label, text in style.describe(profile):
        color = Color.GREEN if landed else Color.PINK
        print("  %s%-10s%s %s%s%s"
              % (color + Color.BOLD, label + ":", Color.RESET,
                 Color.DIM if not landed else "", text, Color.RESET))


def _roll_style() -> dict:
    """Slot-machine animation: spin style profiles, decelerate, land on one."""
    import time

    final = style.random_profile()
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        config.set_style(final)
        return final

    frames = 20
    sys.stdout.write("\033[?25l")  # hide cursor
    try:
        for step in range(frames):
            profile = final if step == frames - 1 else style.random_profile()
            clear()
            print("\n  %sRolling a writing style…%s\n" % (Color.BOLD, Color.RESET))
            _print_profile(profile, landed=(step == frames - 1))
            sys.stdout.flush()
            time.sleep(0.05 + (step / frames) ** 2 * 0.22)  # ease-out
    finally:
        sys.stdout.write("\033[?25h")  # show cursor
        sys.stdout.flush()
    config.set_style(final)
    return final


def _style_screen() -> None:
    """Read-only style section: view the profile and optionally re-roll it."""
    while True:
        profile = ensure_style()
        header = [
            "  %sAI writing style%s" % (Color.BOLD, Color.RESET),
            "  %sLight stylistic nudges so that works by different students%s"
            % (Color.DIM, Color.RESET),
            "  %sdo not look alike. They do not affect quality and cannot be%s"
            % (Color.DIM, Color.RESET),
            "  %sedited by hand, only rolled again.%s"
            % (Color.DIM, Color.RESET),
            "",
        ]
        for label, text in style.describe(profile):
            header.append("  %s%-10s%s %s" % (Color.CYAN + Color.BOLD,
                                              label + ":", Color.RESET, text))
        header.append("")

        action = select(
            [("item", "roll")],
            header_lines=header,
            hint=NAV_HINT,
            render_item=lambda value, selected: option_line(
                "Roll a different set", selected),
            label_item=lambda value: "Roll a different set",
        )
        if action is None:
            return
        new_profile = _roll_style()
        clear()
        print("\n  %sNew writing style:%s\n" % (Color.BOLD, Color.RESET))
        _print_profile(new_profile, landed=True)
        wait_back("Back")
