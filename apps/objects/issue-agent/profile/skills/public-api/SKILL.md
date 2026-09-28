---
name: public-api
description: "Apply before changing a public or exported API."
---

# Public API changes

Before changing a public API:

1. Find every caller.
2. Migrate every caller in the same change.
3. Remove obsolete aliases and compatibility paths.
4. Verify the changed observable contract.
