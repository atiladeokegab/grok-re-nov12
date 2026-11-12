def test_analyst_page_and_its_assets_are_available(client):
    response = client.get("/analyst")
    assert response.status_code == 200
    assert 'id="analyst-title"' in response.text
    for name in ("analyst.js", "analyst.css"):
        assert client.get(f"/static/{name}").status_code == 200
