// storage-canary detects silent data corruption on the write path of a
// storage stack (isac322/homelab#385).
//
// It downloads Thanos chunk objects with objstore.DownloadFile (the
// compactor's code path) into one or more destination directories, fsyncs,
// re-reads every file with O_DIRECT and compares its sha256 with a manifest
// built from two independent S3 reads. On a mismatch it re-reads the file,
// re-fetches the object, records every differing byte range and keeps a
// 1 MiB window of both copies as evidence.
//
// Modes:
//
//	select  build a manifest file from the newest live Thanos blocks
//	run     experiment: verify a manifest on several arms up to a GiB target
//	canary  continuous: select in memory, verify one arm forever, re-select
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"github.com/go-kit/log"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/thanos-io/objstore"
	"github.com/thanos-io/objstore/client"
	"golang.org/x/sys/unix"
	"golang.org/x/time/rate"
)

const (
	stageSelect   = "select"
	stageDownload = "download"
	stageFsync    = "fsync"
	stageVerify   = "verify"

	// maxEvidenceBytes bounds the evidence directory; above it only JSON
	// reports are written, no byte windows.
	maxEvidenceBytes = 512 << 20
	maxWindows       = 8
)

type entry struct {
	Name string `json:"name"`
	Size int64  `json:"size"`
	Sum  string `json:"sha256"`
}

var out = slog.New(slog.NewJSONHandler(os.Stdout, nil))

var (
	verifiedBytes = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "storage_canary_verified_bytes_total",
		Help: "Bytes written and verified by an O_DIRECT re-read.",
	}, []string{"arm"})
	iterations = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "storage_canary_iterations_total",
		Help: "Completed write/verify iterations by result (ok|mismatch).",
	}, []string{"arm", "result"})
	stageErrors = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "storage_canary_errors_total",
		Help: "Iteration errors by stage (select|download|fsync|verify).",
	}, []string{"arm", "stage"})
	lastVerified = prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Name: "storage_canary_last_verified_timestamp_seconds",
		Help: "Unix time of the last successful verification.",
	}, []string{"arm"})
	lastMismatch = prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Name: "storage_canary_last_mismatch_timestamp_seconds",
		Help: "Unix time of the last checksum mismatch.",
	}, []string{"arm"})
	sourceObjects = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "storage_canary_source_objects",
		Help: "Number of source objects currently selected.",
	})
)

func main() {
	cfg := flag.String("objstore", "", "objstore.yml path")
	manifest := flag.String("manifest", "manifest.json", "select/run: manifest path")
	mode := flag.String("mode", "run", "select|run|canary")
	count := flag.Int("count", 24, "select: number of objects")
	objects := flag.Int("objects", 6, "canary: number of objects")
	minSize := flag.Int64("min-size", 256<<20, "select/canary: minimum object size in bytes")
	arms := flag.String("arms", "", "run: name=dir,name=dir")
	armName := flag.String("arm", "", "canary: arm name")
	dir := flag.String("dir", "", "canary: work directory on the storage under test")
	mbps := flag.Float64("mbps", 20, "run/canary: per-arm MB/s cap, shared by download and verify read")
	targetGiB := flag.Float64("target-gib", 450, "run: verified GiB per arm before stopping (0 = forever)")
	evidence := flag.String("evidence", "evidence", "run/canary: evidence directory")
	reselect := flag.Duration("reselect", 6*time.Hour, "canary: re-select source objects this often")
	listen := flag.String("listen", "", "metrics listen address (canary default :9090)")
	flag.Parse()

	if *mode == "canary" {
		if *listen == "" {
			*listen = ":9090"
		}
		if *armName == "" || *dir == "" {
			must(errors.New("canary mode needs -arm and -dir"))
		}
	}

	conf, err := os.ReadFile(*cfg)
	must(err)
	bkt, err := client.NewBucket(log.NewNopLogger(), conf, "storage-canary", nil)
	must(err)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if *listen != "" {
		serveMetrics(*listen)
	}

	switch *mode {
	case "select":
		picked, err := selectObjects(ctx, bkt, *count, *minSize, nil, nil)
		must(err)
		b, _ := json.MarshalIndent(picked, "", "  ")
		must(os.WriteFile(*manifest, b, 0o644))
	case "run":
		var m []entry
		b, err := os.ReadFile(*manifest)
		must(err)
		must(json.Unmarshal(b, &m))
		if len(m) == 0 {
			must(fmt.Errorf("manifest %s is empty", *manifest))
		}
		sourceObjects.Set(float64(len(m)))
		must(os.MkdirAll(*evidence, 0o755))
		var wg sync.WaitGroup
		for i, spec := range strings.Split(*arms, ",") {
			name, d, ok := strings.Cut(spec, "=")
			if !ok {
				must(fmt.Errorf("bad arm %q", spec))
			}
			a := newArm(bkt, name, d, *evidence, *mbps)
			wg.Go(func() { a.runFixed(ctx, m, i, *targetGiB) })
		}
		wg.Wait()
	case "canary":
		must(os.MkdirAll(*evidence, 0o755))
		must(cleanDir(*dir))
		a := newArm(bkt, *armName, *dir, *evidence, *mbps)
		a.runCanary(ctx, *objects, *minSize, *reselect)
	default:
		must(fmt.Errorf("unknown mode %q", *mode))
	}
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "storage-canary:", err)
		os.Exit(1)
	}
}

func serveMetrics(addr string) {
	reg := prometheus.NewRegistry()
	reg.MustRegister(
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
		verifiedBytes, iterations, stageErrors, lastVerified, lastMismatch, sourceObjects,
	)
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{Registry: reg}))
	srv := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	go func() { must(srv.ListenAndServe()) }()
}

// cleanDir creates dir and removes leftovers of a previous process inside it.
func cleanDir(dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	ents, err := os.ReadDir(dir)
	if err != nil {
		return err
	}
	for _, e := range ents {
		if err := os.RemoveAll(filepath.Join(dir, e.Name())); err != nil {
			return err
		}
	}
	return nil
}

func sleep(ctx context.Context, d time.Duration) {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
	case <-t.C:
	}
}

// selectObjects picks chunk segments from the newest blocks that are neither
// marked for deletion nor excluded from compaction, and hashes each one twice
// from S3. Objects already in known with the same size are reused without
// re-hashing (Thanos objects are immutable). lim (may be nil) caps the
// hashing reads.
func selectObjects(ctx context.Context, bkt objstore.Bucket, count int, minSize int64, lim *rate.Limiter, known map[string]entry) ([]entry, error) {
	var blocks []string
	if err := bkt.Iter(ctx, "", func(n string) error {
		if strings.HasSuffix(n, "/") && len(n) == 27 {
			blocks = append(blocks, n)
		}
		return nil
	}); err != nil {
		return nil, err
	}
	sort.Sort(sort.Reverse(sort.StringSlice(blocks)))
	var picked []entry
	for _, b := range blocks {
		if len(picked) >= count {
			break
		}
		if ok, err := bkt.Exists(ctx, b+"deletion-mark.json"); err != nil || ok {
			continue
		}
		if ok, err := bkt.Exists(ctx, b+"no-compact-mark.json"); err != nil || ok {
			continue
		}
		err := bkt.Iter(ctx, b+"chunks/", func(n string) error {
			if len(picked) >= count {
				return nil
			}
			a, err := bkt.Attributes(ctx, n)
			if bkt.IsObjNotFoundErr(err) {
				return nil
			}
			if err != nil || a.Size < minSize {
				return err
			}
			if k, ok := known[n]; ok && k.Size == a.Size {
				picked = append(picked, k)
				return nil
			}
			s1, err := hashObject(ctx, bkt, n, lim)
			if bkt.IsObjNotFoundErr(err) {
				return nil
			}
			if err != nil {
				return err
			}
			s2, err := hashObject(ctx, bkt, n, lim)
			if bkt.IsObjNotFoundErr(err) {
				return nil
			}
			if err != nil {
				return err
			}
			if s1 != s2 {
				out.Warn("source unstable, skipped", "object", n)
				return nil
			}
			picked = append(picked, entry{n, a.Size, s1})
			out.Info("selected", "object", n, "size", a.Size)
			return nil
		})
		if err != nil {
			return nil, err
		}
	}
	return picked, nil
}

func hashObject(ctx context.Context, bkt objstore.Bucket, name string, lim *rate.Limiter) (string, error) {
	rc, err := bkt.Get(ctx, name)
	if err != nil {
		return "", err
	}
	defer rc.Close()
	h := sha256.New()
	if _, err := io.Copy(h, limited(ctx, rc, lim)); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

type limReader struct {
	ctx context.Context
	r   io.Reader
	lim *rate.Limiter
}

func (l limReader) Read(p []byte) (int, error) {
	if len(p) > l.lim.Burst() {
		p = p[:l.lim.Burst()]
	}
	n, err := l.r.Read(p)
	if n > 0 {
		if werr := l.lim.WaitN(l.ctx, n); werr != nil {
			return n, werr
		}
	}
	return n, err
}

func limited(ctx context.Context, r io.Reader, lim *rate.Limiter) io.Reader {
	if lim == nil {
		return r
	}
	return limReader{ctx, r, lim}
}

// limBucket rate-limits Get so objstore.DownloadFile is used unchanged.
type limBucket struct {
	objstore.Bucket
	lim *rate.Limiter
}

type limReadCloser struct {
	io.Reader
	io.Closer
}

func (b limBucket) Get(ctx context.Context, name string) (io.ReadCloser, error) {
	rc, err := b.Bucket.Get(ctx, name)
	if err != nil {
		return nil, err
	}
	return limReadCloser{limited(ctx, rc, b.lim), rc}, nil
}

// arm is one destination directory on the storage path under test.
type arm struct {
	bkt      objstore.Bucket
	lb       limBucket
	lim      *rate.Limiter
	name     string
	dir      string
	evidence string
	verified int64
	start    time.Time
}

func newArm(bkt objstore.Bucket, name, dir, evidence string, mbps float64) *arm {
	lim := rate.NewLimiter(rate.Limit(mbps*1e6), 1<<20)
	verifiedBytes.WithLabelValues(name)
	for _, r := range []string{"ok", "mismatch"} {
		iterations.WithLabelValues(name, r)
	}
	for _, s := range []string{stageSelect, stageDownload, stageFsync, stageVerify} {
		stageErrors.WithLabelValues(name, s)
	}
	return &arm{bkt: bkt, lb: limBucket{bkt, lim}, lim: lim, name: name, dir: dir, evidence: evidence, start: time.Now()}
}

// iterError is a failed iteration and the stage it failed in.
type iterError struct {
	stage string
	err   error
}

func (e *iterError) Error() string { return e.stage + ": " + e.err.Error() }
func (e *iterError) Unwrap() error { return e.err }

// Cause lets objstore's IsObjNotFoundErr (github.com/pkg/errors.Cause) see
// the provider error.
func (e *iterError) Cause() error { return e.err }

// iterate writes e into <dir>/<iter>/, verifies it and removes the directory.
func (a *arm) iterate(ctx context.Context, iter int, e entry) error {
	dst := filepath.Join(a.dir, strconv.Itoa(iter))
	defer os.RemoveAll(dst)
	if err := os.MkdirAll(dst, 0o755); err != nil {
		return &iterError{stageDownload, err}
	}
	file := filepath.Join(dst, path.Base(e.Name))
	t0 := time.Now()
	if err := objstore.DownloadFile(ctx, log.NewNopLogger(), a.lb, e.Name, file); err != nil {
		return &iterError{stageDownload, err}
	}
	if err := syncAndDrop(file); err != nil {
		return &iterError{stageFsync, err}
	}
	sum, err := directHash(ctx, file, a.lim)
	if err != nil {
		return &iterError{stageVerify, err}
	}
	a.verified += e.Size
	verifiedBytes.WithLabelValues(a.name).Add(float64(e.Size))
	ok := sum == e.Sum
	out.Info("iteration", "arm", a.name, "iter", iter, "object", e.Name, "ok", ok,
		"secs", time.Since(t0).Seconds(), "verified_gib", float64(a.verified)/(1<<30),
		"elapsed_h", time.Since(a.start).Hours())
	if ok {
		iterations.WithLabelValues(a.name, "ok").Inc()
		lastVerified.WithLabelValues(a.name).SetToCurrentTime()
		return nil
	}
	iterations.WithLabelValues(a.name, "mismatch").Inc()
	lastMismatch.WithLabelValues(a.name).SetToCurrentTime()
	a.investigate(ctx, e, iter, file, sum)
	return nil
}

func (a *arm) countError(err error) string {
	var ie *iterError
	stage := stageDownload
	if errors.As(err, &ie) {
		stage = ie.stage
	}
	stageErrors.WithLabelValues(a.name, stage).Inc()
	out.Error(stage, "arm", a.name, "err", err)
	return stage
}

// runFixed is the experiment loop: it cycles over m until targetGiB is
// verified (0 = forever). Download errors are retried, fsync and verify
// errors stop the arm.
func (a *arm) runFixed(ctx context.Context, m []entry, offset int, targetGiB float64) {
	for iter := 0; ctx.Err() == nil && (targetGiB == 0 || float64(a.verified) < targetGiB*(1<<30)); iter++ {
		e := m[(iter+offset*len(m)/2)%len(m)]
		err := a.iterate(ctx, iter, e)
		if err == nil || ctx.Err() != nil {
			continue
		}
		if a.countError(err) != stageDownload {
			return
		}
		sleep(ctx, 10*time.Second)
	}
	out.Info("arm done", "arm", a.name, "verified_gib", float64(a.verified)/(1<<30))
}

// runCanary loops forever over an in-memory selection that is refreshed every
// reselect and as soon as a selected object disappears from the bucket.
func (a *arm) runCanary(ctx context.Context, count int, minSize int64, reselect time.Duration) {
	var m []entry
	var selectedAt time.Time
	for iter := 0; ctx.Err() == nil; {
		if len(m) == 0 || time.Since(selectedAt) >= reselect {
			known := make(map[string]entry, len(m))
			for _, e := range m {
				known[e.Name] = e
			}
			picked, err := selectObjects(ctx, a.bkt, count, minSize, a.lim, known)
			if ctx.Err() != nil {
				break
			}
			switch {
			case err == nil && len(picked) > 0:
				m = picked
				out.Info("selection", "arm", a.name, "objects", len(m))
			case err == nil:
				err = errors.New("no eligible objects")
				fallthrough
			default:
				stageErrors.WithLabelValues(a.name, stageSelect).Inc()
				out.Error(stageSelect, "arm", a.name, "err", err, "kept_objects", len(m))
			}
			selectedAt = time.Now()
			sourceObjects.Set(float64(len(m)))
			if len(m) == 0 {
				sleep(ctx, 5*time.Minute)
				continue
			}
		}
		e := m[iter%len(m)]
		err := a.iterate(ctx, iter, e)
		iter++
		if err == nil || ctx.Err() != nil {
			continue
		}
		a.countError(err)
		if a.bkt.IsObjNotFoundErr(err) {
			// Compaction removed the block: drop the object and re-select now.
			m = slicesDelete(m, e.Name)
			sourceObjects.Set(float64(len(m)))
			selectedAt = time.Time{}
			continue
		}
		sleep(ctx, 30*time.Second)
	}
	out.Info("canary stopped", "arm", a.name, "verified_gib", float64(a.verified)/(1<<30))
}

func slicesDelete(m []entry, name string) []entry {
	var kept []entry
	for _, e := range m {
		if e.Name != name {
			kept = append(kept, e)
		}
	}
	return kept
}

func syncAndDrop(file string) error {
	f, err := os.Open(file)
	if err != nil {
		return err
	}
	defer f.Close()
	if err := f.Sync(); err != nil {
		return err
	}
	return unix.Fadvise(int(f.Fd()), 0, 0, unix.FADV_DONTNEED)
}

func alignedBuf(n int) []byte {
	b := make([]byte, n+4096)
	off := int(uintptr(unsafe.Pointer(&b[0])) & 4095)
	if off != 0 {
		off = 4096 - off
	}
	return b[off : off+n]
}

// directReader reads a file with O_DIRECT into an aligned buffer.
type directReader struct {
	f   *os.File
	buf []byte
	r   []byte
}

func openDirect(file string) (*directReader, error) {
	fd, err := syscall.Open(file, syscall.O_RDONLY|syscall.O_DIRECT, 0)
	if err != nil {
		return nil, err
	}
	return &directReader{f: os.NewFile(uintptr(fd), file), buf: alignedBuf(1 << 20)}, nil
}

func (d *directReader) Read(p []byte) (int, error) {
	if len(d.r) == 0 {
		n, err := d.f.Read(d.buf)
		if n == 0 {
			if err == nil {
				err = io.EOF
			}
			return 0, err
		}
		d.r = d.buf[:n]
	}
	n := copy(p, d.r)
	d.r = d.r[n:]
	return n, nil
}

func directHash(ctx context.Context, file string, lim *rate.Limiter) (string, error) {
	d, err := openDirect(file)
	if err != nil {
		return "", err
	}
	defer d.f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, limited(ctx, d, lim)); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

type diffRange struct {
	Offset int64  `json:"offset"`
	Len    int    `json:"len"`
	Source string `json:"source"`
	Local  string `json:"local"`
}

func (a *arm) investigate(ctx context.Context, e entry, iter int, file, firstSum string) {
	second, err := directHash(ctx, file, nil)
	if err != nil {
		out.Error("investigate reread", "arm", a.name, "err", err)
	}
	fresh, err := hashObject(ctx, a.bkt, e.Name, nil)
	if err != nil {
		out.Error("investigate refetch", "arm", a.name, "err", err)
	}
	var ranges []diffRange
	if rc, err := a.bkt.Get(ctx, e.Name); err != nil {
		out.Error("investigate get", "arm", a.name, "err", err)
	} else {
		if d, err := openDirect(file); err != nil {
			out.Error("investigate open", "arm", a.name, "err", err)
		} else {
			ranges, err = diff(rc, d)
			if err != nil && !errors.Is(err, io.EOF) {
				out.Error("investigate diff", "arm", a.name, "err", err)
			}
			d.f.Close()
		}
		rc.Close()
	}
	now := time.Now().UTC()
	tag := fmt.Sprintf("%s-%s-%d-%s", now.Format("20060102T150405Z"), a.name, iter, strings.ReplaceAll(e.Name, "/", "_"))
	windows := dirSize(a.evidence) < maxEvidenceBytes
	if windows {
		for _, r := range ranges[:min(len(ranges), maxWindows)] {
			saveWindow(ctx, a.bkt, e.Name, file, r.Offset, filepath.Join(a.evidence, fmt.Sprintf("%s-%d", tag, r.Offset)))
		}
	}
	mnt := mountOf(a.dir)
	report := filepath.Join(a.evidence, tag+".json")
	b, _ := json.MarshalIndent(map[string]any{
		"arm": a.name, "iter": iter, "object": e.Name, "manifest": e.Sum,
		"first_read": firstSum, "second_read": second, "fresh_s3": fresh,
		"persistent": second == firstSum, "source_ok": fresh == e.Sum,
		"ranges": ranges, "windows_saved": windows, "time": now,
		"node": os.Getenv("NODE_NAME"), "pod": os.Getenv("POD_NAME"), "kernel": kernelRelease(),
		"mount_point": mnt.point, "mount_source": mnt.source, "mount_fstype": mnt.fstype,
	}, "", "  ")
	if err := os.WriteFile(report, b, 0o644); err != nil {
		out.Error("investigate report", "arm", a.name, "err", err)
	}
	out.Warn("MISMATCH", "arm", a.name, "iter", iter, "object", e.Name, "ranges", len(ranges),
		"persistent", second == firstSum, "source_ok", fresh == e.Sum, "report", report,
		"mount_source", mnt.source, "mount_fstype", mnt.fstype)
}

func diff(a, b io.Reader) ([]diffRange, error) {
	ba, bb := make([]byte, 1<<20), make([]byte, 1<<20)
	var off int64
	var ranges []diffRange
	var cur *diffRange
	for {
		na, ea := io.ReadFull(a, ba)
		nb, eb := io.ReadFull(b, bb)
		n := min(na, nb)
		for i := range n {
			if ba[i] != bb[i] {
				if cur != nil && off+int64(i) <= cur.Offset+int64(cur.Len)+16 {
					cur.Len = int(off + int64(i) - cur.Offset + 1)
				} else {
					ranges = append(ranges, diffRange{Offset: off + int64(i), Len: 1})
					cur = &ranges[len(ranges)-1]
				}
			}
		}
		for i := range ranges {
			r := &ranges[i]
			if r.Source == "" && r.Offset >= off && r.Offset+int64(r.Len) <= off+int64(n) {
				lo := r.Offset - off
				r.Source = hex.EncodeToString(ba[lo : lo+int64(r.Len)])
				r.Local = hex.EncodeToString(bb[lo : lo+int64(r.Len)])
			}
		}
		off += int64(n)
		if ea != nil || eb != nil || na != nb {
			if na != nb {
				return ranges, fmt.Errorf("length differs at %d", off)
			}
			return ranges, io.EOF
		}
	}
}

func saveWindow(ctx context.Context, bkt objstore.Bucket, name, file string, at int64, prefix string) {
	start := max(0, (at-(512<<10))&^4095)
	const n = 1 << 20
	if rc, err := bkt.GetRange(ctx, name, start, n); err == nil {
		b, _ := io.ReadAll(rc)
		rc.Close()
		_ = os.WriteFile(fmt.Sprintf("%s-src-%d.bin", prefix, start), b, 0o644)
	}
	if d, err := openDirect(file); err == nil {
		if _, err := d.f.Seek(start, io.SeekStart); err == nil {
			var buf bytes.Buffer
			_, _ = io.CopyN(&buf, d, n)
			_ = os.WriteFile(fmt.Sprintf("%s-local-%d.bin", prefix, start), buf.Bytes(), 0o644)
		}
		d.f.Close()
	}
}

func dirSize(dir string) int64 {
	var total int64
	_ = filepath.WalkDir(dir, func(_ string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if info, err := d.Info(); err == nil && d.Type().IsRegular() {
			total += info.Size()
		}
		return nil
	})
	return total
}

func kernelRelease() string {
	var u unix.Utsname
	if err := unix.Uname(&u); err != nil {
		return ""
	}
	return unix.ByteSliceToString(u.Release[:])
}

type mount struct{ point, source, fstype string }

// mountOf returns the /proc/self/mountinfo entry with the longest mount
// point containing dir.
func mountOf(dir string) mount {
	abs, err := filepath.Abs(dir)
	if err != nil {
		return mount{}
	}
	if r, err := filepath.EvalSymlinks(abs); err == nil {
		abs = r
	}
	b, err := os.ReadFile("/proc/self/mountinfo")
	if err != nil {
		return mount{}
	}
	var best mount
	for line := range strings.Lines(string(b)) {
		// id parent major:minor root mountpoint opts [optional...] - fstype source superopts
		pre, post, ok := strings.Cut(strings.TrimSpace(line), " - ")
		if !ok {
			continue
		}
		f, g := strings.Fields(pre), strings.Fields(post)
		if len(f) < 5 || len(g) < 2 {
			continue
		}
		p := unescapeMount(f[4])
		if !within(abs, p) || len(p) < len(best.point) {
			continue
		}
		best = mount{point: p, source: unescapeMount(g[1]), fstype: g[0]}
	}
	return best
}

func within(dir, mnt string) bool {
	return mnt == "/" || dir == mnt || strings.HasPrefix(dir, mnt+"/")
}

// unescapeMount decodes the \ooo octal escapes used in mountinfo.
func unescapeMount(s string) string {
	if !strings.Contains(s, `\`) {
		return s
	}
	var sb strings.Builder
	// Classic loop: the body skips the three escape digits.
	for i := 0; i < len(s); i++ {
		if s[i] == '\\' && i+3 < len(s) {
			if v, err := strconv.ParseUint(s[i+1:i+4], 8, 8); err == nil {
				sb.WriteByte(byte(v))
				i += 3
				continue
			}
		}
		sb.WriteByte(s[i])
	}
	return sb.String()
}
