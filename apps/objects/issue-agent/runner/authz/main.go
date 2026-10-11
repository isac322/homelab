// issue-agent-authz is a legacy (v1) Docker Engine authorization plugin for
// the issue-agent runner pod's dockerd sidecar. dockerd discovers it through
// /run/docker/plugins/issue-agent-authz.sock and consults it for every API
// request (--authorization-plugin=issue-agent-authz). A plugin error or an
// unreachable socket makes dockerd fail the request, so the policy fails
// closed. The policy itself lives in policy.go.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"
)

// pluginMediaType is the media type of moby's plugin protocol (pkg/plugins).
const pluginMediaType = "application/vnd.docker.plugins.v1.2+json"

// maxRequest bounds a plugin request: dockerd forwards at most 4 MiB of body,
// base64-encoded inside the JSON envelope, plus headers.
const maxRequest = 16 << 20

type server struct {
	policy *Policy
	log    *json.Encoder
}

func (s *server) logEvent(fields map[string]any) {
	fields["time"] = time.Now().UTC().Format(time.RFC3339Nano)
	_ = s.log.Encode(fields)
}

func reply(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", pluginMediaType)
	_ = json.NewEncoder(w).Encode(v)
}

func (s *server) activate(w http.ResponseWriter, _ *http.Request) {
	reply(w, map[string][]string{"Implements": {"authz"}})
}

func (s *server) authzReq(w http.ResponseWriter, r *http.Request) {
	var req AuthZRequest
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, maxRequest))
	if err == nil {
		err = json.Unmarshal(body, &req)
	}
	if err != nil {
		msg := "issue-agent docker policy: unreadable authorization request"
		s.logEvent(map[string]any{"event": "deny", "reason": msg, "error": err.Error()})
		reply(w, AuthZResponse{Allow: false, Msg: msg})
		return
	}
	resp := s.policy.Evaluate(req)
	if !resp.Allow {
		// Bodies and headers are never logged: they may carry environment
		// values or registry credentials.
		s.logEvent(map[string]any{
			"event":  "deny",
			"method": req.RequestMethod,
			"uri":    req.RequestURI,
			"reason": resp.Msg,
		})
	}
	reply(w, resp)
}

func (s *server) authzRes(w http.ResponseWriter, r *http.Request) {
	_, _ = io.Copy(io.Discard, http.MaxBytesReader(w, r.Body, maxRequest))
	reply(w, AuthZResponse{Allow: true})
}

func run() error {
	socket := flag.String("socket", "/run/docker/plugins/issue-agent-authz.sock", "unix socket path dockerd discovers the plugin at")
	flag.Parse()
	if flag.NArg() != 0 {
		return fmt.Errorf("unexpected arguments: %v", flag.Args())
	}

	if err := os.MkdirAll(filepath.Dir(*socket), 0o755); err != nil {
		return err
	}
	if err := os.Remove(*socket); err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("remove stale socket: %w", err)
	}
	// The socket only appears once it is ready to serve; restrict it to root
	// (dockerd) before it becomes visible under its final name.
	tmp := *socket + ".tmp"
	_ = os.Remove(tmp)
	ln, err := net.Listen("unix", tmp)
	if err != nil {
		return err
	}
	if err := os.Chmod(tmp, 0o600); err != nil {
		ln.Close()
		return err
	}
	if err := os.Rename(tmp, *socket); err != nil {
		ln.Close()
		return err
	}

	s := &server{policy: DefaultPolicy(), log: json.NewEncoder(os.Stderr)}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /Plugin.Activate", s.activate)
	mux.HandleFunc("POST /AuthZPlugin.AuthZReq", s.authzReq)
	mux.HandleFunc("POST /AuthZPlugin.AuthZRes", s.authzRes)
	srv := &http.Server{Handler: mux, ReadHeaderTimeout: 10 * time.Second}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	errc := make(chan error, 1)
	go func() { errc <- srv.Serve(ln) }()
	s.logEvent(map[string]any{"event": "listening", "socket": *socket})

	select {
	case err := <-errc:
		return err
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		return srv.Shutdown(shutdownCtx)
	}
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "issue-agent-authz: %v\n", err)
		os.Exit(1)
	}
}
