#!/bin/sh
# POSIX sh on purpose: the official n8n image is Alpine-based and ships no bash.
#
# Starts n8n 2.40.x with issue-agent credentials and workflow provisioned from Git.
#
# Credentials: the three header-auth credentials are machine-owned (values come from
# Kubernetes Secrets) and are upserted by fixed id on every start.
#
# Workflow: imported only when the Git source changed AND the stored workflow still
# matches what this script last imported. A workflow edited in the UI is never
# overwritten; the conflict is logged and the edited version keeps running.
set -eu
umask 077

secrets=/run/issue-agent-n8n
source_file=/etc/issue-agent-n8n/n8n-workflow.json
workflow_id="$ISSUE_AGENT_WORKFLOW_ID"
state_dir=/home/node/.n8n/issue-agent
state_file="$state_dir/workflow-import.json"
work=/tmp/issue-agent-bootstrap
rm -rf "$work"
mkdir -p "$work" "$state_dir"
trap 'rm -rf "$work"' EXIT

node -e '
const fs = require("fs");
const read = (p) => fs.readFileSync(p, "utf8").trim();
const [dir, out] = process.argv.slice(1);
const header = (id, name, token) => ({
  id, name, type: "httpHeaderAuth",
  data: { name: "Authorization", value: `Bearer ${token}` },
});
fs.writeFileSync(out, JSON.stringify([
  header("iaBridgeOps00001", "issue-agent-bridge-ops", read(`${dir}/ops/bridge-ops-token`)),
  header("iaN8nWebhook0001", "issue-agent-n8n-webhook", read(`${dir}/ops/n8n-webhook-token`)),
  header("iaModelKey000001", "issue-agent-model-key", read(`${dir}/model/apiKey`)),
]));
' "$secrets" "$work/credentials.json"
n8n import:credentials --input="$work/credentials.json"
rm -f "$work/credentials.json"

fail() {
  echo "issue-agent: $*" >&2
  exit 1
}

# Prints "yes" or "no". Absence is only concluded from a successful full listing:
# `list:workflow` exits 0 after querying every workflow row, and exits 1 on any
# DB/CLI error. (`export:workflow` cannot be used for this: in n8n 2.40.x it raises
# the same exit-1 UserError for "no workflows" as for real failures.)
# JSON log format makes each listed id an exact `message` field.
workflow_exists() {
  if ! listing="$(N8N_LOG_FORMAT=json N8N_LOG_LEVEL=info n8n list:workflow --onlyId)"; then
    fail "n8n list:workflow failed; refusing to decide whether workflow $workflow_id exists"
  fi
  printf '%s\n' "$listing" | node -e '
const id = process.argv[1];
let found = false;
for (const line of require("fs").readFileSync(0, "utf8").split("\n")) {
  let entry;
  try { entry = JSON.parse(line); } catch { continue; }
  if (entry && entry.message === id) found = true;
}
process.stdout.write(found ? "yes" : "no");
' "$workflow_id"
}

# Prints the stored versionId of an existing workflow; any export error aborts startup.
stored_version() {
  rm -f "$work/export.json"
  if ! n8n export:workflow --id="$workflow_id" --output="$work/export.json" >&2; then
    fail "n8n export:workflow --id=$workflow_id failed for an existing workflow"
  fi
  node -e '
const [file, id] = process.argv.slice(1);
const list = JSON.parse(require("fs").readFileSync(file, "utf8"));
const matches = (Array.isArray(list) ? list : [list]).filter((w) => w && w.id === id);
if (matches.length !== 1 || typeof matches[0].versionId !== "string" || !matches[0].versionId) {
  console.error(`issue-agent: export of workflow ${id} returned ${matches.length} matching entries without a usable versionId`);
  process.exit(1);
}
process.stdout.write(matches[0].versionId);
' "$work/export.json" "$workflow_id"
}

# Prints "<field>" from the state file, or nothing.
state_field() {
  [ -s "$state_file" ] || return 0
  node -e '
const [file, key] = process.argv.slice(1);
const v = JSON.parse(require("fs").readFileSync(file, "utf8"))[key];
if (typeof v === "string") process.stdout.write(v);
' "$state_file" "$1"
}

source_sha="$(node -e '
const c = require("crypto"), fs = require("fs");
const wf = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
if (wf.id !== process.argv[2]) { console.error(`workflow id ${wf.id} != ${process.argv[2]}`); process.exit(1); }
process.stdout.write(c.createHash("sha256").update(fs.readFileSync(process.argv[1])).digest("hex"));
' "$source_file" "$workflow_id")"

exists="$(workflow_exists)"
current_version=""
if [ "$exists" = yes ]; then
  current_version="$(stored_version)"
fi
recorded_sha="$(state_field sourceSha256)"
recorded_version="$(state_field versionId)"

action=skip
if [ "$exists" = no ]; then
  action=import
elif [ "$source_sha" = "$recorded_sha" ]; then
  action=skip
elif [ -n "$recorded_version" ] && [ "$current_version" = "$recorded_version" ]; then
  action=import
else
  echo "issue-agent: CONFLICT workflow $workflow_id was changed in n8n (versionId $current_version, last imported ${recorded_version:-none}) and the Git source also changed (sha256 $source_sha). Not importing; export the edited workflow and reconcile it in Git." >&2
fi

if [ "$action" = import ]; then
  n8n import:workflow --input="$source_file"
  new_version="$(stored_version)"
  if [ "$new_version" = "$current_version" ]; then
    fail "workflow import did not produce a new version"
  fi
  # import:workflow always stores the workflow unpublished; publish the imported version.
  n8n publish:workflow --id="$workflow_id" --versionId="$new_version"
  node -e '
const [file, sha, version] = process.argv.slice(1);
require("fs").writeFileSync(`${file}.tmp`, JSON.stringify({ sourceSha256: sha, versionId: version }));
require("fs").renameSync(`${file}.tmp`, file);
' "$state_file" "$source_sha" "$new_version"
  echo "issue-agent: imported and published workflow $workflow_id version $new_version"
else
  echo "issue-agent: workflow $workflow_id left unchanged (versionId $current_version)"
fi

rm -rf "$work"
trap - EXIT

ISSUE_AGENT_MODEL_URL="$(cat "$secrets/model/baseUrl")/chat/completions"
export ISSUE_AGENT_MODEL_URL
exec n8n start
