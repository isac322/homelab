package main

import (
	"os"
	"path/filepath"
	"sort"
	"syscall"
	"testing"

	"golang.org/x/sys/unix"
)

// recordingOps runs the real fd-anchored calls but records chowns (by inode,
// mapped back to a path by the test) instead of making them, so the tests run
// as a non-root user. statOverride replaces the stat of a named entry.
type recordingOps struct {
	sysOps
	chowned      []uint64
	statOverride map[string]func(entryStat) entryStat
}

func (o *recordingOps) statAt(dirfd int, name string) (entryStat, error) {
	st, err := o.sysOps.statAt(dirfd, name)
	if err == nil && o.statOverride[name] != nil {
		st = o.statOverride[name](st)
	}
	return st, err
}

func (o *recordingOps) chownAt(dirfd int, name string, uid, gid int) error {
	st, err := o.sysOps.statAt(dirfd, name)
	if err != nil {
		return err
	}
	o.chowned = append(o.chowned, st.Ino)
	return nil
}

type tree struct {
	t       *testing.T
	root    string // the checkouts directory
	outside string
}

func newTree(t *testing.T) *tree {
	base, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	tr := &tree{t: t, root: filepath.Join(base, "checkouts"), outside: filepath.Join(base, "outside")}
	tr.file(filepath.Join(tr.outside, "keep"))
	tr.dir("")
	return tr
}

func (tr *tree) dir(rel string) {
	if err := os.MkdirAll(filepath.Join(tr.root, rel), 0o755); err != nil {
		tr.t.Fatal(err)
	}
}

func (tr *tree) file(abs string) {
	if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
		tr.t.Fatal(err)
	}
	if err := os.WriteFile(abs, []byte("x"), 0o644); err != nil {
		tr.t.Fatal(err)
	}
}

func (tr *tree) symlink(target, rel string) {
	if err := os.Symlink(target, filepath.Join(tr.root, rel)); err != nil {
		tr.t.Fatal(err)
	}
}

// inodes maps the inode of every entry below base (not following links) to
// its slash path relative to base.
func inodes(t *testing.T, base string) map[uint64]string {
	out := map[uint64]string{}
	err := filepath.Walk(base, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(base, p)
		out[uint64(info.Sys().(*syscall.Stat_t).Ino)] = filepath.ToSlash(rel)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// run sweeps as if the agent uid were someone else, so every visited entry
// "needs" a chown, and returns the sorted chowned paths. Paths outside the
// checkouts directory are reported with an "outside:" prefix.
func (tr *tree) run(ops *recordingOps) ([]string, *sweeper) {
	s := &sweeper{ops: ops, uid: os.Getuid() + 1, gid: os.Getgid() + 1, logf: tr.t.Logf}
	if err := s.sweep(tr.root); err != nil {
		tr.t.Fatal(err)
	}
	in := inodes(tr.t, tr.root)
	out := inodes(tr.t, tr.outside)
	var paths []string
	for _, ino := range ops.chowned {
		switch {
		case in[ino] != "":
			paths = append(paths, in[ino])
		case out[ino] != "":
			paths = append(paths, "outside:"+out[ino])
		default:
			paths = append(paths, "unknown")
		}
	}
	sort.Strings(paths)
	return paths, s
}

func assertPaths(t *testing.T, got []string, want ...string) {
	t.Helper()
	sort.Strings(want)
	if len(got) != len(want) {
		t.Fatalf("chowned %q, want %q", got, want)
	}
	for i := range got {
		if got[i] != want[i] {
			t.Fatalf("chowned %q, want %q", got, want)
		}
	}
}

func TestNestedWorktreeEntriesAreChowned(t *testing.T) {
	tr := newTree(t)
	tr.file(filepath.Join(tr.root, "isac322/krema-worktrees/issue-7/target/debug/app"))
	tr.file(filepath.Join(tr.root, "isac322/krema-worktrees/issue-7/src/main.rs"))
	tr.dir("isac322/krema-worktrees/issue-8")
	ops := &recordingOps{}
	got, s := tr.run(ops)
	assertPaths(t, got,
		"isac322/krema-worktrees/issue-7",
		"isac322/krema-worktrees/issue-7/target",
		"isac322/krema-worktrees/issue-7/target/debug",
		"isac322/krema-worktrees/issue-7/target/debug/app",
		"isac322/krema-worktrees/issue-7/src",
		"isac322/krema-worktrees/issue-7/src/main.rs",
		"isac322/krema-worktrees/issue-8",
	)
	if s.changed != 7 || s.failed != 0 {
		t.Fatalf("changed=%d failed=%d", s.changed, s.failed)
	}
}

func TestEntriesAlreadyOwnedAreNotChowned(t *testing.T) {
	tr := newTree(t)
	tr.file(filepath.Join(tr.root, "isac322/krema-worktrees/issue-7/src/main.rs"))
	ops := &recordingOps{}
	s := &sweeper{ops: ops, uid: os.Getuid(), gid: os.Getgid(), logf: t.Logf}
	if err := s.sweep(tr.root); err != nil {
		t.Fatal(err)
	}
	if len(ops.chowned) != 0 || s.changed != 0 {
		t.Fatalf("chowned %d entries owned by the agent", len(ops.chowned))
	}
}

func TestNonWorktreeTopLevelDirsAreNotTouched(t *testing.T) {
	tr := newTree(t)
	tr.file(filepath.Join(tr.root, "isac322/krema/.git/HEAD"))
	tr.file(filepath.Join(tr.root, "isac322/krema/src/lib.rs"))
	tr.file(filepath.Join(tr.root, "isac322/notes/todo"))
	tr.file(filepath.Join(tr.root, ".issue-agent-janitor/status"))
	tr.file(filepath.Join(tr.root, ".hidden-worktrees/x/y"))
	tr.file(filepath.Join(tr.root, "isac322/-worktrees/x"))
	tr.file(filepath.Join(tr.root, "isac322/file-worktrees"))
	tr.file(filepath.Join(tr.root, "loose-file"))
	tr.file(filepath.Join(tr.root, "isac322/krema-worktrees/issue-7/a"))
	got, _ := tr.run(&recordingOps{})
	// The owner and <repo>-worktrees levels themselves are walked, not chowned.
	assertPaths(t, got, "isac322/krema-worktrees/issue-7", "isac322/krema-worktrees/issue-7/a")
}

func TestSymlinksAreChownedNotFollowed(t *testing.T) {
	tr := newTree(t)
	tr.dir("isac322/krema-worktrees/issue-7")
	tr.symlink(tr.outside, "isac322/krema-worktrees/issue-7/escape")
	tr.symlink(filepath.Join(tr.outside, "keep"), "isac322/krema-worktrees/issue-7/shadow")
	// A worktree that is itself a link, and links at the structural levels.
	tr.symlink(tr.outside, "isac322/krema-worktrees/issue-8")
	tr.symlink(tr.outside, "isac322/evil-worktrees")
	tr.symlink(tr.outside, "evil")
	got, _ := tr.run(&recordingOps{})
	assertPaths(t, got,
		"isac322/krema-worktrees/issue-7",
		"isac322/krema-worktrees/issue-7/escape",
		"isac322/krema-worktrees/issue-7/shadow",
		"isac322/krema-worktrees/issue-8",
	)
}

func TestDirectorySwappedForSymlinkAfterStatIsNotEntered(t *testing.T) {
	tr := newTree(t)
	tr.dir("isac322/krema-worktrees/issue-7")
	tr.symlink(tr.outside, "isac322/krema-worktrees/issue-7/candidate")
	// Pretend the stat saw a directory (the agent swaps it for a link
	// before the open): O_NOFOLLOW must refuse to open through the link.
	ops := &recordingOps{statOverride: map[string]func(entryStat) entryStat{
		"candidate": func(st entryStat) entryStat {
			st.Mode = st.Mode&^unix.S_IFMT | unix.S_IFDIR
			return st
		},
	}}
	got, s := tr.run(ops)
	assertPaths(t, got, "isac322/krema-worktrees/issue-7", "isac322/krema-worktrees/issue-7/candidate")
	if s.failed != 1 {
		t.Fatalf("failed=%d, want the refused open counted", s.failed)
	}
}

func TestOtherFilesystemsAreSkipped(t *testing.T) {
	tr := newTree(t)
	tr.file(filepath.Join(tr.root, "isac322/krema-worktrees/issue-7/mnt/inner"))
	tr.file(filepath.Join(tr.root, "isac322/krema-worktrees/issue-7/src/main.rs"))
	tr.file(filepath.Join(tr.root, "isac322/other-worktrees/issue-1/a"))
	tr.file(filepath.Join(tr.root, "mounted/krema-worktrees/issue-1/a"))
	otherDev := func(st entryStat) entryStat { st.Dev++; return st }
	ops := &recordingOps{statOverride: map[string]func(entryStat) entryStat{
		"mnt":             otherDev,
		"other-worktrees": otherDev,
		"mounted":         otherDev,
	}}
	got, _ := tr.run(ops)
	assertPaths(t, got,
		"isac322/krema-worktrees/issue-7",
		"isac322/krema-worktrees/issue-7/src",
		"isac322/krema-worktrees/issue-7/src/main.rs",
	)
}

func TestSymlinkedRootIsRefused(t *testing.T) {
	tr := newTree(t)
	link := filepath.Join(filepath.Dir(tr.root), "link")
	if err := os.Symlink(tr.root, link); err != nil {
		t.Fatal(err)
	}
	s := &sweeper{ops: &recordingOps{}, uid: 1, gid: 1, logf: t.Logf}
	if err := s.sweep(link); err == nil {
		t.Fatal("sweep followed a symlinked root")
	}
}
