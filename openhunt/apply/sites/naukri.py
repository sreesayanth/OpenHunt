from openhunt.apply.sites.base import Site


class Naukri(Site):
    name = "naukri"
    label = "Naukri"
    base = "https://www.naukri.com"
    login_path = "/nlogin/login"
    home_path = "/mnjuser/homepage"
    # Logged in = Naukri lets us stay on the "My Naukri" pages instead of sending us to the login page.
    logged_in_url = r"/mnjuser/"

    user_fields = ("#usernameField", "input[placeholder*=Email i]", *Site.user_fields)
    password_fields = ("#passwordField", *Site.password_fields)
    submit_buttons = ("button[type=submit].loginButton", *Site.submit_buttons)
    error_fields = (".server-err:visible", ".erLbl:visible", ".error:visible")
    error_text = Site.error_text + r"|invalid details"
