package main

import (
	"errors"
	"fmt"
	"os"
	"path"
	"sort"
	"strings"

	"golang.org/x/sys/unix"
)

// entryStat is the part of a stat(2) result the sweep needs.
type entryStat struct {
	Mode uint32
	UID  uint32
	GID  uint32
	Dev  uint64
	Ino  uint64
}

func (st entryStat) isDir() bool { return st.Mode&unix.S_IFMT == unix.S_IFDIR }

// fsOps is every filesystem call the sweep makes. Each one is relative to a
// directory fd and never follows a symlink; tests wrap sysOps to inject stat
// results or record chowns.
type fsOps interface {
	// openDirAt opens name below dirfd with O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC.
	openDirAt(dirfd int, name string) (int, error)
	// statAt is fstatat(dirfd, name, AT_SYMLINK_NOFOLLOW).
	statAt(dirfd int, name string) (entryStat, error)
	fstat(fd int) (entryStat, error)
	// chownAt is fchownat(dirfd, name, uid, gid, AT_SYMLINK_NOFOLLOW).
	chownAt(dirfd int, name string, uid, gid int) error
	readDirNames(fd int) ([]string, error)
	close(fd int) error
}

type sysOps struct{}

const dirFlags = unix.O_RDONLY | unix.O_DIRECTORY | unix.O_NOFOLLOW | unix.O_CLOEXEC

func toEntryStat(st *unix.Stat_t) entryStat {
	return entryStat{Mode: uint32(st.Mode), UID: st.Uid, GID: st.Gid, Dev: uint64(st.Dev), Ino: uint64(st.Ino)}
}

func (sysOps) openDirAt(dirfd int, name string) (int, error) {
	for {
		fd, err := unix.Openat(dirfd, name, dirFlags, 0)
		if err != unix.EINTR {
			return fd, err
		}
	}
}

func (sysOps) statAt(dirfd int, name string) (entryStat, error) {
	var st unix.Stat_t
	if err := unix.Fstatat(dirfd, name, &st, unix.AT_SYMLINK_NOFOLLOW); err != nil {
		return entryStat{}, err
	}
	return toEntryStat(&st), nil
}

func (sysOps) fstat(fd int) (entryStat, error) {
	var st unix.Stat_t
	if err := unix.Fstat(fd, &st); err != nil {
		return entryStat{}, err
	}
	return toEntryStat(&st), nil
}

func (sysOps) chownAt(dirfd int, name string, uid, gid int) error {
	return unix.Fchownat(dirfd, name, uid, gid, unix.AT_SYMLINK_NOFOLLOW)
}

// readDirNames lists fd through a duplicate so the caller keeps owning fd.
func (sysOps) readDirNames(fd int) ([]string, error) {
	dup, err := unix.Dup(fd)
	if err != nil {
		return nil, err
	}
	unix.CloseOnExec(dup)
	f := os.NewFile(uintptr(dup), "dir")
	defer f.Close()
	names, err := f.Readdirnames(-1)
	if err != nil {
		return nil, err
	}
	sort.Strings(names)
	return names, nil
}

func (sysOps) close(fd int) error { return unix.Close(fd) }

// maxDepth bounds the recursion (one open fd per level) below a worktree.
const maxDepth = 512

// sweeper chowns everything below <root>/<owner>/<repo>-worktrees/ to uid:gid
// without ever resolving a pathname through an agent-writable directory: the
// walk holds a directory fd per level and names only one component at a time.
type sweeper struct {
	ops      fsOps
	uid, gid int
	logf     func(format string, args ...any)

	rootDev uint64
	changed int
	failed  int
}

func (s *sweeper) fail(rel, op string, err error) {
	s.failed++
	s.logf("%s %s: %v", op, rel, err)
}

// sweep walks root. Only failing to open root is an error; per-entry
// failures are logged, counted and skipped.
func (s *sweeper) sweep(root string) error {
	rootfd, err := s.ops.openDirAt(unix.AT_FDCWD, root)
	if err != nil {
		return fmt.Errorf("open %s: %w", root, err)
	}
	defer s.ops.close(rootfd)
	rst, err := s.ops.fstat(rootfd)
	if err != nil {
		return fmt.Errorf("fstat %s: %w", root, err)
	}
	s.rootDev = rst.Dev
	owners, err := s.ops.readDirNames(rootfd)
	if err != nil {
		return fmt.Errorf("read %s: %w", root, err)
	}
	for _, owner := range owners {
		if strings.HasPrefix(owner, ".") {
			continue
		}
		ownerfd, ok := s.openLevel(rootfd, owner, owner)
		if !ok {
			continue
		}
		s.sweepOwner(ownerfd, owner)
		s.ops.close(ownerfd)
	}
	return nil
}

func (s *sweeper) sweepOwner(ownerfd int, owner string) {
	entries, err := s.ops.readDirNames(ownerfd)
	if err != nil {
		s.fail(owner, "read", err)
		return
	}
	for _, entry := range entries {
		if !strings.HasSuffix(entry, "-worktrees") || entry == "-worktrees" {
			continue
		}
		rel := path.Join(owner, entry)
		wtfd, ok := s.openLevel(ownerfd, entry, rel)
		if !ok {
			continue
		}
		names, err := s.ops.readDirNames(wtfd)
		if err != nil {
			s.fail(rel, "read", err)
		} else {
			for _, name := range names {
				s.visit(wtfd, name, path.Join(rel, name), 0)
			}
		}
		s.ops.close(wtfd)
	}
}

// openLevel opens a structural directory (<owner> or <repo>-worktrees) that is
// walked but never chowned. Anything else there (a symlink, a file, another
// filesystem) is skipped.
func (s *sweeper) openLevel(parent int, name, rel string) (int, bool) {
	st, err := s.ops.statAt(parent, name)
	if err != nil {
		s.fail(rel, "stat", err)
		return -1, false
	}
	if !st.isDir() || st.Dev != s.rootDev {
		return -1, false
	}
	return s.openDir(parent, name, rel)
}

// openDir opens name below parent and re-checks the opened directory: the
// entry may have been swapped since it was stat'ed.
func (s *sweeper) openDir(parent int, name, rel string) (int, bool) {
	fd, err := s.ops.openDirAt(parent, name)
	if err != nil {
		s.fail(rel, "open", err)
		return -1, false
	}
	st, err := s.ops.fstat(fd)
	if err != nil {
		s.fail(rel, "fstat", err)
		s.ops.close(fd)
		return -1, false
	}
	if !st.isDir() || st.Dev != s.rootDev {
		s.ops.close(fd)
		return -1, false
	}
	return fd, true
}

func (s *sweeper) visit(parent int, name, rel string, depth int) {
	st, err := s.ops.statAt(parent, name)
	if err != nil {
		if !errors.Is(err, unix.ENOENT) {
			s.fail(rel, "stat", err)
		}
		return
	}
	if st.Dev != s.rootDev {
		return
	}
	if st.UID != uint32(s.uid) || st.GID != uint32(s.gid) {
		if err := s.ops.chownAt(parent, name, s.uid, s.gid); err != nil {
			if !errors.Is(err, unix.ENOENT) {
				s.fail(rel, "chown", err)
			}
		} else {
			s.changed++
		}
	}
	if !st.isDir() {
		return
	}
	if depth >= maxDepth {
		s.fail(rel, "descend", fmt.Errorf("deeper than %d levels", maxDepth))
		return
	}
	fd, ok := s.openDir(parent, name, rel)
	if !ok {
		return
	}
	defer s.ops.close(fd)
	names, err := s.ops.readDirNames(fd)
	if err != nil {
		s.fail(rel, "read", err)
		return
	}
	for _, child := range names {
		s.visit(fd, child, path.Join(rel, child), depth+1)
	}
}
