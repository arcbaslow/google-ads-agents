from app.csrf import app_origin


def test_app_origin_lowercases_host(settings):
    settings.signin_redirect_uri = "https://App.Example.COM:8443/auth/google/callback"
    assert app_origin(settings) == "https://app.example.com:8443"
