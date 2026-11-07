"""Sign-in flow: credentials, session reuse and the optional AI set-up."""
from __future__ import annotations

from .. import api, config
from ..session import Session
from ..ui import Color, Spinner, clear, error, secret_input, warn
from .settings import configure_ai


def login(allow_cancel: bool = False, notice: str = "") -> Session | None:
    """Prompt for credentials and return a Session.

    On the initial login (``allow_cancel=False``) the screen cannot be left by
    pressing Enter — an empty field just re-prompts; only mechanically ending
    the program (Ctrl+C / Ctrl+D) stops it. When switching accounts
    (``allow_cancel=True``) an empty line or ``q`` cancels back to the menu.
    ``notice`` is shown above the form (e.g. why a new login is needed).
    """
    clear()
    print("  %snewlxp.ru%s %s· sign in%s"
          % (Color.BOLD, Color.RESET, Color.DIM, Color.RESET))
    if notice:
        print()
        warn(notice)
    if allow_cancel:
        print("  %s(empty line or q cancels)%s" % (Color.DIM, Color.RESET))
    print()
    while True:
        try:
            email = input("  Email     ").strip()
            if not email or email.lower() == "q":
                if allow_cancel:
                    return None
                continue  # initial login: stay on screen
            password = secret_input("  Password  ").strip()
            if not password or password.lower() == "q":
                if allow_cancel:
                    return None
                continue
        except (KeyboardInterrupt, EOFError):
            return None  # mechanical exit / cancel only
        try:
            with Spinner("Signing in"):
                tokens = api.sign_in(email, password)
                profile = api.get_me(tokens["accessToken"])
            session = Session(tokens["accessToken"], tokens.get("refreshToken"), profile)
            session.save()
            if config.load() is None:
                _offer_ai_setup()
            return session
        except api.AuthError:
            error("Wrong email or password, try again.\n")
        except api.ApiError as exc:
            error("Connection failed: %s. Try again.\n" % exc)


def _offer_ai_setup() -> None:
    """Right after login, optionally set up the AI token (skippable)."""
    clear()
    print("  %sAI access (optional)%s" % (Color.BOLD, Color.RESET))
    print("  %sYou can add a ChatGPT or Claude key to have works written for%s"
          % (Color.DIM, Color.RESET))
    print("  %scheckpoints. You can also do this later from the menu.%s\n"
          % (Color.DIM, Color.RESET))
    try:
        answer = input("  Set up the AI now? (y for yes, Enter to skip): ").strip()
    except (KeyboardInterrupt, EOFError):
        return
    if answer.lower() in ("y", "yes"):
        configure_ai(None)


def restore_or_login() -> Session | None:
    """Reuse a saved session when possible, otherwise log in.

    Returns ``None`` if there is no session and the user cancels login.
    """
    session = Session.load()
    if session is None:
        return login()
    try:
        with Spinner("Checking the session"):
            token = session.valid_token()
            session.user = api.get_me(token)  # validates the token
        session.save()
        return session
    except api.AuthError:
        Session.forget()
        return login(notice="Session expired, sign in again.")
    except api.ApiError as exc:
        # Network trouble: keep the saved session for the next run.
        return login(notice="Could not verify the session (%s)." % exc)
