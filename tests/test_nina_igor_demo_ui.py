"""Static integration guard for the external demo hub (no privileged API calls)."""

from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def test_demo_appears_in_existing_command_center():
    assert 'data-tab="demo"' in HTML
    assert 'id="view-demo"' in HTML
    assert 'demo:["NINA + IGOR · Demo"' in HTML
    assert 'data-go="execution"' in HTML


def test_demo_links_are_isolated_and_marked_nonproduction():
    assert "TRYB DEMO / EXTERNAL / UNVERIFIED" in HTML
    assert "DEMO i LIVE mają oddzielne granice zaufania" in HTML
    assert "27acc968-f66b-4d46-93ce-a5326a9401ec" in HTML
    assert 'target="_blank" rel="noopener noreferrer"' in HTML


def test_external_links_never_include_api_keys_or_tenant_information():
    import re

    demo = HTML.split('<section id="view-demo"', 1)[1].split('</section>', 1)[0]
    urls = re.findall(r'href="([^"]+)"', demo)
    assert urls
    assert all(url.startswith("https://") for url in urls)
    assert all(not any(x in url.lower() for x in ("api_key", "x-api-key", "token=", "tenant=", "?")) for url in urls)
    assert "fetch(" not in demo
