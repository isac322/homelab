---
name: destructive-operations
description: "Apply before deleting data, overwriting unrelated work, or running destructive operations."
---

# Destructive operations

Before an irreversible operation:

1. Identify the exact data or state that will change.
2. Prefer a reversible alternative when it satisfies the request.
3. Capture a rollback path or backup when practical.
4. State the irreversible consequence before execution.
