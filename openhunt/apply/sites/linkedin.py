from openhunt.apply.sites.base import Site


class LinkedIn(Site):
    name = "linkedin"
    label = "LinkedIn"
    base = "https://www.linkedin.com"
    login_path = "/login"
    home_path = "/feed/"
    session_cookies = ("li_at",)
    logged_in_url = r"/feed|/jobs|/in/|/mynetwork|/messaging"
    warn_rules = True

    user_fields = ("#username", "input[name=session_key]", *Site.user_fields)
    password_fields = ("#password", "input[name=session_password]", *Site.password_fields)
    submit_buttons = ("button[type=submit][aria-label*=Sign i]", "button[data-litms-control-urn*=submit]", *Site.submit_buttons)
    code_fields = ("#input__email_verification_pin", "#input__phone_verification_pin", "input[name=pin]", *Site.code_fields)
    code_submit = ("#email-pin-submit-button", "#two-step-submit-button", "button#pin-submit-button", *Site.code_submit)
    error_fields = ("#error-for-password:visible", "#error-for-username:visible", ".form__label--error:visible")
