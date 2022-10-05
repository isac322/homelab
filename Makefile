.PHONY: help bootstrap

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

bootstrap: /tmp/prod-cluster-secrets.yaml /tmp/backbone-cluster-secrets.yaml /tmp/public_ip_map.yaml ## Bootstrap given cluster onto current kubectl context. (Possible CLUSTER_NAME: backbone, prod)
	make -C cluster-setup argocd


/tmp/%-cluster-secrets.yaml:
	@test -r 'terraform/$*' || (echo 'Specify valid cluster name via CLUSTER_NAME'; exit 1)
	make -C terraform/$* cluster-secrets DEST=$@


/tmp/public_ip_map.yaml:
	make -C terraform/prod public-ip-map DEST=$@
