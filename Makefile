# SPDX-License-Identifier: Apache-2.0

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

PYTHON ?= python3
RUN_ID ?=
RUN_ARG := $(if $(strip $(RUN_ID)),--run-id $(RUN_ID),)

.PHONY: help doctor doctor-json init-submodules docker-pull orfs-deps orfs-build \
        croc-rtl croc-netlist-sim croc-pnr croc-gds croc-signoff \
        pin3d-smoke pin3d-full report test validate-contracts

help:
	@echo "open-3d-memory-chipflow"
	@echo "  make doctor             read-only WSL/tool/version audit"
	@echo "  make docker-pull        pull and lock hpretl/iic-osic-tools:2025.12"
	@echo "  make orfs-build         local ORFS build, limited to 6 threads"
	@echo "  make croc-rtl           software + Verilator RTL simulation"
	@echo "  make croc-netlist-sim   Yosys synthesis + gate-level simulation"
	@echo "  make croc-pnr           OpenROAD floorplan through finishing"
	@echo "  make croc-gds           KLayout GDS + seal + metal/active fill"
	@echo "  make croc-signoff       full IHP DRC + antenna + density + exact LVS"
	@echo "  make pin3d-smoke        ASAP7+ASAP7/GCD 3D flow"
	@echo "  make pin3d-full         same flow plus strict artifact acceptance"
	@echo "  make report             Markdown/JSON/index from run manifests"
	@echo "  make test               fast contract/unit tests"
	@echo "Use RUN_ID=name to group stages without overwriting history."

doctor:
	$(PYTHON) scripts/doctor.py --human

doctor-json:
	$(PYTHON) scripts/doctor.py --json

init-submodules:
	git submodule update --init --recursive --jobs 4

docker-pull:
	bash scripts/pull_croc_image.sh

orfs-deps:
	bash scripts/bootstrap_orfs_dependencies.sh

orfs-build:
	bash scripts/build_orfs.sh

croc-rtl:
	$(PYTHON) scripts/run_stage.py $(RUN_ARG) --stage croc-rtl --classification public_rule_candidate -- bash scripts/croc_flow.sh rtl

croc-netlist-sim:
	$(PYTHON) scripts/run_stage.py $(RUN_ARG) --stage croc-netlist-sim --requires croc-rtl --classification public_rule_candidate -- bash scripts/croc_flow.sh netlist-sim

croc-pnr:
	$(PYTHON) scripts/run_stage.py $(RUN_ARG) --stage croc-pnr --requires croc-netlist-sim --classification public_rule_candidate -- bash scripts/croc_flow.sh pnr

croc-gds:
	$(PYTHON) scripts/run_stage.py $(RUN_ARG) --stage croc-gds --requires croc-pnr --classification public_rule_candidate -- bash scripts/croc_flow.sh gds

croc-signoff:
	$(PYTHON) scripts/run_stage.py $(RUN_ARG) --stage croc-signoff --requires croc-pnr --requires croc-gds --classification public_rule_candidate -- bash scripts/croc_signoff.sh

pin3d-smoke:
	$(PYTHON) scripts/run_stage.py $(RUN_ARG) --stage pin3d-smoke --classification research_only -- bash scripts/pin3d_flow.sh smoke

pin3d-full:
	$(PYTHON) scripts/run_stage.py $(RUN_ARG) --stage pin3d-full --classification research_only -- bash scripts/pin3d_flow.sh full

report:
	$(PYTHON) scripts/report.py --runs runs --output reports/generated

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

validate-contracts:
	$(PYTHON) scripts/validate_json.py schemas/traffic_spec.schema.json config/traffic_spec.json
	$(PYTHON) scripts/validate_json.py schemas/signoff_summary.schema.json config/signoff_summary.template.json
