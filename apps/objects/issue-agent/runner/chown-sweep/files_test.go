package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func newFiles(t *testing.T) (janitorFiles, string) {
	base, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	checkouts := filepath.Join(base, "checkouts")
	outside := filepath.Join(base, "outside")
	for _, d := range []string{checkouts, outside} {
		if err := os.Mkdir(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(outside, "keep"), []byte("keep"), 0o644); err != nil {
		t.Fatal(err)
	}
	return janitorFiles{checkouts: checkouts, uid: os.Getuid(), gid: os.Getgid()}, outside
}

func assertKeep(t *testing.T, outside string) {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(outside, "keep"))
	if err != nil || string(data) != "keep" {
		t.Fatalf("outside/keep changed: %q %v", data, err)
	}
	entries, _ := os.ReadDir(outside)
	if len(entries) != 1 {
		t.Fatalf("outside has %d entries", len(entries))
	}
}

func TestParseStatusArgs(t *testing.T) {
	st, err := parseStatusArgs([]string{"1791856534", "73", "-", "-", "-"})
	if err != nil || st.LastPruneAt != nil || st.LastPruneLease != nil || st.LastPruneResult != nil {
		t.Fatalf("%+v %v", st, err)
	}
	st, err = parseStatusArgs([]string{"1791856534", "40", "1791856000", "1791857000", "error"})
	if err != nil || *st.LastPruneAt != 1791856000 || *st.LastPruneLease != 1791857000 || *st.LastPruneResult != "error" {
		t.Fatalf("%+v %v", st, err)
	}
	for _, bad := range [][]string{
		{"1", "2", "-", "-"},
		{"x", "2", "-", "-", "-"},
		{"1", "101", "-", "-", "-"},
		{"1", "2", "0", "-", "-"},
		{"1", "2", "-", "-", "skipped"},
	} {
		if _, err := parseStatusArgs(bad); err == nil {
			t.Fatalf("accepted %q", bad)
		}
	}
}

func TestWriteStatusCreatesDirAndWritesJSON(t *testing.T) {
	j, _ := newFiles(t)
	st, _ := parseStatusArgs([]string{"1791856534", "73", "1791856000", "1791857000", "ok"})
	if err := j.writeStatus(st); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(j.checkouts, janitorDir)
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0o700 {
		t.Fatalf("janitor dir: %v %v", info, err)
	}
	data, err := os.ReadFile(filepath.Join(dir, statusFile))
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"checked_at": 1791856534.0, "docker_used_pct": 73.0, "last_prune_at": 1791856000.0,
		"last_prune_lease": 1791857000.0, "last_prune_result": "ok"}
	if len(got) != len(want) {
		t.Fatalf("status %v", got)
	}
	for k, v := range want {
		if got[k] != v {
			t.Fatalf("status %v", got)
		}
	}
	// A rewrite leaves no temp files behind; nulls are serialised as null.
	st, _ = parseStatusArgs([]string{"1791856999", "10", "-", "-", "-"})
	if err := j.writeStatus(st); err != nil {
		t.Fatal(err)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 {
		t.Fatalf("janitor dir has %d entries", len(entries))
	}
	data, _ = os.ReadFile(filepath.Join(dir, statusFile))
	if string(data) != `{"checked_at":1791856999,"docker_used_pct":10,"last_prune_at":null,"last_prune_lease":null,"last_prune_result":null}` {
		t.Fatalf("status %s", data)
	}
}

func TestWriteStatusNeverFollowsLinks(t *testing.T) {
	j, outside := newFiles(t)
	st, _ := parseStatusArgs([]string{"1791856534", "73", "-", "-", "-"})
	dir := filepath.Join(j.checkouts, janitorDir)

	// Symlinked janitor directory: refused.
	if err := os.Symlink(outside, dir); err != nil {
		t.Fatal(err)
	}
	if err := j.writeStatus(st); err == nil {
		t.Fatal("wrote through a symlinked janitor dir")
	}
	assertKeep(t, outside)
	os.Remove(dir)

	// Symlinked status and planted temp name: replaced, not followed.
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	keep := filepath.Join(outside, "keep")
	for _, name := range []string{statusFile, ".status." + itoa(os.Getpid())} {
		if err := os.Symlink(keep, filepath.Join(dir, name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := j.writeStatus(st); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(filepath.Join(dir, statusFile))
	if err != nil || !info.Mode().IsRegular() {
		t.Fatalf("status: %v %v", info, err)
	}
	assertKeep(t, outside)
}

func itoa(n int) string { b, _ := json.Marshal(n); return string(b) }

func writeRequest(t *testing.T, j janitorFiles, body string) string {
	dir := filepath.Join(j.checkouts, janitorDir)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(dir, requestFile)
	if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestReadRequest(t *testing.T) {
	j, outside := newFiles(t)
	if _, err := j.readRequest(); !errors.Is(err, errAbsent) {
		t.Fatalf("no janitor dir: %v", err)
	}
	p := writeRequest(t, j, `{"requested_at": 1791856534, "lease_until": 1791857734}`)
	req, err := j.readRequest()
	if err != nil || req.LeaseUntil != 1791857734 || req.RequestedAt != 1791856534 {
		t.Fatalf("%+v %v", req, err)
	}
	for _, body := range []string{
		`{"requested_at": 1791856534}`, // legacy request without a lease
		`{"lease_until": "soon"}`,
		`{"lease_until": 1, "force": true}`,
		`not json`,
	} {
		writeRequest(t, j, body)
		if _, err := j.readRequest(); !errors.Is(err, errInvalid) {
			t.Fatalf("%s: %v", body, err)
		}
	}
	os.Remove(p)
	if err := os.Symlink(filepath.Join(outside, "keep"), p); err != nil {
		t.Fatal(err)
	}
	if _, err := j.readRequest(); !errors.Is(err, errInvalid) {
		t.Fatalf("symlinked request: %v", err)
	}
	if err := j.dropRequest(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(p); !os.IsNotExist(err) {
		t.Fatalf("request still present: %v", err)
	}
	assertKeep(t, outside)
	if err := j.dropRequest(); err != nil {
		t.Fatalf("dropping a missing request: %v", err)
	}
}

func TestRunExitCodes(t *testing.T) {
	j, _ := newFiles(t)
	if code := run([]string{"read-request", j.checkouts}); code != exitAbsent {
		t.Fatalf("absent: %d", code)
	}
	writeRequest(t, j, `{}`)
	if code := run([]string{"read-request", j.checkouts}); code != exitInvalid {
		t.Fatalf("invalid: %d", code)
	}
	if code := run([]string{"drop-request", j.checkouts}); code != 0 {
		t.Fatalf("drop: %d", code)
	}
	if code := run([]string{"bogus", j.checkouts}); code != exitUsage {
		t.Fatalf("usage: %d", code)
	}
	if code := run([]string{"status", j.checkouts, "1"}); code != exitUsage {
		t.Fatalf("status usage: %d", code)
	}
}
