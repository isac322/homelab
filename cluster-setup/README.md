# Legacy Ansible host bootstrap

이 디렉터리는 아직 전환하지 않은 `[ansible_managed]` 호스트의 bootstrap과
Nix 전환 전 동작을 확인하는 rollback 기준으로 유지한다. Legacy host-management
playbook은 `[ansible_managed]`만 target으로 삼고, `[nix_managed]` 호스트에는 SSH
연결이나 remote task를 실행하지 않는다. 두 ownership group은 `homelab`의
child로 남으며 `backbone` 같은 topology group도 유지한다.

`etc-hosts.yaml`은 모든 Ansible-managed host가 포함된 실행만 허용하고 `--limit`을
거부한다. Managed host 하나라도 fact gathering에 실패하면 어떤 `/etc/hosts`도
쓰기 전에 전체 play를 중단한다. Nix-managed host entry는 연결이나 facts 없이
inventory의 `[nix_managed]`와 `ansible_host`에서 `hosts_dns_hostname`으로 정적으로
추가한다.

부분 전환 이후 legacy `wireguard.yaml`은 fact gathering이나 remote mutation 전에
fail closed한다. 이 role은 Nix host의 encrypted identity와 PSK를 안전하게 읽을 수
없다. Peer 변경은 다음 명령으로 수행한다.

```bash
nix run .#rollout-peers -- <host>
```

## 준비물

Ubuntu가 설치된 기기가 필요하며 IP로 SSH 접근이 가능해야 한다.
`inventory/hosts`의 `[ansible_managed]`에 호스트를 추가하고,
`inventory/host_vars/<host>.yaml`에 접속 및 legacy desired-state 변수를 선언한다.

## 관리 범위

- locale과 static IP
- legacy WireGuard mesh
- admin 사용자와 SSH
- NetworkManager에서 systemd-networkd로 전환
- legacy K3s 설치