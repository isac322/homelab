# Legacy Ansible host bootstrap

이 디렉터리는 아직 전환하지 않은 `[ansible_managed]` 호스트의 bootstrap과
Nix 전환 전 동작을 확인하는 rollback 기준으로만 유지한다.
`[nix_managed]`에 있는 호스트는 어떤 operational playbook도 대상으로 삼지 않는다.

호스트 전환 시 `inventory/hosts`에서 해당 호스트를 `[ansible_managed]`에서
`[nix_managed]`로 옮긴다. `backbone` membership은 cluster topology 참조이므로
그대로 유지한다. 현재 `n2p1`과 `n2p2`는 Nix가 관리한다.

부분 전환 이후 legacy `wireguard.yaml`은 fail closed한다. 이 role은 play 대상에서
제외된 Nix 호스트의 encrypted identity와 PSK를 안전하게 읽을 수 없으므로,
남은 호스트만 대상으로 실행하면 peer를 누락한다. Peer 변경은 다음 명령으로
수행한다.

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