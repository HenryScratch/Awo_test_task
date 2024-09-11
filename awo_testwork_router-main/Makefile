SHELL := bash
.SHELLFLAGS := -e -u -c # -o pipefail
.ONESHELL:
.DELETE_ON_ERROR:

ROUTERADDR=62.217.180.127:10000

#include .env
#export

.PHONY: help
help:
	@:

PHONY: all
all: virtualenv install build

.PHONY: virtualenv
virtualenv:
	@echo 'creating the virtualenv...'
	@rm -rf .venv
	@virtualenv .venv # which python?
	@.venv/bin/pip install -U pip setuptools wheel build virtualenv ipython
	@echo 'run `source .venv/bin/activate` to activate virtualenv'

.PHONY: install
install:
	@echo 'installing the package into virtualenv (-editable mode)...'
	@.venv/bin/pip install -e .

.PHONY: build
build:
	@echo 'generating the distribution packages (tar.gz & wheel)...'
	@.venv/bin/python3 -m build #.venv/bin/pip wheel --no-deps .

.PHONY: clean
clean:
	@echo 'cleaning build/dist/egg-info directories...'
	@rm -rf build dist src/*.egg-info

.PHONY: docker
docker:
	@echo 'bulding the docker image...'
	docker build --tag $(name)

.PHONY: check
check:
	@ruff check --output-format=full src tools test | less
#	@mypy src

.PHONY: run
run:
	.venv/bin/python3 -m router.cli -d

.PHONY: shell
shell:
	@.venv/bin/ipython3 --no-confirm-exit

.PHONY: version
version:
	@grep __version__ src/*/__init__.py # package name?

.PHONY: router-ping
router-ping:
	@curl -s -H 'x-token:auth' http://mp-router:10000/router/ping

.PHONY: router-users
router-users:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/users | jq

.PHONY: router-accounts
router-accounts:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/accounts | jq

.PHONY: router-accounts-emails
router-accounts-emails:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/accounts | jq '.[] | .email'

.PHONY: router-accounts-worker-state
router-accounts-worker-state:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/accounts | jq '.[] | {email, worker_state}'

.PHONY: router-accounts-req-stats
router-accounts-req-stats:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/accounts | jq '.[] | {email, req_stats}'

.PHONY: router-accounts-last-status-codes
router-accounts-last-status-codes:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/accounts | jq '.[] | {email, last_status_codes}'

.PHONY: router-accounts-deny
router-accounts-deny:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/accounts | jq '.[] | select (.api_routing_rules.deny | length > 0) | {email, deny: .api_routing_rules.deny}'

.PHONY: router-accounts-banned
router-accounts-banned:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/accounts | jq '.[] | select(.banned==true) | .email'

.PHONY: router-stats-users
router-stats-users:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/stats/users | jq

.PHONY: router-stats-http
router-stats-http:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/stats/http | jq

.PHONY: router-stats-service
router-stats-service:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/stats/service | jq

.PHONY: router-stats-cache
router-stats-cache:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/stats/cache | jq

.PHONY: router-cache-top10
router-cache-top10:
	@curl -s -H 'x-token:auth' http://$(ROUTERADDR)/router/cache/top10 | jq

.PHONY: router-reset
router-reset:
	@curl -s -H 'x-token:auth' -X POST http://$(ROUTERADDR)/router/reset

.PHONY: router-reset-users
router-reset-users:
	@curl -s -H 'x-token:auth' -X POST http://$(ROUTERADDR)/router/reset/users

.PHONY: router-reset-accounts
router-reset-accounts:
	@curl -s -H 'x-token:auth' -X POST http://$(ROUTERADDR)/router/reset/accounts
