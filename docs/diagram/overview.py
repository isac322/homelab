import importlib.resources

from diagrams import Cluster, Diagram, Edge
from diagrams.custom import Custom
from diagrams.k8s.infra import Master, Node
from diagrams.oci.security import Vault
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import User
from diagrams.onprem.iac import Terraform
from diagrams.onprem.vcs import Github

with Diagram('Overview', show=False):
    dns = Custom('Cloudflare DNS', icon_path=str(importlib.resources.path('assets', 'cloudflare-icon.png')))

    with Cluster('k8s Cluster - backbone'):
        backbone_masters = [Master(), Master(), Master()]
        backbone_workers = [Node(), Node()]
        backbone_masters[0] - dns

    admin = User('Admin')
    github_repo = Github('isac322/homelab')
    github_repo << Edge(label='GitOps') << [backbone_masters[0], admin]

    gha = GithubActions('Github Actions')
    secret_store = Vault('OCI Secret Store')
    github_repo - gha >> Terraform('Terraform Cloud') >> [dns, secret_store]
    secret_store << Edge(label='External Secrets') << backbone_masters[0]
