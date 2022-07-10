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

    with Cluster('k8s Cluster - prod'):
        prod_masters = [Master(), Master(), Master()]

        dns - prod_masters

    with Cluster('k8s Cluster - backbone'):
        backbone_master = Master()
        backbone_worker = Node()
        backbone_master - dns

    admin = User('Admin')
    admin >> Edge(label='TO BE DEPRECATED', style='dotted') >> prod_masters[0]
    github_repo = Github('isac322/homelab')
    github_repo << Edge(label='GitOps') << [backbone_master, admin]

    gha = GithubActions('Github Actions')
    secret_store = Vault('OCI Secret Store')
    github_repo - gha >> Terraform('Terraform Cloud') >> [dns, secret_store]
    secret_store << Edge(label='External Secrets') << [backbone_master, prod_masters[0]]
