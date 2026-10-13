// issue-agent-chown-sweep: root-side filesystem helper for dockerd-janitor in
// the issue-agent dockerd sidecar. Every operation is anchored to directory fds
// opened O_DIRECTORY|O_NOFOLLOW and names one path component at a time, so an
// agent that rewrites the (agent-writable) checkouts tree mid-walk cannot make
// root touch anything through a symlink.
//
// Usage (CHECKOUTS is normally /home/agent/checkouts):
//
//	issue-agent-chown-sweep sweep CHECKOUTS
//	    chown <owner>/<repo>-worktrees/<name>/** to 1000:1000 (same filesystem
//	    only, symlinks themselves); prints the number of entries changed.
//	issue-agent-chown-sweep status CHECKOUTS CHECKED_AT USED_PCT LAST_PRUNE_AT LAST_PRUNE_LEASE LAST_PRUNE_RESULT
//	    atomically write .issue-agent-janitor/status ("-" = null).
//	issue-agent-chown-sweep read-request CHECKOUTS
//	    print the prune request's lease_until. Exit 3: no request; exit 4:
//	    unusable request (drop it).
//	issue-agent-chown-sweep drop-request CHECKOUTS
//	    unlink .issue-agent-janitor/prune-request.
package main

import (
	"errors"
	"fmt"
	"log"
	"os"
)

const (
	agentUID = 1000
	agentGID = 1000

	exitError   = 1
	exitAbsent  = 3
	exitInvalid = 4
	exitUsage   = 64
)

func main() {
	log.SetFlags(0)
	log.SetPrefix("issue-agent-chown-sweep: ")
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	if len(args) < 2 {
		log.Print("usage: issue-agent-chown-sweep sweep|status|read-request|drop-request CHECKOUTS [...]")
		return exitUsage
	}
	cmd, checkouts, rest := args[0], args[1], args[2:]
	files := janitorFiles{checkouts: checkouts, uid: agentUID, gid: agentGID}
	switch {
	case cmd == "sweep" && len(rest) == 0:
		s := &sweeper{ops: sysOps{}, uid: agentUID, gid: agentGID, logf: log.Printf}
		if err := s.sweep(checkouts); err != nil {
			log.Print(err)
			return exitError
		}
		fmt.Println(s.changed)
		if s.failed > 0 {
			log.Printf("%d entries skipped after errors", s.failed)
		}
		return 0
	case cmd == "status":
		st, err := parseStatusArgs(rest)
		if err != nil {
			log.Print(err)
			return exitUsage
		}
		if err := files.writeStatus(st); err != nil {
			log.Print(err)
			return exitError
		}
		return 0
	case cmd == "read-request" && len(rest) == 0:
		req, err := files.readRequest()
		switch {
		case err == nil:
			fmt.Println(req.LeaseUntil)
			return 0
		case errors.Is(err, errAbsent):
			return exitAbsent
		case errors.Is(err, errInvalid):
			log.Print(err)
			return exitInvalid
		default:
			log.Print(err)
			return exitError
		}
	case cmd == "drop-request" && len(rest) == 0:
		if err := files.dropRequest(); err != nil {
			log.Print(err)
			return exitError
		}
		return 0
	}
	log.Printf("unknown command or arguments: %q", args)
	return exitUsage
}
