from app.main import app


def test_nina_run_route_exists():
    routes = {route.path for route in app.routes}
    assert "/nina-run" in routes
