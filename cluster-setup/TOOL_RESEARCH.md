# Ansible 대안 도구 조사: 선언적 클러스터 관리 도구 비교

## 목표

현재 Ansible로 구현된 클러스터 설정(k3s, WireGuard mesh, kubeconfig, OS 초기화, 방화벽, SSH hardening, ArgoCD)을 **전부 동일하게 유지**하면서, **더 선언적이고 현대적인 도구**로 전환할 수 있는지 조사한다.

---

## 현재 Ansible 구성 요약

### 관리 대상 노드

| 호스트 | 하드웨어 | 그룹 | 역할 |
|---|---|---|---|
| n2p1 | ODROID N2+ | backbone | k3s master, NFS storage |
| n2p2 | ODROID N2+ | backbone | k3s master, storage |
| rpi5 | Raspberry Pi 5 | backbone | k3s master, WG gateway |
| rock5bp | Rock 5B | backbone | k3s master |
| v1.bhyoo.com | Ubuntu VPS | prod | k3s master (단일 노드) |

### 핵심 상태 관리

| 구성 요소 | 상태/특징 | 복잡도 |
|---|---|---|
| **WireGuard mesh** | 노드별 private/public key, 노드쌍별 preshared key, 멀티그룹 mesh 토폴로지, edge client config 생성 | 매우 높음 |
| **k3s** | HA embedded etcd (backbone 4-master), 호스트별 node label/IP/flannel config | 높음 |
| **kubeconfig** | Ed25519 CSR → K8s API 제출 → 승인 → 인증서 다운로드 → kubeconfig 렌더링 | 중간 |
| **OS 초기화** | systemd-networkd 정적 IP, systemd-resolved, locale, 패키지 관리 | 중간 |
| **방화벽** | iptables 규칙 (K8s ports, WireGuard, NFS, mDNS 등) | 중간 |
| **SSH hardening** | 키 배포, 알고리즘 제한, devsec.hardening | 낮음 |
| **ArgoCD** | 멀티클러스터 등록 (prod→backbone via WireGuard), Terraform output 연동 | 중간 |

### 실행 순서 (Makefile)

```
ansible-install → init-backbone-os → etc-hosts → ssh-hardening → firewall → wireguard → k3s → argocd
```

---

## 도구별 상세 분석

### Tier 1: 강력 추천

---

### 1. Talos Linux

> OS 자체가 단일 YAML machine config로 정의되는 불변(immutable) Kubernetes 전용 OS. SSH 없음, 셸 없음, 패키지 매니저 없음.

**선언성:** 최상 + 불변. Configuration drift가 구조적으로 불가능.

**현재 Ansible 역할과의 매핑:**

| 현재 (Ansible) | Talos로 전환 시 |
|---|---|
| k3s 설치/설정 | 불필요 - Talos가 Kubernetes를 내장 제공 |
| WireGuard mesh (700줄+ 커스텀 role) | KubeSpan: `machine.network.kubespan.enabled: true` 한 줄로 전체 mesh 자동 구성 |
| kubeconfig 관리 | `talosctl kubeconfig`로 생성 |
| OS 초기화/패키지 | 불필요 - 불변 OS |
| iptables 방화벽 | machine config에서 선언적 네트워크 규칙 |
| SSH hardening | 불필요 - SSH 자체가 없음 |
| /etc/hosts | `machine.network.extraHostEntries` |
| ArgoCD | Helm chart via inline manifests 또는 별도 bootstrap |

**장점:**
- WireGuard mesh가 KubeSpan으로 완전 자동화 (키 생성, peer 발견, mesh 유지 전부 자동)
- Git에 machine config YAML만 버전 관리하면 됨
- 보안: mTLS 기반 API, 공격 표면 최소화
- 매우 활발한 개발: v1.12.2 (Kubernetes 1.35 포함, Linux 6.18.8)
- TalosCon 2025 개최, 커뮤니티 빠르게 성장 중

**단점:**
- k3s가 아닌 Talos의 Kubernetes 배포판 사용 (전환 필요)
- SSH가 없으므로 디버깅 시 `talosctl` 학습 필요
- ARM SBC 호환성 확인 필요 (ODROID N2+, Rock 5B에 system extension 필요 가능성)
- 범용 리눅스 기능(NFS 서버 등)은 Kubernetes Pod로 실행해야 함
- edge client WireGuard config 생성은 KubeSpan과 별도로 관리 필요

**학습 곡선:** 중간

**참고 자료:**
- https://www.talos.dev/
- https://www.talos.dev/v1.10/talos-guides/network/kubespan/
- https://robkenis.com/posts/k3s_to_talos/ (k3s → Talos 마이그레이션 사례)

---

### 2. NixOS + Colmena

> 전체 OS 상태(커널, 패키지, 서비스, 설정 파일)를 Nix 언어로 선언. 시스템이 원자적으로 해당 상태로 수렴.

**선언성:** 최상. Configuration drift가 설계상 불가능.

**현재 Ansible 역할과의 매핑:**

| 현재 (Ansible) | NixOS로 전환 시 |
|---|---|
| k3s 설치/설정 | `services.k3s.enable = true; services.k3s.role = "server";` |
| WireGuard mesh | `networking.wireguard.interfaces.wg0 = { privateKeyFile = ...; peers = [...]; };` |
| kubeconfig 관리 | activation script 또는 NixOS 모듈 |
| OS 초기화 | `environment.systemPackages`, `i18n.defaultLocale`, `time.timeZone` |
| iptables 방화벽 | `networking.firewall.allowedTCPPorts = [ 6443 ... ];` |
| SSH hardening | `services.openssh.settings = { ... };` |
| systemd-networkd | `systemd.network.networks."10-eth0" = { ... };` |
| ArgoCD | Helm chart via k3s 또는 별도 NixOS 모듈 |

**Colmena (멀티노드 배포 도구):**
```nix
# flake.nix
{
  colmena = {
    meta = { nixpkgs = ...; };
    n2p1 = { ... };    # backbone
    rpi5 = { ... };    # backbone + WG gateway
    v1 = { ... };      # prod
  };
}
# 배포: colmena apply --on @backbone
```

**시크릿 관리:**
- **agenix**: SSH 호스트 키로 age 암호화, activation 시 `/run/agenix`로 복호화
- **sops-nix**: Mozilla SOPS + age/GPG, 템플릿 지원
- WireGuard private key를 git repo에 암호화 저장, activation 시 복호화

**장점:**
- 모든 OS 구성이 하나의 코드로 표현됨
- Nix 언어의 함수형 특성으로 WireGuard mesh 토폴로지를 우아하게 표현 가능
- 원자적 롤백: 문제 발생 시 이전 세대로 즉시 복원
- Nixpkgs: 100,000+ 패키지
- 범용 Linux이므로 NFS 서버 등 모든 것 가능
- [nixos-k3s](https://github.com/niki-on-github/nixos-k3s): 이 유스케이스를 정확히 구현한 프로젝트 존재
- ARM 지원 우수 (NixOS on ARM은 잘 지원됨)

**단점:**
- 모든 노드에 NixOS 재설치 필수 (nixos-anywhere으로 원격 가능)
- 학습 곡선이 매우 높음 — Nix는 함수형 프로그래밍 언어
- Flakes, overlays, modules 등 에코시스템 개념이 많음
- Colmena는 0.4.x (안정적이나 1.0 미만)

**학습 곡선:** 높음

**참고 자료:**
- https://nixos.org/
- https://wiki.nixos.org/wiki/WireGuard
- https://nixos.wiki/wiki/K3s
- https://github.com/niki-on-github/nixos-k3s
- https://github.com/zhaofengli/colmena
- https://github.com/ryantm/agenix

---

### Tier 2: 실용적 대안

---

### 3. Salt (SaltStack) — masterless 모드

> State 시스템이 선언적 — 원하는 상태를 정의하면 Salt이 수렴시킴.

**선언성:** 높음. Ansible의 "task 순서대로 실행"과 달리 requisite 시스템(`require`, `watch`, `onchanges`)으로 의존성 선언.

```yaml
# Salt State 예시
wireguard:
  pkg.installed: []
  service.running:
    - watch:
      - file: /etc/wireguard/wg0.conf

/etc/wireguard/wg0.conf:
  file.managed:
    - source: salt://wireguard/wg0.conf.j2
    - template: jinja
    - require:
      - pkg: wireguard
```

**장점:**
- Ansible보다 확실히 더 선언적
- masterless 모드로 Salt master 없이 운영 가능
- Pillar로 시크릿 관리 내장
- 기존 OS 유지 가능 (재설치 불필요)
- [saltstack-kubernetes](https://github.com/fjudith/saltstack-kubernetes): Salt + WireGuard + K8s 조합 구현
- 최신 릴리즈: 3007.10

**단점:**
- Salt minion 에이전트를 모든 노드에 설치해야 함
- Broadcom 인수 후 오픈소스 방향성 불확실
- Ansible보다 무겁고 복잡한 운영 오버헤드
- 근본적으로는 여전히 "상태 수렴" 모델 (NixOS/Talos 수준의 선언성은 아님)

**학습 곡선:** 중간

---

### 4. Pyinfra

> Python으로 인프라를 코드로 관리. Ansible과 같은 idempotent 모델이되 YAML 대신 Python.

**선언성:** 중간 — 본질적으로 Ansible과 같은 수준. "순서대로 실행"하는 imperative 모델.

```python
from pyinfra.operations import apt, files, systemd

apt.packages(packages=["wireguard-tools"])
files.template(
    src="templates/wg0.conf.j2",
    dest="/etc/wireguard/wg0.conf",
)
systemd.service("wg-quick@wg0", running=True, enabled=True)
```

**장점:**
- Python으로 WireGuard mesh 키 생성 같은 복잡한 로직을 자연스럽게 표현
- 타겟에 Python 불필요 (POSIX shell만 필요)
- 기존 OS 유지 가능
- 활발한 개발 (v3.6.1, FOSDEM 2026 발표)

**단점:**
- Ansible보다 근본적으로 더 선언적이지 않음
- 전용 WireGuard/k3s 모듈 없음
- 시크릿 관리 없음
- 커뮤니티가 작음

**학습 곡선:** 낮음

---

### Tier 3: 이 유스케이스에 부적합

| 도구 | 부적합 이유 |
|---|---|
| **Pulumi** | 클라우드 리소스 프로비저닝 전용. 노드 설정은 Command provider(SSH 명령 실행)에 의존 → Ansible보다 나을 게 없음 |
| **Terraform / OpenTofu** | 동일. provisioner는 공식 문서에서 "최후의 수단"으로 명시. 노드 구성 관리에 설계상 부적합 |
| **Chef** | Chef Infra Server 2026.11 EOL. 상용 Chef 360으로 전환 중. 홈랩에 과도한 인프라 |
| **mgmt (mgmtconfig)** | 아키텍처는 우수(reactive, graph-based)하나 에코시스템이 너무 작음. WireGuard/k3s 모듈 전무 |
| **Sidero / Cluster API** | 클러스터 fleet 관리용. 4-5노드 홈랩에는 과잉. 관리 플레인 자체에 K8s 클러스터 필요 |

---

## 종합 비교표

| 기준 | Ansible (현재) | Talos Linux | NixOS+Colmena | Salt | Pyinfra |
|---|---|---|---|---|---|
| **선언성** | 낮음 (task 순서) | 최상 (불변 OS) | 최상 (함수형) | 높음 (State) | 중간 (idempotent) |
| **WireGuard mesh** | 700줄+ 커스텀 role | `enabled: true` 1줄 | 네이티브 모듈 | 수동 구현 | 수동 구현 |
| **k3s/K8s** | xanmanning.k3s role | 내장 K8s (k3s 아님) | `services.k3s` | 수동/formula | 수동 구현 |
| **OS 재설치 필요** | 아니오 | **예** | **예** | 아니오 | 아니오 |
| **시크릿 관리** | git-crypt + vars | mTLS + secrets.yaml | agenix / sops-nix | Pillar | 없음 |
| **롤백** | 없음 | machine config 교체 | 원자적 세대 롤백 | 없음 | 없음 |
| **Config drift** | 발생 가능 | 불가능 | 불가능 | 감지 가능 | 발생 가능 |
| **ARM SBC 지원** | 우수 | 확인 필요 | 우수 | 우수 | 우수 |
| **학습 곡선** | 기준 | 중간 | 높음 | 중간 | 낮음 |
| **커뮤니티** | 매우 큼 | 빠르게 성장 | 큼 | 큼 | 작음 |
| **최신 릴리즈** | - | v1.12.2 | 24.11 | 3007.10 | v3.6.1 |

---

## 결론

"더 선언적"이라는 목표를 진지하게 추구한다면, 진정으로 선언적인 도구는 **Talos Linux**과 **NixOS** 둘 뿐이다. Salt과 Pyinfra는 Ansible 대비 개선이 있지만 같은 패러다임이다.

- **유지보수 최소화, 가장 현대적:** Talos Linux — WireGuard mesh가 KubeSpan으로 완전 자동화, OS 관리 자체가 사라짐. ARM SBC 호환성 검증 선행 필요.
- **가장 유연하면서 진정 선언적:** NixOS + Colmena — 범용 Linux 유지하면서 모든 것을 선언적으로 관리. NFS 서버 등 K8s 외 워크로드 지원. Nix 학습 투자 필요.
- **최소 변경으로 점진적 개선:** Salt (masterless) 또는 Pyinfra — 기존 OS 유지, 점진적 전환. 패러다임 자체는 Ansible과 유사.
