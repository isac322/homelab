##@ General

# The help target prints out all targets with their descriptions organized
# beneath their categories. The categories are represented by '##@' and the
# target descriptions by '##'. The awk commands is responsible for reading the
# entire set of makefiles included in this invocation, looking for lines of the
# file as xyz: ## something, and then pretty-format the target and help. Then,
# if there's a line with ##@ something, that gets pretty-printed as a category.
# More info on the usage of ANSI control characters for terminal formatting:
# https://en.wikipedia.org/wiki/ANSI_escape_code#SGR_parameters
# More info on the awk command:
# http://linuxcommand.org/lc3_adv_awk.php

.PHONY: help ansible-install init-backbone-os etc-hosts ssh-hardening firewall k3s argocd

help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

ansible-install: requirements.yaml
	ansible-galaxy install --force -r requirements.yaml

init-backbone-os: ansible-install init-backbone-os.yaml
	ansible-playbook $@.yaml

etc-hosts: init-backbone-os etc-hosts.yaml
	ansible-playbook $@.yaml

ssh-hardening: init-backbone-os ssh-hardening.yaml
	ansible-playbook $@.yaml

firewall: init-backbone-os firewall.yaml
	ansible-playbook $@.yaml

wireguard: firewall wireguard.yaml
	ansible-playbook $@.yaml

k3s: etc-hosts ssh-hardening firewall wireguard k3s.yaml
	ansible-playbook $@.yaml

argocd: k3s argocd.yaml
	ansible-playbook $@.yaml
