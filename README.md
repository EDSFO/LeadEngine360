# LeadEngine360

MVP para transformar o cadastro da empresa e da oferta, junto dos materiais comerciais, em contas B2B priorizadas por evidências. O fluxo implementado inclui onboarding multi-tenant, oferta, documentos, ICP revisável, importação de contas CSV, scoring inicial, registro de sinais, briefs comerciais e exportação.

## Rodar localmente com Docker

1. Copie `.env.example` para `.env` e defina segredos aleatórios para `JWT_SECRET` e `POSTGRES_PASSWORD`.
3. Execute `docker compose up --build` na raiz.
4. Abra `http://localhost:3000`. A API é acessada pelo frontend por meio do proxy interno.

O banco PostgreSQL e os uploads persistem em volumes do Docker. Para ativar análise com modelo de IA, preencha `OPENROUTER_API_KEY` e `OPENROUTER_MODEL` no `.env`. Sem chave, o sistema gera um rascunho heurístico e indica baixa confiança. O frontend encaminha chamadas de API pelo mesmo endereço, o que permite usar um hostname Tailscale ou endereço LAN sem gravar `localhost` no navegador.

## Publicação na máquina innovaapps

O MVP foi implantado na máquina `innovaapps`, com `APP_PORT=3002` porque as portas 3000 e 3001 já atendem outros aplicativos. Na rede local, abra `http://<IP_LAN>:3002`; pela Tailscale, abra `http://<IP_TAILSCALE>:3002` em um dispositivo conectado à mesma tailnet. O frontend é a única porta de usuário; PostgreSQL, Redis e API ficam acessíveis apenas na rede interna do Docker. O script em `deploy/innovaapps.ps1` prepara os segredos, constrói as imagens e abre a porta 3002 apenas para a rede local e a faixa Tailscale.

## Rodar componentes fora do Docker

Inicie PostgreSQL e Redis. No ambiente virtual, instale `backend/requirements.txt`, defina `DATABASE_URL`, `REDIS_URL` e `UPLOAD_DIR`, depois rode a API (`uvicorn app.main:app --app-dir backend --reload`) e o worker (`celery -A app.worker.celery_app worker --loglevel=INFO --pool=solo`) em terminais separados. Na pasta `frontend`, execute `npm ci` e `npm run dev`. O worker com `--pool=solo` atende desenvolvimento local no Windows; o Compose usa concorrência de dois processos Linux.

## Escopo atual

- Cadastro e login, empresa vendedora e até cinco ofertas.
- Upload de PDF, DOCX, TXT e Markdown (até 20 MB por arquivo), processado em background por Celery e Redis.
- Extração, divisão e indexação do texto em trechos isolados por tenant e oferta, com estado e retries visíveis.
- Recuperação de trechos por relevância textual para contextualizar a análise.
- Perfil comercial e ICP sugerido, com evidências recuperadas e perguntas em aberto.
- O resultado da análise é um rascunho até o usuário revisar e aprovar o ICP.
- Contas entram por CSV; conectores automáticos de descoberta ainda não estão configurados.
- Fit Score usa segmento, porte e região informados no CSV e definidos no ICP aprovado.
- O ICP admite pesos em `ideal_customer_profile.weights` (chaves `segments`, `company_size` e `regions`) e limiares em `classification_thresholds`.
- Intent e Timing usam sinais adicionados manualmente com força, confiança, data e origem.
- O score de Engajamento considera contato, resposta, reunião, oportunidade, ganho e perda registrados no pipeline.
- Hot exige Fit Score de pelo menos 24, score total de 80 ou mais e um sinal com confiança de pelo menos 0,6.
- Exportação CSV preserva as dimensões do score e sua classificação.

## Importação de contas

Baixe o modelo CSV na tela `Contas e sinais`. São reconhecidos nomes de coluna em português e inglês para empresa, domínio/site, setor, porte e região. Uma repetição do mesmo domínio para a mesma oferta atualiza a conta existente. O lote aceita até 2.000 linhas e registra linhas ignoradas.

Os sinais são incluídos com tipo, descrição, confiança, força, data e URL de origem. A tela mantém a evidência, permite registrar resultados comerciais, recalcula o score e gera brief de abordagem para cada conta. Os briefs usam sinais informados e deixam lacunas como perguntas, sem declarar uma necessidade de compra como fato.

## Fontes e conectores

A tela `Fontes e conectores` mantém, por oferta, a seleção das fontes e ferramentas desejadas, seguindo o fluxo do diagrama: descoberta de empresas, inbound, enriquecimento de contatos, sinais de intenção, tecnologias, extração pública, análise/escrita e outbound/CRM. O catálogo separa o que o MVP já permite (CSV, sinais manuais, exportação e gateway de IA configurado) do que é uma integração planejada. Salvar uma seleção não ativa nem autentica um fornecedor.

A arquitetura favorece alternativas abertas onde são viáveis: OpenStreetMap/Overpass para descoberta geográfica; WhatWeb para fingerprinting tecnológico; Crawl4AI self-hosted para extração controlada de páginas públicas; Mautic e Twenty como possíveis integrações de marketing/CRM. A análise e a escrita usam OpenRouter com o modelo configurado em `OPENROUTER_MODEL`. Há conectores comerciais opcionais no catálogo para fontes e enriquecimento como Apollo, Prospeo, LeadMagic, BuiltWith e outras. Não há hoje uma base open source que replique com cobertura geral os dados comerciais de contatos e intenção dos fornecedores pagos.

Credenciais de terceiros ainda não são coletadas nem gravadas. A próxima implementação de cada conector deve usar API oficial ou exportação autorizada, segredos fora das tabelas de negócio, limites de uso e evidência de origem. Extração web deve ser limitada a fontes públicas permitidas; automação de contas pessoais ou navegação automatizada em redes sociais não está habilitada.

## Limitações atuais

- PDFs digitalizados ainda precisam de OCR antes do envio.
- A recuperação RAG atual é lexical; embeddings e busca vetorial ficam para uma próxima etapa.
- A seleção de conectores é persistida por oferta, mas apenas os itens marcados como disponíveis funcionam no fluxo atual; os demais são catálogo/planejamento.
- Não há enriquecimento automático de e-mail/telefone, coleta automática de sinais externos nem envio de campanhas.
- O schema de desenvolvimento é criado automaticamente. Antes do primeiro deploy de produção, adotar migrations e guardar segredos de fornecedores em mecanismo próprio.
