.PHONY: help bootstrap-backbone

CONTEXT := $(shell kubectl config view -o jsonpath='{.current-context}')

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

help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)


##@ Boostrap

bootstrap:  ## Bootstrap given cluster onto current kubectl context. (Possible CLUSTER_NAME: backbone, prod)
	@test -r 'values/argocd/$(CLUSTER_NAME).yml' || (echo 'Specify valid cluster name via CLUSTER_NAME'; exit 1)
	@echo 'bootstrap $(CLUSTER_NAME) cluster for context: "$(CONTEXT)"'
	@while [ -z "$$CONTINUE" ]; do \
		read -r -p "Type anything but Y or y to exit. [y/N]: " CONTINUE; \
	done ; \
	[ $$CONTINUE = "y" ] || [ $$CONTINUE = "Y" ] || (echo "Exiting."; exit 1;)

	# provision via terraform and install the secrets to cluster
	make -C terraform/$(CLUSTER_NAME) apply
	make -C terraform/$(CLUSTER_NAME) cluster-secrets DEST=/tmp/cluster-secrets.yaml

	helm repo add argo https://argoproj.github.io/argo-helm
	helm repo update argo

	# boostrap via ArgoCD
	helm install \
		--namespace argocd \
		--create-namespace \
		argocd \
		argo/argo-cd \
		--atomic --wait \
		--values values/argocd/$(CLUSTER_NAME).yml

	# install CRDs of external-secrets
	kubectl apply -f https://raw.githubusercontent.com/external-secrets/external-secrets/HEAD/deploy/crds/bundle.yaml
	helm install \
		--namespace kube-system \
		--create-namespace \
		--wait --atomic \
		cluster-secrets \
		charts/cluster-secrets \
		--values /tmp/cluster-secrets.yaml
	rm -f /tmp/cluster-secrets.yaml


bootstrap-backbone: CLUSTER_NAME=backbone
bootstrap-backbone: bootstrap  ## Bootstrap backbone cluster onto current kubectl context.
