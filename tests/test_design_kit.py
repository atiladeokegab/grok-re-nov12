def test_runs_page_uses_the_kit_and_the_theme_attribute_switches(client, auth):
    client.post("/api/runs", json={"id": "web-1", "body": "Hello"}, headers=auth)
    page = client.get("/").text
    assert '<link rel="stylesheet" href="/static/tokens.css">' in page
    assert '<html lang="en" data-theme="neutral">' in page
    for component in ('class="button', 'class="input"', 'class="table"'):
        assert component in page
    assert '<html lang="en" data-theme="refinery">' in client.get("/?theme=refinery").text
    assert "<script>x" not in client.get('/?theme="><script>x').text  # escaped, not injected


def test_tokens_hold_a_refinery_theme_and_the_three_components(client):
    css = client.get("/static/tokens.css").text
    refinery = css.split(':root[data-theme="refinery"] {')[1].split("}")[0]
    for value in ("#00D46A", "#F4F4F5", "#27272A", "#09090B", '"Work Sans"', "Inter"):
        assert value in refinery
    for component in (".button {", ".input {", ".table {"):
        assert component in css
