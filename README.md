# Isac's reproducible k8s homelab

**_Work In Progress_**

Kubernetes 클러스터 (재)생성이 가능한 THE BIG RED BUTTON을 목표로합니다.

![The Big Red Button](https://abisimanjuntak.files.wordpress.com/2013/12/day-of-the-doctor-trailer-seize-the-moment.jpg)


## System overview

![System Overview](docs/diagram/overview.png?raw=true "Overview")

## TODO list

- [ ] provisioning + k8s 설치 자동화
    - [x] backbone 클러스터
    - [ ] prod 클러스터
    - [ ] prod 클러스터의 노드들 LPG 대신 DRG로 피어링
    - [ ] prod와 backbone을 DRG의 site-to-site VPN으로 연결
    - [ ] backbone, prod 클러스터 각각 생성 이후에 argocd 연결 자동화
- [ ] 클러스터 운영 자동화 (k8s 설치 이후 모든 작업)
    - [x] backbone 클러스터
    - [ ] prod 클러스터
- [ ] Secret를 클러스터 외부로 분리
    - [x] backbone 클러스터에서 secret 추출
    - [ ] prod 클러스터에서 secret 추출
- [ ] 관리 도구들의 웹 UI를 VPN으로 숨기기
    - [x] ArgoCD
    - [ ] Rook
    - [ ] Grafana
    - [ ] InfluxDB
- [x] 외부 의존성 Terraforming
    - [x] Oracle Vault
    - [ ] Oracle Object Storage
    - [x] Cloudflare
- [ ] 문서 생성 자동화
- [ ] 모니터링 고도화
    - [ ] Mimir or Thanos
    - [ ] Loki
    - [ ] Alert 연동
    - [ ] 대시보드 추가
        - [x] Rook
        - [x] blocky
        - [ ] argocd
        - [ ] node
        - [ ] traefik
        - [ ] cert-manager
- [ ] k8s로 wireguard config 관리
- [ ] CI/CD
    - [ ] Chart 자동 업그레이드 파이프라인 구축
    - [x] Terraform Cloud 연동
    - [x] Publishing Helm Chart
    - [x] Dependabot
- [ ] 데이터
    - [ ] NAS에 클러스터 자동 백업
    - [ ] NAS에 Rook 데이터 자동 백업
    - [ ] NAS와 seamless한 k8s 연동 (?)