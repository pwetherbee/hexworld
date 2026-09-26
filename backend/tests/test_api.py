import time

from fastapi.testclient import TestClient

from hexworld.agents.fake import FakeClient
from hexworld.api import create_app


def test_api_end_to_end_with_stream(make_runtime):
    rt = make_runtime(llm=FakeClient(latency_s=0.01, reject_rate=0))
    with TestClient(create_app(rt)) as client:
        assert client.get("/api/health").json()["ok"]
        world = client.post("/api/worlds", json={"name": "t", "radius": 6}).json()
        wid = world["id"]

        bad = client.post(f"/api/worlds/{wid}/runs", json={"q": 50, "r": 0, "prompt": "x"})
        assert bad.status_code == 400

        run = client.post(
            f"/api/worlds/{wid}/runs", json={"q": 0, "r": 0, "prompt": "a forest", "options": {"radius": 1}}
        ).json()
        conflict = client.post(f"/api/worlds/{wid}/runs", json={"q": 3, "r": 0, "prompt": "again"})
        assert conflict.status_code == 409

        seen = []
        with client.websocket_connect(f"/api/worlds/{wid}/stream?after=0") as ws:
            deadline = time.time() + 20
            while time.time() < deadline:
                ev = ws.receive_json()
                seen.append(ev["type"])
                if ev["type"] in ("run.completed", "run.failed"):
                    break
        assert "run.completed" in seen and "tile.accepted" in seen and seen[0] == "world.created"

        detail = client.get(f"/api/worlds/{wid}").json()
        accepted = [t for t in detail["tiles"] if t["status"] == "accepted"]
        assert accepted and detail["active_run_id"] is None
        asset = client.get(f"/api/assets/{accepted[0]['asset_id']}.png")
        assert asset.status_code == 200 and asset.headers["content-type"] == "image/png"

        t = accepted[0]
        td = client.get(f"/api/worlds/{wid}/tiles/{t['q']}/{t['r']}").json()
        assert td["attempts"] and td["attempts"][-1]["outcome"] == "accepted"

        evs = client.get(f"/api/runs/{run['id']}/events").json()
        assert evs[-1]["type"] == "run.completed"
        assert client.get("/api/schema").json()["title"] == "ApiSchemas"

        # deleting a world removes it with its tiles, runs and events
        assert client.delete(f"/api/worlds/{wid}").json() == {"deleted": True}
        assert client.get(f"/api/worlds/{wid}").status_code == 404
        assert wid not in [w["id"] for w in client.get("/api/worlds").json()]
        assert not rt.store.list_tiles(wid) and not rt.store.list_runs(wid)
        assert client.get(f"/api/runs/{run['id']}/events").json() == []
        assert client.delete(f"/api/worlds/{wid}").status_code == 404
