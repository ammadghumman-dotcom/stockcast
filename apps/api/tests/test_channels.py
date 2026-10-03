from fastapi.testclient import TestClient


def test_channel_crud_and_scoping(client: TestClient, headers: dict, other_headers: dict) -> None:
    r = client.post("/channels", json={"name": "Sheet uploads", "type": "csv"}, headers=headers)
    assert r.status_code == 201, r.text
    ch = r.json()
    assert ch["is_connected"] is False and ch["last_synced_at"] is None
    assert client.get(f"/channels/{ch['id']}", headers=other_headers).status_code == 404
    assert client.get("/channels", headers=other_headers).json() == []
    r = client.patch(f"/channels/{ch['id']}", json={"name": "Renamed"}, headers=headers)
    assert r.json()["name"] == "Renamed"


def test_shopify_channel_must_use_install_flow(client: TestClient, headers: dict) -> None:
    r = client.post("/channels", json={"name": "x", "type": "shopify"}, headers=headers)
    assert r.status_code == 422


def test_sync_requires_connected_non_csv_channel(client: TestClient, headers: dict) -> None:
    ch = client.post("/channels", json={"name": "csv", "type": "csv"}, headers=headers).json()
    assert client.post(f"/channels/{ch['id']}/sync", headers=headers).status_code == 422


def test_sync_run_recorded_and_failure_captured(client, db, headers, shopify_channel, monkeypatch):
    # connector raises ConnectorError -> run is 'failed' with the error, HTTP still 202
    from app.ingest.base import ConnectorError

    def boom(self):
        raise ConnectorError("Shopify 503")

    monkeypatch.setattr("app.ingest.shopify.connector.ShopifyConnector.fetch_products", boom)
    r = client.post(f"/channels/{shopify_channel.id}/sync", headers=headers)
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "failed" and "503" in run["error"] and run["trigger"] == "manual"
    runs = client.get(f"/channels/{shopify_channel.id}/sync-runs", headers=headers).json()
    assert len(runs) == 1 and runs[0]["id"] == run["id"]
