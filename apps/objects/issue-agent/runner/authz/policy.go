package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"mime"
	"net/url"
	"path"
	"path/filepath"
	"regexp"
	"strings"
)

// AuthZRequest mirrors moby pkg/authorization.Request (docker-v29.9.0
// pkg/authorization/api.go). RequestBody is only populated by dockerd for
// bodies with Content-Type application/json of at most 4 MiB
// (pkg/authorization/authz.go sendBody/maxBodySize).
type AuthZRequest struct {
	User            string            `json:"User,omitempty"`
	UserAuthNMethod string            `json:"UserAuthNMethod,omitempty"`
	RequestMethod   string            `json:"RequestMethod,omitempty"`
	RequestURI      string            `json:"RequestUri,omitempty"`
	RequestBody     []byte            `json:"RequestBody,omitempty"`
	RequestHeaders  map[string]string `json:"RequestHeaders,omitempty"`
}

// AuthZResponse mirrors moby pkg/authorization.Response.
type AuthZResponse struct {
	Allow bool   `json:"Allow"`
	Msg   string `json:"Msg,omitempty"`
	Err   string `json:"Err,omitempty"`
}

// Policy is the pod-local Docker API allowlist. Anything not explicitly
// allowed is denied.
type Policy struct {
	// BindRoots are canonical (symlink-free) directories; a bind source must
	// resolve strictly below one of them.
	BindRoots []string
	// SocketDir holds the daemon socket; binds resolving to it or below it are
	// always denied.
	SocketDir string
	// AllowedDevices is the exact set of Devices[].PathOnHost values allowed.
	AllowedDevices map[string]bool
	// Resolve canonicalises an absolute host path in the daemon's mount
	// namespace (EvalSymlinks on the longest existing prefix).
	Resolve func(string) (string, error)
}

// DefaultPolicy returns the production policy for the issue-agent runner pod.
func DefaultPolicy() *Policy {
	return &Policy{
		BindRoots: []string{"/home/agent/checkouts", "/tmp/issue-agent"},
		SocketDir: "/run/issue-agent-docker",
		AllowedDevices: map[string]bool{
			"/dev/dri":            true,
			"/dev/dri/card0":      true,
			"/dev/dri/renderD128": true,
		},
		Resolve: resolveHostPath,
	}
}

type deny string

// versionPrefix matches moby's "/v{version:[0-9.]+}" route prefix.
var versionPrefix = regexp.MustCompile(`^/v[0-9.]+(/|$)`)

// Evaluate returns the decision for one API request.
func (p *Policy) Evaluate(req AuthZRequest) AuthZResponse {
	if reason := p.evaluate(req); reason != "" {
		return AuthZResponse{Allow: false, Msg: "issue-agent docker policy: " + string(reason)}
	}
	return AuthZResponse{Allow: true}
}

func (p *Policy) evaluate(req AuthZRequest) deny {
	u, err := url.ParseRequestURI(req.RequestURI)
	if err != nil {
		return "unparseable request URI"
	}
	method := strings.ToUpper(req.RequestMethod)
	readOnly := method == "GET" || method == "HEAD"

	p0 := u.Path
	if loc := versionPrefix.FindStringIndex(p0); loc != nil {
		p0 = "/" + p0[loc[1]:]
	}
	clean := path.Clean("/" + p0)
	if !readOnly && clean != p0 && clean+"/" != p0 {
		return "non-canonical request path"
	}
	seg := strings.Split(strings.TrimPrefix(clean, "/"), "/")

	switch seg[0] {
	case "swarm", "services", "secrets", "configs", "nodes", "tasks":
		return deny("swarm endpoints are disabled (/" + seg[0] + ")")
	}
	if readOnly {
		return ""
	}

	// moby's handlers call r.ParseForm, which reads form-encoded bodies into
	// the same values as the query string; such bodies are invisible here.
	if ct := header(req.RequestHeaders, "Content-Type"); ct != "" {
		if mt, _, err := mime.ParseMediaType(ct); err == nil &&
			(mt == "application/x-www-form-urlencoded" || mt == "multipart/form-data") {
			return "form-encoded request bodies are not allowed"
		}
	}

	route := method + " " + routePattern(method, seg)
	switch route {
	// Containers.
	case "POST /containers/create":
		return p.checkContainerCreate(req.RequestBody)
	case "POST /containers/*/start":
		return checkEmptyBody(req.RequestBody, "container start")
	case "POST /containers/*/exec":
		return checkExecCreate(req.RequestBody)
	case "POST /containers/*/update":
		return "container update is not allowed"
	case "POST /containers/*/stop", "POST /containers/*/restart", "POST /containers/*/kill",
		"POST /containers/*/wait", "POST /containers/*/pause", "POST /containers/*/unpause",
		"POST /containers/*/resize", "POST /containers/*/attach", "POST /containers/*/rename",
		"PUT /containers/*/archive", "DELETE /containers/*", "POST /containers/prune",
		"POST /exec/*/start", "POST /exec/*/resize":
		return ""

	// Images and builds.
	case "POST /commit", "POST /build/prune", "POST /build/cancel", "POST /grpc", "POST /session", "POST /auth":
		return ""
	case "POST /build":
		return checkClassicBuild(u.Query())

	// Volumes.
	case "POST /volumes/create":
		return checkVolumeCreate(req.RequestBody)
	case "DELETE /volumes/*", "POST /volumes/prune":
		return ""

	// Networks.
	case "POST /networks/create":
		return checkNetworkCreate(req.RequestBody)
	case "POST /networks/*/connect":
		if seg[1] == "host" || seg[1] == "none" {
			return deny("connecting to the " + seg[1] + " network is not allowed")
		}
		return ""
	case "POST /networks/*/disconnect", "DELETE /networks/*", "POST /networks/prune":
		return ""
	}

	switch seg[0] {
	case "images":
		// pull/import/load/push/tag/remove/prune
		return ""
	case "plugins":
		return "plugin management is not allowed"
	}
	return deny("endpoint " + method + " /" + strings.Join(seg, "/") + " is not on the allowlist")
}

// routePattern replaces the variable {id}/{name} segment of the container,
// exec, network and volume routes with "*". The fixed POST routes
// .../create and .../prune keep their literal segment; any other method on
// such a path addresses an object that happens to carry that name.
func routePattern(method string, seg []string) string {
	out := make([]string, len(seg))
	copy(out, seg)
	switch out[0] {
	case "containers", "networks", "volumes", "exec":
		literal := method == "POST" && len(out) == 2 && (out[1] == "create" || out[1] == "prune")
		if len(out) >= 2 && !literal {
			out[1] = "*"
		}
	}
	return "/" + strings.Join(out, "/")
}

func header(h map[string]string, name string) string {
	for k, v := range h {
		if strings.EqualFold(k, name) {
			return v
		}
	}
	return ""
}

// decodeBody mirrors moby's decoding (encoding/json, case-insensitive field
// names, last duplicate wins, trailing content rejected). A missing body means
// dockerd did not forward it (non-JSON Content-Type), so it is denied.
func decodeBody(body []byte, what string, out any) deny {
	if len(bytes.TrimSpace(body)) == 0 {
		return deny(what + " requires a JSON body (Content-Type: application/json)")
	}
	dec := json.NewDecoder(bytes.NewReader(body))
	if err := dec.Decode(out); err != nil {
		return deny(what + " body is not valid JSON: " + err.Error())
	}
	if dec.More() {
		return deny(what + " body has trailing content")
	}
	return ""
}

func checkEmptyBody(body []byte, what string) deny {
	b := bytes.TrimSpace(body)
	if len(b) == 0 || string(b) == "{}" || string(b) == "null" {
		return ""
	}
	return deny(what + " must not carry a body")
}

type deviceMapping struct {
	PathOnHost        string
	PathInContainer   string
	CgroupPermissions string
}

type mountSpec struct {
	Type          string
	Source        string
	Target        string
	VolumeOptions *struct {
		DriverConfig *struct {
			Name    string
			Options map[string]string
		}
	}
}

type hostConfig struct {
	Binds             []string
	NetworkMode       string
	VolumeDriver      string
	VolumesFrom       []string
	Mounts            []mountSpec
	CapAdd            []string
	CgroupnsMode      string
	IpcMode           string
	PidMode           string
	Privileged        bool
	SecurityOpt       []string
	UTSMode           string
	UsernsMode        string
	Sysctls           map[string]string
	Runtime           string
	CgroupParent      string
	Devices           []deviceMapping
	DeviceCgroupRules []string
	DeviceRequests    []json.RawMessage
	MaskedPaths       []string
	ReadonlyPaths     []string
}

type createRequest struct {
	HostConfig       *hostConfig
	NetworkingConfig *struct {
		EndpointsConfig map[string]json.RawMessage
	}
}

// allowedSecurityOpts is an allowlist: any other entry (seccomp/apparmor
// profiles, label=disable, systempaths=unconfined, no-new-privileges=false)
// is denied.
var allowedSecurityOpts = map[string]bool{
	"no-new-privileges":      true,
	"no-new-privileges=true": true,
	"no-new-privileges:true": true,
}

func (p *Policy) checkContainerCreate(body []byte) deny {
	var r createRequest
	if d := decodeBody(body, "container create", &r); d != "" {
		return d
	}
	if r.NetworkingConfig != nil {
		for name := range r.NetworkingConfig.EndpointsConfig {
			if name == "host" || strings.HasPrefix(name, "container:") {
				return deny("NetworkingConfig endpoint " + name + " is not allowed")
			}
		}
	}
	h := r.HostConfig
	if h == nil {
		return ""
	}
	switch {
	case h.Privileged:
		return "privileged containers are not allowed"
	case len(h.CapAdd) > 0:
		return "CapAdd is not allowed"
	case h.NetworkMode == "host" || strings.HasPrefix(h.NetworkMode, "container:"):
		return deny("NetworkMode " + h.NetworkMode + " is not allowed")
	case h.PidMode == "host":
		return "PidMode host is not allowed"
	case h.IpcMode == "host":
		return "IpcMode host is not allowed"
	case h.UTSMode == "host":
		return "UTSMode host is not allowed"
	case h.UsernsMode == "host":
		return "UsernsMode host is not allowed"
	case h.CgroupnsMode == "host":
		return "CgroupnsMode host is not allowed"
	case h.CgroupParent != "":
		return "CgroupParent is not allowed"
	case len(h.DeviceCgroupRules) > 0:
		return "DeviceCgroupRules are not allowed"
	case len(h.DeviceRequests) > 0:
		return "DeviceRequests are not allowed"
	case len(h.Sysctls) > 0:
		return "Sysctls are not allowed"
	case h.Runtime != "" && h.Runtime != "runc":
		return deny("Runtime " + h.Runtime + " is not allowed")
	case h.VolumeDriver != "":
		return "VolumeDriver is not allowed"
	case len(h.VolumesFrom) > 0:
		return "VolumesFrom is not allowed"
	case h.MaskedPaths != nil || h.ReadonlyPaths != nil:
		return "overriding MaskedPaths/ReadonlyPaths (systempaths=unconfined) is not allowed"
	}
	for _, o := range h.SecurityOpt {
		if !allowedSecurityOpts[strings.TrimSpace(o)] {
			return deny("SecurityOpt " + o + " is not allowed")
		}
	}
	for _, d := range h.Devices {
		if !p.AllowedDevices[d.PathOnHost] {
			return deny("device " + d.PathOnHost + " is not allowed")
		}
	}
	for _, b := range h.Binds {
		fields := strings.Split(b, ":")
		if len(fields) == 1 {
			continue // anonymous volume at a container path
		}
		src := fields[0]
		if src == "" {
			return deny("bind " + b + " has an empty source")
		}
		if !strings.HasPrefix(src, "/") {
			continue // named volume (implicitly created with the local driver, no options)
		}
		if d := p.checkBindSource(src); d != "" {
			return d
		}
	}
	for _, m := range h.Mounts {
		switch m.Type {
		case "bind":
			if d := p.checkBindSource(m.Source); d != "" {
				return d
			}
		case "volume":
			if m.VolumeOptions != nil && m.VolumeOptions.DriverConfig != nil {
				return "volume mounts with VolumeOptions.DriverConfig are not allowed"
			}
		case "tmpfs", "image":
		default:
			return deny(fmt.Sprintf("mount type %q is not allowed", m.Type))
		}
	}
	return ""
}

func (p *Policy) checkBindSource(src string) deny {
	if !strings.HasPrefix(src, "/") {
		return deny("bind source " + src + " is not absolute")
	}
	resolved, err := p.Resolve(src)
	if err != nil {
		return deny("cannot resolve bind source " + src + ": " + err.Error())
	}
	if p.SocketDir != "" && (resolved == p.SocketDir || strings.HasPrefix(resolved, p.SocketDir+"/")) {
		return deny("bind source " + src + " references the Docker socket")
	}
	for _, root := range p.BindRoots {
		if strings.HasPrefix(resolved, root+"/") {
			return ""
		}
	}
	return deny(fmt.Sprintf("bind source %s (resolved %s) is outside %s", src, resolved, strings.Join(p.BindRoots, ", ")))
}

// resolveHostPath resolves symlinks in the longest existing prefix of an
// absolute path and appends the remaining (cleaned, ".."-free) components;
// dockerd creates missing Binds sources itself.
func resolveHostPath(p string) (string, error) {
	p = filepath.Clean(p)
	var tail []string
	cur := p
	for {
		r, err := filepath.EvalSymlinks(cur)
		if err == nil {
			for i := len(tail) - 1; i >= 0; i-- {
				r = filepath.Join(r, tail[i])
			}
			return r, nil
		}
		if !errors.Is(err, fs.ErrNotExist) {
			return "", err
		}
		parent := filepath.Dir(cur)
		if parent == cur {
			return "", err
		}
		tail = append(tail, filepath.Base(cur))
		cur = parent
	}
}

func checkExecCreate(body []byte) deny {
	var r struct{ Privileged bool }
	if d := decodeBody(body, "exec create", &r); d != "" {
		return d
	}
	if r.Privileged {
		return "privileged exec is not allowed"
	}
	return ""
}

func checkVolumeCreate(body []byte) deny {
	var r struct {
		Driver            string
		DriverOpts        map[string]string
		ClusterVolumeSpec json.RawMessage
	}
	if d := decodeBody(body, "volume create", &r); d != "" {
		return d
	}
	if r.Driver != "" && r.Driver != "local" {
		return deny("volume driver " + r.Driver + " is not allowed")
	}
	if len(r.ClusterVolumeSpec) > 0 && string(bytes.TrimSpace(r.ClusterVolumeSpec)) != "null" {
		return "cluster volumes are not allowed"
	}
	if len(r.DriverOpts) > 0 {
		// local driver opts (type/o/device) mount arbitrary host paths or
		// network filesystems (o=bind, device=/...).
		return "volume DriverOpts are not allowed"
	}
	return ""
}

func checkNetworkCreate(body []byte) deny {
	var r struct {
		Driver     string
		ConfigFrom *struct{ Network string }
	}
	if d := decodeBody(body, "network create", &r); d != "" {
		return d
	}
	if r.Driver != "" && r.Driver != "bridge" {
		return deny("network driver " + r.Driver + " is not allowed")
	}
	if r.ConfigFrom != nil && r.ConfigFrom.Network != "" {
		return "ConfigFrom networks are not allowed"
	}
	return ""
}

// checkClassicBuild inspects the query parameters moby's /build route reads
// with r.FormValue (exact, lower-case keys).
func checkClassicBuild(q url.Values) deny {
	for _, v := range q["networkmode"] {
		if v == "host" || strings.HasPrefix(v, "container:") {
			return deny("build networkmode " + v + " is not allowed")
		}
	}
	for _, v := range q["cgroupparent"] {
		if v != "" {
			return "build cgroupparent is not allowed"
		}
	}
	return ""
}
