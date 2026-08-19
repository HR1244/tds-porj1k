from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import re
import uvicorn
import os

app = FastAPI()

@app.post("/release-gate")
async def release_gate(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON"})

    violations = []
    
    # Extract fields with defaults
    target = body.get("target", "")
    event = body.get("event", "")
    ref = body.get("ref", "")
    
    workflow = body.get("workflow", {})
    trigger = workflow.get("trigger", "")
    permissions = workflow.get("permissions", {})
    tests_passed = workflow.get("testsPassed")
    matrix_complete = workflow.get("matrixComplete")
    fail_fast = workflow.get("failFast")
    actions = workflow.get("actions", [])
    env_approval = workflow.get("environmentApproval")
    
    image = body.get("image", {})
    multi_stage = image.get("multiStage")
    runs_as_root = image.get("runsAsRoot")
    secret_mode = image.get("secretMode", "")
    critical_cves = image.get("criticalVulnerabilities")
    digest_pinned = image.get("digestPinned")
    
    # 1. EXCESS_PERMISSION
    # Exactly least privilege: contents: read, packages: write, id-token: none
    if permissions.get("contents") != "read" or permissions.get("packages") != "write" or permissions.get("id-token") != "none" or len(permissions) != 3:
        violations.append("EXCESS_PERMISSION")
        
    # 2. UNSAFE_PR_TRIGGER
    # A pull request must use pull_request, never pull_request_target
    if event == "pull_request" and trigger != "pull_request":
        violations.append("UNSAFE_PR_TRIGGER")
    elif trigger == "pull_request_target":
        violations.append("UNSAFE_PR_TRIGGER")
        
    # 3. TESTS_INCOMPLETE
    # testsPassed must be true, matrixComplete must be true, failFast must be false
    if tests_passed is not True or matrix_complete is not True or fail_fast is not False:
        violations.append("TESTS_INCOMPLETE")
        
    # 4. MUTABLE_ACTION
    # Actions owned by "actions" may use a version tag.
    # Third-party actions must be pinned to full 40-character lowercase hex SHA.
    sha_regex = re.compile(r"^[0-9a-f]{40}$")
    for action in actions:
        owner = action.get("owner", "")
        action_ref = action.get("ref", "")
        if owner != "actions":
            if not sha_regex.match(action_ref):
                violations.append("MUTABLE_ACTION")
                break
                
    # 5. SINGLE_STAGE_IMAGE
    if multi_stage is not True:
        violations.append("SINGLE_STAGE_IMAGE")
        
    # 6. ROOT_RUNTIME
    if runs_as_root is not False:
        violations.append("ROOT_RUNTIME")
        
    # 7. SECRET_IN_LAYER
    # secretMode must be "none" or "buildkit"
    if secret_mode not in ["none", "buildkit"]:
        violations.append("SECRET_IN_LAYER")
        
    # 8. CRITICAL_CVE
    if critical_cves != 0:
        violations.append("CRITICAL_CVE")
        
    # 9. UNPINNED_IMAGE
    if digest_pinned is not True:
        violations.append("UNPINNED_IMAGE")
        
    # 10 & 11. Production requirements
    if target == "production":
        # INVALID_PRODUCTION_REF
        if event != "push" or ref != "refs/heads/main":
            violations.append("INVALID_PRODUCTION_REF")
        # APPROVAL_REQUIRED
        if env_approval is not True:
            violations.append("APPROVAL_REQUIRED")
            
    decision = "promote" if len(violations) == 0 else "block"
    return {"decision": decision, "violations": violations}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
