import re


def test_home_serves_the_listing_form_and_its_local_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="xray-form"' in page.text
    assets = set(re.findall(r'(?:href|src)="(/static/[^\"]+)"', page.text))
    assert assets
    for path in assets:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content, path


def test_run_inspection_remains_available_beside_the_listing_page(client, auth):
    client.post("/api/runs", json={"id": "web-1", "body": "Hello"}, headers=auth)
    page = client.get("/runs")
    assert page.status_code == 200
    assert "web-1" in page.text
