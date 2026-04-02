"""
Email/password authentication Streamlit component.

Renders a two-tab form (Sign In / Create Account) that calls auth_bridge
functions and updates st.session_state. No iframe or custom component
required — this is pure Streamlit.

Public API:
    render_email_auth_form(t) → None
        Renders the form. Calls st.rerun() on successful authentication.
"""
import streamlit as st

import src.components.auth_bridge as auth_bridge


def render_email_auth_form(t=None, key_suffix: str = "") -> None:
    """
    Render email/password sign-in and registration form.

    Args:
        t: optional translation callable — t(key) → str.
           Falls back to English if not provided.
    """
    def _t(key: str, default: str) -> str:
        if t is None:
            return default
        try:
            return t(key)
        except Exception:
            return default

    tab_signin, tab_register = st.tabs([
        _t("email_signin_tab", "Sign In"),
        _t("email_register_tab", "Create Account"),
    ])

    # ── Sign In tab ────────────────────────────────────────────────────────
    with tab_signin:
        with st.form(f"email_signin_form{key_suffix}", clear_on_submit=False):
            email = st.text_input(
                _t("email_label", "Email"),
                placeholder="you@example.com",
                key=f"signin_email{key_suffix}",
            )
            password = st.text_input(
                _t("password_label", "Password"),
                type="password",
                key=f"signin_password{key_suffix}",
            )
            submitted = st.form_submit_button(
                _t("signin_btn", "Sign In"),
                use_container_width=True,
                type="primary",
            )

        if submitted:
            if not email or not password:
                st.error(_t("email_fill_all", "Please fill in email and password."))
            else:
                with st.spinner(_t("signing_in", "Signing in…")):
                    ok = auth_bridge.login_email(email.strip(), password)
                if ok:
                    st.success(_t("signin_success", "Welcome! Loading your dashboard…"))
                    st.rerun()
                else:
                    st.error(_t("signin_failed", "Invalid email or password. Please try again."))

    # ── Create Account tab ─────────────────────────────────────────────────
    with tab_register:
        with st.form(f"email_register_form{key_suffix}", clear_on_submit=True):
            reg_name = st.text_input(
                _t("display_name_label", "Display Name (optional)"),
                placeholder=_t("display_name_placeholder", "Your name"),
                key=f"reg_name{key_suffix}",
            )
            reg_email = st.text_input(
                _t("email_label", "Email"),
                placeholder="you@example.com",
                key=f"reg_email{key_suffix}",
            )
            reg_pass = st.text_input(
                _t("password_label", "Password"),
                type="password",
                help=_t("password_hint", "At least 8 characters"),
                key=f"reg_pass{key_suffix}",
            )
            reg_pass2 = st.text_input(
                _t("confirm_password_label", "Confirm Password"),
                type="password",
                key=f"reg_pass2{key_suffix}",
            )
            reg_submitted = st.form_submit_button(
                _t("register_btn", "Create Account"),
                use_container_width=True,
                type="primary",
            )

        if reg_submitted:
            if not reg_email or not reg_pass:
                st.error(_t("email_fill_all", "Please fill in email and password."))
            elif reg_pass != reg_pass2:
                st.error(_t("password_mismatch", "Passwords do not match."))
            elif len(reg_pass) < 8:
                st.error(_t("password_too_short", "Password must be at least 8 characters."))
            else:
                with st.spinner(_t("creating_account", "Creating your account…")):
                    result = auth_bridge.register_email(
                        reg_email.strip(), reg_pass, reg_name.strip()
                    )
                if result["ok"]:
                    st.success(result["message"])
                    st.info(_t("check_email", "After verifying your email, come back and sign in."))
                else:
                    st.error(result["message"])
