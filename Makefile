# Makefile para Qualia Core

.PHONY: help install install-dev test test-all test-api test-performance coverage \
        run-api frontend-install frontend-dev frontend-build \
        docker-build docker-run clean

PYTHON := .venv/bin/python

help: ## Mostra esta mensagem de ajuda
	@echo "Qualia Core - Comandos Disponíveis"
	@echo "=================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# ==== INSTALAÇÃO ====

install: ## Instala dependências do projeto
	$(PYTHON) -m pip install -e ".[all]"

install-dev: ## Instala dependências + ferramentas de dev
	$(PYTHON) -m pip install -e ".[all,dev]"

# ==== TESTES ====

test: ## Roda todos os testes
	$(PYTHON) -m pytest tests/ -v

test-all: ## Roda todos os testes com coverage
	$(PYTHON) -m pytest tests/ -v --cov=qualia --cov-report=term-missing

test-api: ## Testa a API REST
	$(PYTHON) -m pytest tests/test_api.py tests/test_api_extended.py -v

test-performance: ## Roda testes de performance
	$(PYTHON) -m pytest tests/test_performance.py -v

test-quick: ## Validação rápida do sistema
	@$(PYTHON) -c "from qualia.core import QualiaCore; c=QualiaCore(); print(f'Core OK - {len(c.registry)} plugins')"
	@$(PYTHON) -c "from qualia.api import app; print('API OK')"

coverage: ## Gera relatório de cobertura HTML
	$(PYTHON) -m pytest tests/ --cov=qualia --cov-report=html --cov-report=term
	@echo "Relatório em htmlcov/index.html"

# ==== EXECUÇÃO ====

run-api: ## Inicia a API REST
	$(PYTHON) -m uvicorn qualia.api:app --port 8000

# ==== FRONTEND ====

frontend-install: ## Instala dependencias do frontend
	cd qualia/frontend && npm install

frontend-dev: ## Inicia frontend em modo dev (porta 5173)
	cd qualia/frontend && npm run dev

frontend-build: ## Build do frontend (output em qualia/frontend/dist/)
	cd qualia/frontend && npm run build

# ==== DOCKER ====

docker-build: ## Constrói imagem Docker
	docker build -t qualia-core:latest .

docker-run: ## Roda via Docker
	docker-compose up -d qualia-api

# ==== LIMPEZA ====

clean: ## Remove arquivos temporários
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@echo "Limpo!"

# ==== ATALHOS ====

t: test
ta: test-all
c: coverage
