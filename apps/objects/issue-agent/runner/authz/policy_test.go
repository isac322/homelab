package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type fixture struct {
	policy    *Policy
	checkouts string
	scratch   string
	sockDir   string
}

func newFixture(t *testing.T) fixture {
	t.Helper()
	base, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	f := fixture{
		checkouts: filepath.Join(base, "home/agent/checkouts"),
		scratch:   filepath.Join(base, "tmp/issue-agent"),
		sockDir:   filepath.Join(base, "run/issue-agent-docker"),
	}
	for _, d := range []string{f.checkouts + "/repo", f.scratch + "/wt", f.sockDir, base + "/etc"} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	for link, target := range map[string]string{
		f.checkouts + "/repo/escape":   "/",
		f.checkouts + "/repo/etc-link": base + "/etc",
		f.checkouts + "/repo/sock":     f.sockDir,
		f.checkouts + "/repo/inner":    f.checkouts + "/repo",
		f.scratch + "/wt/to-checkouts": f.checkouts + "/repo",
	} {
		if err := os.Symlink(target, link); err != nil {
			t.Fatal(err)
		}
	}
	def := DefaultPolicy()
	f.policy = &Policy{
		BindRoots:      []string{f.checkouts, f.scratch},
		SocketDir:      f.sockDir,
		AllowedDevices: def.AllowedDevices,
		Resolve:        resolveHostPath,
	}
	return f
}

func jsonReq(method, uri, body string) AuthZRequest {
	r := AuthZRequest{RequestMethod: method, RequestURI: uri}
	if body != "" {
		r.RequestBody = []byte(body)
		r.RequestHeaders = map[string]string{"Content-Type": "application/json"}
	}
	return r
}

func create(hostConfig string) string {
	return `{"Image":"busybox","Cmd":["true"],"HostConfig":` + hostConfig + `}`
}

func TestDefaultPolicy(t *testing.T) {
	p := DefaultPolicy()
	if strings.Join(p.BindRoots, ",") != "/home/agent/checkouts,/tmp/issue-agent" {
		t.Errorf("BindRoots = %v", p.BindRoots)
	}
	if p.SocketDir != "/run/issue-agent-docker" {
		t.Errorf("SocketDir = %q", p.SocketDir)
	}
	if len(p.AllowedDevices) != 3 || !p.AllowedDevices["/dev/dri"] || !p.AllowedDevices["/dev/dri/card0"] || !p.AllowedDevices["/dev/dri/renderD128"] {
		t.Errorf("AllowedDevices = %v", p.AllowedDevices)
	}
}

func TestPolicy(t *testing.T) {
	f := newFixture(t)
	co, sc, sock := f.checkouts, f.scratch, f.sockDir
	bind := func(src string) string { return create(`{"Binds":["` + src + `:/src:ro"]}`) }
	mount := func(typ, src string) string {
		return create(`{"Mounts":[{"Type":"` + typ + `","Source":"` + src + `","Target":"/m"}]}`)
	}
	formReq := jsonReq("POST", "/v1.51/build?networkmode=default", "")
	formReq.RequestHeaders = map[string]string{"content-type": "application/x-www-form-urlencoded"}
	textReq := jsonReq("POST", "/v1.51/containers/create", "")
	textReq.RequestHeaders = map[string]string{"Content-Type": "text/plain"}

	cases := []struct {
		name  string
		req   AuthZRequest
		allow bool
	}{
		// Read-only endpoints.
		{"ping", jsonReq("HEAD", "/_ping", ""), true},
		{"info", jsonReq("GET", "/v1.51/info", ""), true},
		{"containers list", jsonReq("GET", "/v1.51/containers/json?all=1", ""), true},
		{"logs", jsonReq("GET", "/v1.51/containers/abc/logs?stdout=1", ""), true},
		{"plugins list", jsonReq("GET", "/v1.51/plugins", ""), true},
		{"swarm inspect", jsonReq("GET", "/v1.51/swarm", ""), false},
		{"swarm init", jsonReq("POST", "/v1.51/swarm/init", `{}`), false},
		{"services create", jsonReq("POST", "/v1.51/services/create", `{}`), false},
		{"secrets create", jsonReq("POST", "/secrets/create", `{}`), false},
		{"configs create", jsonReq("POST", "/configs/create", `{}`), false},
		{"nodes update", jsonReq("POST", "/nodes/x/update", `{}`), false},

		// Container create: baseline.
		{"create minimal", jsonReq("POST", "/v1.51/containers/create?name=x", `{"Image":"busybox"}`), true},
		{"create null hostconfig", jsonReq("POST", "/containers/create", `{"Image":"busybox","HostConfig":null}`), true},
		{"create empty body", jsonReq("POST", "/v1.51/containers/create", ""), false},
		{"create non-JSON content type", textReq, false},
		{"create invalid JSON", jsonReq("POST", "/v1.51/containers/create", `{"HostConfig":`), false},
		{"create trailing content", jsonReq("POST", "/v1.51/containers/create", `{"Image":"x"} {"HostConfig":{"Privileged":true}}`), false},
		{"create wrong field type", jsonReq("POST", "/v1.51/containers/create", create(`{"Privileged":"true"}`)), false},

		// Privilege and namespaces.
		{"privileged", jsonReq("POST", "/v1.51/containers/create", create(`{"Privileged":true}`)), false},
		{"privileged lower-case keys", jsonReq("POST", "/v1.51/containers/create", `{"hostconfig":{"privileged":true}}`), false},
		{"privileged duplicate key last wins", jsonReq("POST", "/v1.51/containers/create", `{"HostConfig":{"Privileged":false,"Privileged":true}}`), false},
		{"privileged false", jsonReq("POST", "/v1.51/containers/create", create(`{"Privileged":false}`)), true},
		{"cap add", jsonReq("POST", "/v1.51/containers/create", create(`{"CapAdd":["SYS_ADMIN"]}`)), false},
		{"cap drop", jsonReq("POST", "/v1.51/containers/create", create(`{"CapDrop":["ALL"]}`)), true},
		{"network host", jsonReq("POST", "/v1.51/containers/create", create(`{"NetworkMode":"host"}`)), false},
		{"network container", jsonReq("POST", "/v1.51/containers/create", create(`{"NetworkMode":"container:abc"}`)), false},
		{"network none", jsonReq("POST", "/v1.51/containers/create", create(`{"NetworkMode":"none"}`)), true},
		{"network bridge", jsonReq("POST", "/v1.51/containers/create", create(`{"NetworkMode":"bridge"}`)), true},
		{"endpoint host", jsonReq("POST", "/v1.51/containers/create", `{"NetworkingConfig":{"EndpointsConfig":{"host":{}}}}`), false},
		{"endpoint custom", jsonReq("POST", "/v1.51/containers/create", `{"NetworkingConfig":{"EndpointsConfig":{"e2e":{}}}}`), true},
		{"pid host", jsonReq("POST", "/v1.51/containers/create", create(`{"PidMode":"host"}`)), false},
		{"ipc host", jsonReq("POST", "/v1.51/containers/create", create(`{"IpcMode":"host"}`)), false},
		{"ipc private", jsonReq("POST", "/v1.51/containers/create", create(`{"IpcMode":"private"}`)), true},
		{"uts host", jsonReq("POST", "/v1.51/containers/create", create(`{"UTSMode":"host"}`)), false},
		{"userns host", jsonReq("POST", "/v1.51/containers/create", create(`{"UsernsMode":"host"}`)), false},
		{"cgroupns host", jsonReq("POST", "/v1.51/containers/create", create(`{"CgroupnsMode":"host"}`)), false},
		{"cgroup parent", jsonReq("POST", "/v1.51/containers/create", create(`{"CgroupParent":"/"}`)), false},
		{"sysctls", jsonReq("POST", "/v1.51/containers/create", create(`{"Sysctls":{"net.ipv4.ip_forward":"1"}}`)), false},
		{"runtime runsc", jsonReq("POST", "/v1.51/containers/create", create(`{"Runtime":"runsc"}`)), false},
		{"runtime runc", jsonReq("POST", "/v1.51/containers/create", create(`{"Runtime":"runc"}`)), true},
		{"masked paths cleared", jsonReq("POST", "/v1.51/containers/create", create(`{"MaskedPaths":[]}`)), false},
		{"readonly paths cleared", jsonReq("POST", "/v1.51/containers/create", create(`{"ReadonlyPaths":[]}`)), false},
		{"masked paths null", jsonReq("POST", "/v1.51/containers/create", create(`{"MaskedPaths":null,"ReadonlyPaths":null}`)), true},

		// Security options.
		{"seccomp unconfined", jsonReq("POST", "/v1.51/containers/create", create(`{"SecurityOpt":["seccomp=unconfined"]}`)), false},
		{"seccomp custom profile", jsonReq("POST", "/v1.51/containers/create", create(`{"SecurityOpt":["seccomp={\"defaultAction\":\"SCMP_ACT_ALLOW\"}"]}`)), false},
		{"apparmor unconfined", jsonReq("POST", "/v1.51/containers/create", create(`{"SecurityOpt":["apparmor=unconfined"]}`)), false},
		{"label disable", jsonReq("POST", "/v1.51/containers/create", create(`{"SecurityOpt":["label=disable"]}`)), false},
		{"label colon disable", jsonReq("POST", "/v1.51/containers/create", create(`{"SecurityOpt":["label:disable"]}`)), false},
		{"systempaths unconfined", jsonReq("POST", "/v1.51/containers/create", create(`{"SecurityOpt":["systempaths=unconfined"]}`)), false},
		{"no-new-privileges false", jsonReq("POST", "/v1.51/containers/create", create(`{"SecurityOpt":["no-new-privileges=false"]}`)), false},
		{"no-new-privileges", jsonReq("POST", "/v1.51/containers/create", create(`{"SecurityOpt":["no-new-privileges"]}`)), true},

		// Devices.
		{"device dri dir", jsonReq("POST", "/v1.51/containers/create", create(`{"Devices":[{"PathOnHost":"/dev/dri","PathInContainer":"/dev/dri","CgroupPermissions":"rwm"}]}`)), true},
		{"device card0", jsonReq("POST", "/v1.51/containers/create", create(`{"Devices":[{"PathOnHost":"/dev/dri/card0","PathInContainer":"/dev/dri/card0","CgroupPermissions":"rwm"}]}`)), true},
		{"device renderD128", jsonReq("POST", "/v1.51/containers/create", create(`{"Devices":[{"PathOnHost":"/dev/dri/renderD128","PathInContainer":"/dev/dri/renderD128","CgroupPermissions":"rwm"}]}`)), true},
		{"device card1", jsonReq("POST", "/v1.51/containers/create", create(`{"Devices":[{"PathOnHost":"/dev/dri/card1","PathInContainer":"/dev/dri/card1"}]}`)), false},
		{"device sda", jsonReq("POST", "/v1.51/containers/create", create(`{"Devices":[{"PathOnHost":"/dev/sda","PathInContainer":"/dev/sda"}]}`)), false},
		{"device dri traversal", jsonReq("POST", "/v1.51/containers/create", create(`{"Devices":[{"PathOnHost":"/dev/dri/../mem","PathInContainer":"/dev/mem"}]}`)), false},
		{"device mixed", jsonReq("POST", "/v1.51/containers/create", create(`{"Devices":[{"PathOnHost":"/dev/dri"},{"PathOnHost":"/dev/kmsg"}]}`)), false},
		{"device cgroup rules", jsonReq("POST", "/v1.51/containers/create", create(`{"DeviceCgroupRules":["b *:* rwm"]}`)), false},
		{"device requests", jsonReq("POST", "/v1.51/containers/create", create(`{"DeviceRequests":[{"Driver":"nvidia","Count":-1}]}`)), false},

		// Binds and mounts.
		{"bind checkout", jsonReq("POST", "/v1.51/containers/create", bind(co+"/repo")), true},
		{"bind missing under checkout", jsonReq("POST", "/v1.51/containers/create", bind(co+"/repo/not-yet/created")), true},
		{"bind scratch", jsonReq("POST", "/v1.51/containers/create", bind(sc+"/wt")), true},
		{"bind scratch link into checkouts", jsonReq("POST", "/v1.51/containers/create", bind(sc+"/wt/to-checkouts")), true},
		{"bind inner link", jsonReq("POST", "/v1.51/containers/create", bind(co+"/repo/inner")), true},
		{"bind root", jsonReq("POST", "/v1.51/containers/create", bind("/")), false},
		{"bind etc", jsonReq("POST", "/v1.51/containers/create", bind("/etc")), false},
		{"bind checkouts root itself", jsonReq("POST", "/v1.51/containers/create", bind(co)), false},
		{"bind scratch root itself", jsonReq("POST", "/v1.51/containers/create", bind(sc)), false},
		{"bind dotdot escape", jsonReq("POST", "/v1.51/containers/create", bind(co+"/../../../etc")), false},
		{"bind symlink to root", jsonReq("POST", "/v1.51/containers/create", bind(co+"/repo/escape")), false},
		{"bind symlink to outside dir", jsonReq("POST", "/v1.51/containers/create", bind(co+"/repo/etc-link/sub")), false},
		{"bind symlink to socket dir", jsonReq("POST", "/v1.51/containers/create", bind(co+"/repo/sock")), false},
		{"bind socket dir", jsonReq("POST", "/v1.51/containers/create", bind(sock)), false},
		{"bind socket file", jsonReq("POST", "/v1.51/containers/create", bind(sock+"/docker.sock")), false},
		{"bind prefix sibling", jsonReq("POST", "/v1.51/containers/create", bind(co+"-other/x")), false},
		{"bind empty source", jsonReq("POST", "/v1.51/containers/create", create(`{"Binds":[":/x"]}`)), false},
		{"named volume bind", jsonReq("POST", "/v1.51/containers/create", create(`{"Binds":["cache:/cache"]}`)), true},
		{"anonymous volume", jsonReq("POST", "/v1.51/containers/create", create(`{"Binds":["/data"]}`)), true},
		{"mount bind checkout", jsonReq("POST", "/v1.51/containers/create", mount("bind", co+"/repo")), true},
		{"mount bind root", jsonReq("POST", "/v1.51/containers/create", mount("bind", "/")), false},
		{"mount bind relative", jsonReq("POST", "/v1.51/containers/create", mount("bind", "repo")), false},
		{"mount bind socket", jsonReq("POST", "/v1.51/containers/create", mount("bind", sock+"/docker.sock")), false},
		{"mount volume", jsonReq("POST", "/v1.51/containers/create", mount("volume", "cache")), true},
		{"mount volume driver config", jsonReq("POST", "/v1.51/containers/create", create(`{"Mounts":[{"Type":"volume","Source":"v","Target":"/m","VolumeOptions":{"DriverConfig":{"Name":"local","Options":{"type":"none","o":"bind","device":"/"}}}}]}`)), false},
		{"mount volume no driver config", jsonReq("POST", "/v1.51/containers/create", create(`{"Mounts":[{"Type":"volume","Source":"v","Target":"/m","VolumeOptions":{"NoCopy":true}}]}`)), true},
		{"mount tmpfs", jsonReq("POST", "/v1.51/containers/create", mount("tmpfs", "")), true},
		{"mount npipe", jsonReq("POST", "/v1.51/containers/create", mount("npipe", "x")), false},
		{"mount cluster", jsonReq("POST", "/v1.51/containers/create", mount("cluster", "x")), false},
		{"mount unknown type", jsonReq("POST", "/v1.51/containers/create", mount("", "/")), false},
		{"volume driver", jsonReq("POST", "/v1.51/containers/create", create(`{"VolumeDriver":"local-persist"}`)), false},
		{"volumes from", jsonReq("POST", "/v1.51/containers/create", create(`{"VolumesFrom":["other"]}`)), false},

		// Container lifecycle.
		{"start", jsonReq("POST", "/v1.51/containers/abc/start", ""), true},
		{"start empty object", jsonReq("POST", "/v1.51/containers/abc/start", `{}`), true},
		{"start with host config", jsonReq("POST", "/v1.51/containers/abc/start", `{"Privileged":true}`), false},
		{"stop", jsonReq("POST", "/v1.51/containers/abc/stop", ""), true},
		{"kill", jsonReq("POST", "/v1.51/containers/abc/kill?signal=KILL", ""), true},
		{"wait", jsonReq("POST", "/v1.51/containers/abc/wait?condition=next-exit", ""), true},
		{"attach", jsonReq("POST", "/v1.51/containers/abc/attach?stream=1&stdout=1", ""), true},
		{"resize", jsonReq("POST", "/v1.51/containers/abc/resize?h=10&w=10", ""), true},
		{"remove", jsonReq("DELETE", "/v1.51/containers/abc?force=1", ""), true},
		{"remove container named prune", jsonReq("DELETE", "/v1.51/containers/prune", ""), true},
		{"start container named create", jsonReq("POST", "/v1.51/containers/create/start", ""), true},
		{"archive put", jsonReq("PUT", "/v1.51/containers/abc/archive?path=/", ""), true},
		{"container prune", jsonReq("POST", "/v1.51/containers/prune", ""), true},
		{"update", jsonReq("POST", "/v1.51/containers/abc/update", `{"Memory":0}`), false},
		{"checkpoint create", jsonReq("POST", "/v1.51/containers/abc/checkpoints", `{}`), false},

		// Exec.
		{"exec", jsonReq("POST", "/v1.51/containers/abc/exec", `{"Cmd":["sh"]}`), true},
		{"exec privileged", jsonReq("POST", "/v1.51/containers/abc/exec", `{"Cmd":["sh"],"Privileged":true}`), false},
		{"exec privileged lower-case", jsonReq("POST", "/v1.51/containers/abc/exec", `{"privileged":true}`), false},
		{"exec empty body", jsonReq("POST", "/v1.51/containers/abc/exec", ""), false},
		{"exec start", jsonReq("POST", "/v1.51/exec/def/start", `{"Detach":false}`), true},
		{"exec resize", jsonReq("POST", "/v1.51/exec/def/resize?h=1&w=1", ""), true},

		// Plugins.
		{"plugin pull", jsonReq("POST", "/v1.51/plugins/pull?remote=x", `[]`), false},
		{"plugin install via create", jsonReq("POST", "/v1.51/plugins/create?name=x", ""), false},
		{"plugin enable", jsonReq("POST", "/v1.51/plugins/issue-agent-authz/enable", ""), false},
		{"plugin disable", jsonReq("POST", "/v1.51/plugins/x/disable", ""), false},
		{"plugin set", jsonReq("POST", "/v1.51/plugins/x/set", `[]`), false},
		{"plugin upgrade", jsonReq("POST", "/v1.51/plugins/x/upgrade?remote=y", `[]`), false},
		{"plugin push", jsonReq("POST", "/v1.51/plugins/x/push", ""), false},
		{"plugin remove", jsonReq("DELETE", "/v1.51/plugins/x", ""), false},

		// Volumes.
		{"volume create default", jsonReq("POST", "/v1.51/volumes/create", `{"Name":"cache"}`), true},
		{"volume create local", jsonReq("POST", "/v1.51/volumes/create", `{"Name":"cache","Driver":"local","DriverOpts":{}}`), true},
		{"volume create bind opts", jsonReq("POST", "/v1.51/volumes/create", `{"Driver":"local","DriverOpts":{"type":"none","o":"bind","device":"/"}}`), false},
		{"volume create device opt", jsonReq("POST", "/v1.51/volumes/create", `{"DriverOpts":{"device":"/dev/sda1","type":"ext4"}}`), false},
		{"volume create nfs", jsonReq("POST", "/v1.51/volumes/create", `{"DriverOpts":{"type":"nfs","o":"addr=10.0.0.1","device":":/export"}}`), false},
		{"volume create other driver", jsonReq("POST", "/v1.51/volumes/create", `{"Driver":"local-persist"}`), false},
		{"volume create cluster", jsonReq("POST", "/v1.51/volumes/create", `{"ClusterVolumeSpec":{}}`), false},
		{"volume create empty body", jsonReq("POST", "/v1.51/volumes/create", ""), false},
		{"volume remove", jsonReq("DELETE", "/v1.51/volumes/cache", ""), true},
		{"volume prune", jsonReq("POST", "/v1.51/volumes/prune", ""), true},
		{"volume update", jsonReq("PUT", "/v1.51/volumes/cache", `{}`), false},

		// Networks.
		{"network create", jsonReq("POST", "/v1.51/networks/create", `{"Name":"e2e"}`), true},
		{"network create bridge", jsonReq("POST", "/v1.51/networks/create", `{"Name":"e2e","Driver":"bridge","Internal":true}`), true},
		{"network create host", jsonReq("POST", "/v1.51/networks/create", `{"Name":"h","Driver":"host"}`), false},
		{"network create macvlan", jsonReq("POST", "/v1.51/networks/create", `{"Name":"m","Driver":"macvlan","Options":{"parent":"eth0"}}`), false},
		{"network create config from", jsonReq("POST", "/v1.51/networks/create", `{"Name":"m","ConfigFrom":{"Network":"cfg"}}`), false},
		{"network create empty body", jsonReq("POST", "/v1.51/networks/create", ""), false},
		{"network connect", jsonReq("POST", "/v1.51/networks/e2e/connect", `{"Container":"abc"}`), true},
		{"network connect host", jsonReq("POST", "/v1.51/networks/host/connect", `{"Container":"abc"}`), false},
		{"network disconnect", jsonReq("POST", "/v1.51/networks/e2e/disconnect", `{"Container":"abc"}`), true},
		{"network remove", jsonReq("DELETE", "/v1.51/networks/e2e", ""), true},

		// Images and builds.
		{"image pull", jsonReq("POST", "/v1.51/images/create?fromImage=busybox&tag=1.37.0", ""), true},
		{"image push", jsonReq("POST", "/v1.51/images/ghcr.io/isac322/x/push?tag=1", ""), true},
		{"image tag", jsonReq("POST", "/v1.51/images/abc/tag?repo=x&tag=y", ""), true},
		{"image remove", jsonReq("DELETE", "/v1.51/images/busybox:1.37.0", ""), true},
		{"image load", jsonReq("POST", "/v1.51/images/load", ""), true},
		{"commit", jsonReq("POST", "/v1.51/commit?container=abc", `{}`), true},
		{"build classic", jsonReq("POST", "/v1.51/build?t=x&networkmode=default", ""), true},
		{"build buildkit", jsonReq("POST", "/v1.51/build?version=2&session=s", ""), true},
		{"build network host", jsonReq("POST", "/v1.51/build?networkmode=host", ""), false},
		{"build network container", jsonReq("POST", "/v1.51/build?networkmode=container:abc", ""), false},
		{"build second networkmode", jsonReq("POST", "/v1.51/build?networkmode=default&networkmode=host", ""), false},
		{"build cgroup parent", jsonReq("POST", "/v1.51/build?cgroupparent=/", ""), false},
		{"build form-encoded body", formReq, false},
		{"build prune", jsonReq("POST", "/v1.51/build/prune", ""), true},
		{"buildkit session", jsonReq("POST", "/session", ""), true},
		{"buildkit grpc", jsonReq("POST", "/grpc", ""), true},
		{"login", jsonReq("POST", "/v1.51/auth", ""), true},

		// Default deny and path handling.
		{"unknown endpoint", jsonReq("POST", "/v1.51/foo", `{}`), false},
		{"unknown system endpoint", jsonReq("POST", "/v1.51/system/reload", `{}`), false},
		{"root post", jsonReq("POST", "/", ""), false},
		{"non-canonical path", jsonReq("POST", "/v1.51/images/../containers/create", create(`{"Privileged":true}`)), false},
		{"double slash", jsonReq("POST", "/v1.51//containers/abc/start", ""), false},
		{"unversioned create privileged", jsonReq("POST", "/containers/create", create(`{"Privileged":true}`)), false},
		{"lower-case method", jsonReq("post", "/v1.51/containers/abc/update", `{}`), false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := f.policy.Evaluate(tc.req)
			if got.Allow != tc.allow {
				t.Fatalf("Allow = %v, want %v (msg %q)", got.Allow, tc.allow, got.Msg)
			}
			if !got.Allow && got.Msg == "" {
				t.Fatal("deny without a message")
			}
		})
	}
}

func TestResolveHostPath(t *testing.T) {
	f := newFixture(t)
	cases := map[string]string{
		f.checkouts + "/repo":                                  f.checkouts + "/repo",
		f.checkouts + "/repo/inner/a/b":                        f.checkouts + "/repo/a/b",
		f.checkouts + "/repo/escape/issue-agent-authz-missing": "/issue-agent-authz-missing",
		f.scratch + "/wt/to-checkouts/x":                       f.checkouts + "/repo/x",
		f.checkouts + "/repo/../repo/./more":                   f.checkouts + "/repo/more",
	}
	for in, want := range cases {
		got, err := resolveHostPath(in)
		if err != nil || got != want {
			t.Errorf("resolveHostPath(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
}

func TestHandlers(t *testing.T) {
	s := &server{policy: newFixture(t).policy, log: json.NewEncoder(io.Discard)}
	do := func(h http.HandlerFunc, body []byte) map[string]any {
		t.Helper()
		rec := httptest.NewRecorder()
		h(rec, httptest.NewRequest("POST", "/", bytes.NewReader(body)))
		if rec.Code != http.StatusOK {
			t.Fatalf("status %d", rec.Code)
		}
		var out map[string]any
		if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
			t.Fatal(err)
		}
		return out
	}
	envelope := func(r AuthZRequest) []byte {
		b, err := json.Marshal(r)
		if err != nil {
			t.Fatal(err)
		}
		return b
	}

	if got := do(s.activate, nil); len(got["Implements"].([]any)) != 1 || got["Implements"].([]any)[0] != "authz" {
		t.Errorf("Activate = %v", got)
	}
	if got := do(s.authzReq, envelope(jsonReq("POST", "/v1.51/containers/create", create(`{"Privileged":true}`)))); got["Allow"] != false {
		t.Errorf("privileged create allowed: %v", got)
	}
	if got := do(s.authzReq, envelope(jsonReq("GET", "/v1.51/info", ""))); got["Allow"] != true {
		t.Errorf("info denied: %v", got)
	}
	if got := do(s.authzReq, []byte("not json")); got["Allow"] != false {
		t.Errorf("malformed request allowed: %v", got)
	}
	// dockerd itself refuses bodies over 4 MiB before calling the plugin; an
	// envelope above the plugin's own cap is denied rather than truncated.
	huge := jsonReq("POST", "/v1.51/containers/create", `{"Image":"busybox","Env":["X=`+strings.Repeat("a", maxRequest)+`"]}`)
	if got := do(s.authzReq, envelope(huge)); got["Allow"] != false {
		t.Errorf("oversized request allowed: %v", got)
	}
	// A 4 MiB create body (the largest dockerd forwards) is still evaluated.
	big := jsonReq("POST", "/v1.51/containers/create", `{"Image":"busybox","Env":["X=`+strings.Repeat("a", 4<<20-100)+`"],"HostConfig":{"Privileged":true}}`)
	if got := do(s.authzReq, envelope(big)); got["Allow"] != false {
		t.Errorf("4 MiB privileged create allowed: %v", got)
	}
	if got := do(s.authzRes, envelope(jsonReq("GET", "/v1.51/info", ""))); got["Allow"] != true {
		t.Errorf("AuthZRes = %v", got)
	}
}
