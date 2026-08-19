import json

def test_endpoint():
    from main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    payload = {
      "target": "preview",
      "event": "pull_request",
      "ref": "refs/heads/feature",
      "workflow": {
        "trigger": "pull_request",
        "permissions": {"contents":"read", "packages":"write", "id-token":"none"},
        "testsPassed": True, "matrixComplete": True, "failFast": False,
        "actions": [{"owner":"actions", "name":"checkout", "ref":"v4"}]
      },
      "image": {
        "multiStage": True, "runsAsRoot": False, "secretMode": "none",
        "criticalVulnerabilities": 0, "digestPinned": True
      }
    }

    response = client.post("/release-gate", json=payload)
    print("Test 1 (Safe Preview):", response.json())
    assert response.json() == {"decision": "promote", "violations": []}

    payload2 = {
      "target": "production",
      "event": "push",
      "ref": "refs/heads/main",
      "workflow": {
        "trigger": "push",
        "permissions": {"contents":"read", "packages":"write", "id-token":"none"},
        "testsPassed": True, "matrixComplete": True, "failFast": False,
        "actions": [{"owner":"actions", "name":"checkout", "ref":"v4"}],
        "environmentApproval": True
      },
      "image": {
        "multiStage": True, "runsAsRoot": False, "secretMode": "buildkit",
        "criticalVulnerabilities": 0, "digestPinned": True
      }
    }

    response2 = client.post("/release-gate", json=payload2)
    print("Test 2 (Safe Production):", response2.json())
    assert response2.json() == {"decision": "promote", "violations": []}
    
    payload3 = payload2.copy()
    payload3["image"]["runsAsRoot"] = True
    response3 = client.post("/release-gate", json=payload3)
    print("Test 3 (Root Runtime):", response3.json())
    assert "ROOT_RUNTIME" in response3.json()["violations"]
    
test_endpoint()
