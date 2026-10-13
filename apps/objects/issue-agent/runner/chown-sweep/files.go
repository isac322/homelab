package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strconv"

	"golang.org/x/sys/unix"
)

// The janitor's files live in <checkouts>/.issue-agent-janitor, a directory
// the agent uid can write. Root reaches them only through O_NOFOLLOW directory
// fds and single-component names, never through a shell pathname.
const (
	janitorDir   = ".issue-agent-janitor"
	statusFile   = "status"
	requestFile  = "prune-request"
	maxFileBytes = 4096
)

var (
	// errAbsent: there is no prune request (or no janitor directory yet).
	errAbsent = errors.New("absent")
	// errInvalid: the request exists but is not a usable regular JSON file.
	errInvalid = errors.New("invalid")
)

// janitorFiles writes files that uid:gid (the publisher) must be able to
// read and replace.
type janitorFiles struct {
	checkouts string
	uid, gid  int
}

// openDir opens <checkouts>/.issue-agent-janitor, creating it (0700, owned by
// uid:gid) when create is set.
func (j janitorFiles) openDir(create bool) (int, error) {
	rootfd, err := unix.Open(j.checkouts, dirFlags, 0)
	if err != nil {
		return -1, fmt.Errorf("open %s: %w", j.checkouts, err)
	}
	defer unix.Close(rootfd)
	fd, err := unix.Openat(rootfd, janitorDir, dirFlags, 0)
	if errors.Is(err, unix.ENOENT) && create {
		if err := unix.Mkdirat(rootfd, janitorDir, 0o700); err != nil && !errors.Is(err, unix.EEXIST) {
			return -1, fmt.Errorf("mkdir %s: %w", janitorDir, err)
		}
		fd, err = unix.Openat(rootfd, janitorDir, dirFlags, 0)
		if err == nil {
			if err := unix.Fchown(fd, j.uid, j.gid); err != nil {
				unix.Close(fd)
				return -1, fmt.Errorf("chown %s: %w", janitorDir, err)
			}
		}
	}
	if err != nil {
		if errors.Is(err, unix.ENOENT) {
			return -1, errAbsent
		}
		return -1, fmt.Errorf("open %s: %w", janitorDir, err)
	}
	return fd, nil
}

// status is the janitor's per-loop report (GET /janitor/status serves it).
type status struct {
	CheckedAt       int64   `json:"checked_at"`
	DockerUsedPct   int64   `json:"docker_used_pct"`
	LastPruneAt     *int64  `json:"last_prune_at"`
	LastPruneLease  *int64  `json:"last_prune_lease"`
	LastPruneResult *string `json:"last_prune_result"`
}

// parseStatusArgs reads CHECKED_AT USED_PCT LAST_PRUNE_AT LAST_PRUNE_LEASE
// LAST_PRUNE_RESULT; "-" stands for null in the last three.
func parseStatusArgs(args []string) (status, error) {
	if len(args) != 5 {
		return status{}, fmt.Errorf("want 5 status fields, got %d", len(args))
	}
	var st status
	var err error
	if st.CheckedAt, err = strconv.ParseInt(args[0], 10, 64); err != nil || st.CheckedAt <= 0 {
		return status{}, fmt.Errorf("invalid checked_at %q", args[0])
	}
	if st.DockerUsedPct, err = strconv.ParseInt(args[1], 10, 64); err != nil || st.DockerUsedPct < 0 || st.DockerUsedPct > 100 {
		return status{}, fmt.Errorf("invalid docker_used_pct %q", args[1])
	}
	optional := func(name, value string) (*int64, error) {
		if value == "-" {
			return nil, nil
		}
		n, err := strconv.ParseInt(value, 10, 64)
		if err != nil || n <= 0 {
			return nil, fmt.Errorf("invalid %s %q", name, value)
		}
		return &n, nil
	}
	if st.LastPruneAt, err = optional("last_prune_at", args[2]); err != nil {
		return status{}, err
	}
	if st.LastPruneLease, err = optional("last_prune_lease", args[3]); err != nil {
		return status{}, err
	}
	switch args[4] {
	case "-":
	case "ok", "error":
		result := args[4]
		st.LastPruneResult = &result
	default:
		return status{}, fmt.Errorf("invalid last_prune_result %q", args[4])
	}
	return st, nil
}

// writeStatus atomically replaces the status file: an O_EXCL|O_NOFOLLOW temp
// file in the directory fd, chowned through its own fd, renamed over status
// (which replaces a planted symlink instead of following it).
func (j janitorFiles) writeStatus(st status) error {
	payload, err := json.Marshal(st)
	if err != nil {
		return err
	}
	dirfd, err := j.openDir(true)
	if err != nil {
		return err
	}
	defer unix.Close(dirfd)
	tmp := fmt.Sprintf(".%s.%d", statusFile, os.Getpid())
	const flags = unix.O_WRONLY | unix.O_CREAT | unix.O_EXCL | unix.O_NOFOLLOW | unix.O_CLOEXEC
	fd, err := unix.Openat(dirfd, tmp, flags, 0o644)
	if errors.Is(err, unix.EEXIST) {
		// A leftover (or planted) entry: unlinkat removes a link, not its target.
		if err := unix.Unlinkat(dirfd, tmp, 0); err != nil {
			return fmt.Errorf("unlink %s: %w", tmp, err)
		}
		fd, err = unix.Openat(dirfd, tmp, flags, 0o644)
	}
	if err != nil {
		return fmt.Errorf("create %s: %w", tmp, err)
	}
	f := os.NewFile(uintptr(fd), tmp)
	_, err = f.Write(payload)
	if err == nil {
		err = f.Chown(j.uid, j.gid)
	}
	if err == nil {
		err = f.Sync()
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err == nil {
		err = unix.Renameat(dirfd, tmp, dirfd, statusFile)
	}
	if err != nil {
		unix.Unlinkat(dirfd, tmp, 0)
		return fmt.Errorf("write %s: %w", statusFile, err)
	}
	return nil
}

// pruneRequest is the publisher's {"requested_at", "lease_until"} file.
type pruneRequest struct {
	RequestedAt int64 `json:"requested_at"`
	LeaseUntil  int64 `json:"lease_until"`
}

// readRequest returns the prune request, errAbsent when there is none, or an
// error wrapping errInvalid when it must be dropped.
func (j janitorFiles) readRequest() (pruneRequest, error) {
	dirfd, err := j.openDir(false)
	if err != nil {
		return pruneRequest{}, err
	}
	defer unix.Close(dirfd)
	fd, err := unix.Openat(dirfd, requestFile, unix.O_RDONLY|unix.O_NOFOLLOW|unix.O_NONBLOCK|unix.O_CLOEXEC, 0)
	if errors.Is(err, unix.ENOENT) {
		return pruneRequest{}, errAbsent
	}
	if err != nil {
		return pruneRequest{}, fmt.Errorf("%w: open: %v", errInvalid, err)
	}
	f := os.NewFile(uintptr(fd), requestFile)
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return pruneRequest{}, fmt.Errorf("stat %s: %w", requestFile, err)
	}
	if !info.Mode().IsRegular() {
		return pruneRequest{}, fmt.Errorf("%w: not a regular file", errInvalid)
	}
	data, err := io.ReadAll(io.LimitReader(f, maxFileBytes+1))
	if err != nil {
		return pruneRequest{}, fmt.Errorf("read %s: %w", requestFile, err)
	}
	if len(data) > maxFileBytes {
		return pruneRequest{}, fmt.Errorf("%w: larger than %d bytes", errInvalid, maxFileBytes)
	}
	var req pruneRequest
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		return pruneRequest{}, fmt.Errorf("%w: %v", errInvalid, err)
	}
	if req.LeaseUntil <= 0 {
		return pruneRequest{}, fmt.Errorf("%w: no lease_until", errInvalid)
	}
	return req, nil
}

// dropRequest unlinks the prune request (the link itself, if it is one).
func (j janitorFiles) dropRequest() error {
	dirfd, err := j.openDir(false)
	if errors.Is(err, errAbsent) {
		return nil
	}
	if err != nil {
		return err
	}
	defer unix.Close(dirfd)
	if err := unix.Unlinkat(dirfd, requestFile, 0); err != nil && !errors.Is(err, unix.ENOENT) {
		return fmt.Errorf("unlink %s: %w", requestFile, err)
	}
	return nil
}
