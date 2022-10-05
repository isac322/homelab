# Bootstrap backbone cluster

Ansible을 활용하여 Kubernetes cluster 구성

## 준비물

Ubuntu가 설치된 기기가 필요함. IP로 ssh 접근이 가능해야함.
[hosts](./inventory/hosts) 파일에 기기 별칭을 `k8s_cluster`에 넣어놓고,
[n1p1.yaml](./inventory/host_vars/n2p1.yaml), [n1p2.yaml](./inventory/host_vars/n2p2.yaml) 처럼 각 호스트의 IP, ssh 접속 정보 등을
적어야함.

|        변수        | 설명                                                                                                                                                                               |
|:----------------:|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|   ansible_host   | ansible이 실행을 위해 해당 노드에 접속할 때 사용될 IP [공식문서](https://docs.ansible.com/ansible/latest/user_guide/intro_inventory.html#connecting-to-hosts-behavioral-inventory-parameters) 참고       |
|   ansible_user   | ansible이 실행을 위해 해당 노드에 접속할 때 사용될 username [공식문서](https://docs.ansible.com/ansible/latest/user_guide/intro_inventory.html#connecting-to-hosts-behavioral-inventory-parameters) 참고 |
| ansible_password | ansible이 실행을 위해 해당 노드에 접속할 때 사용될 비밀번호 [공식문서](https://docs.ansible.com/ansible/latest/user_guide/intro_inventory.html#connecting-to-hosts-behavioral-inventory-parameters) 참고     |
|    desired_ip    | 이 노드가 할당받고 싶은 Static IP                                                                                                                                                          |
|    gateway_ip    | 이 노드가 Static IP를 할당 받을 떄 사용될 gateway IP                                                                                                                                          |
|      vpn_ip      | Wireguard로 클러스터 VPN을 구축할 때 이 노드가 할당받을 IP                                                                                                                                         |

## 하는 일

- locale 설정
- Static IP 할당
- Wiregaurd로 VPN 구축
- admin 유저 생성
- NetworkManager 삭제 후 systemd-networkd 사용
- k3s 설치