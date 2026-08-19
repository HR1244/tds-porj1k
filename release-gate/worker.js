export default {
  async fetch(request, env, ctx) {
    if (request.method === 'POST' && new URL(request.url).pathname === '/release-gate') {
      try {
        const body = await request.json();
        const violations = [];
        
        const target = body.target || "";
        const event = body.event || "";
        const ref = body.ref || "";
        const workflow = body.workflow || {};
        const image = body.image || {};

        // 1. EXCESS_PERMISSION
        const p = workflow.permissions || {};
        const pKeys = Object.keys(p);
        if (p.contents !== 'read' || p.packages !== 'write' || p['id-token'] !== 'none' || pKeys.length !== 3) {
          violations.push("EXCESS_PERMISSION");
        }
        
        // 2. UNSAFE_PR_TRIGGER
        if (event === 'pull_request' && workflow.trigger !== 'pull_request') {
          violations.push("UNSAFE_PR_TRIGGER");
        } else if (workflow.trigger === 'pull_request_target') {
          violations.push("UNSAFE_PR_TRIGGER");
        }
        
        // 3. TESTS_INCOMPLETE
        if (workflow.testsPassed !== true || workflow.matrixComplete !== true || workflow.failFast !== false) {
          violations.push("TESTS_INCOMPLETE");
        }
        
        // 4. MUTABLE_ACTION
        const actions = workflow.actions || [];
        for (const action of actions) {
          if (action.owner !== 'actions') {
            const shaRegex = /^[0-9a-f]{40}$/;
            if (!shaRegex.test(action.ref)) {
              violations.push("MUTABLE_ACTION");
              break;
            }
          }
        }
        
        // 5. SINGLE_STAGE_IMAGE
        if (image.multiStage !== true) {
          violations.push("SINGLE_STAGE_IMAGE");
        }
        
        // 6. ROOT_RUNTIME
        if (image.runsAsRoot !== false) {
          violations.push("ROOT_RUNTIME");
        }
        
        // 7. SECRET_IN_LAYER
        if (image.secretMode !== 'none' && image.secretMode !== 'buildkit') {
          violations.push("SECRET_IN_LAYER");
        }
        
        // 8. CRITICAL_CVE
        if (image.criticalVulnerabilities !== 0) {
          violations.push("CRITICAL_CVE");
        }
        
        // 9. UNPINNED_IMAGE
        if (image.digestPinned !== true) {
          violations.push("UNPINNED_IMAGE");
        }
        
        // 10 & 11. Production requirements
        if (target === 'production') {
          if (event !== 'push' || ref !== 'refs/heads/main') {
            violations.push("INVALID_PRODUCTION_REF");
          }
          if (workflow.environmentApproval !== true) {
            violations.push("APPROVAL_REQUIRED");
          }
        }
        
        const decision = violations.length === 0 ? "promote" : "block";
        return new Response(JSON.stringify({ decision, violations }), {
          headers: { "Content-Type": "application/json" }
        });
        
      } catch (e) {
        return new Response("Bad Request", { status: 400 });
      }
    }
    
    return new Response("Not Found", { status: 404 });
  }
};
