# LeadEngine360

Projeto para transformar o cadastro da empresa e da oferta, junto dos materiais comerciais, em contas B2B priorizadas por evidências. O fluxo implementado inclui onboarding multi-tenant, oferta, documentos, ICP revisável, descoberta por APIs de Overpass, Apollo e Hunter, importação legada de contas CSV, scoring, workflows por conta, registro de sinais, briefs comerciais e exportação. As integrações ainda precisam de validação na Innovaapps e não cobrem todos os nichos B2B.

## Rodar localmente com Docker

1. Copie `.env.example` para `.env` e defina segredos aleatórios para `JWT_SECRET` e `POSTGRES_PASSWORD`.
2. Execute `docker compose up --build` na raiz. A API aplica as migrações Alembic antes de iniciar.
3. Abra `http://localhost:3000`. A API é acessada pelo frontend por meio do proxy interno.

O banco PostgreSQL e os uploads persistem em volumes do Docker. Para ativar análise com modelo de IA, preencha `OPENROUTER_API_KEY` e `OPENROUTER_MODEL` no `.env`. Sem chave, o sistema gera um rascunho heurístico e indica baixa confiança. O frontend encaminha chamadas de API pelo mesmo endereço, o que permite usar um hostname Tailscale ou endereço LAN sem gravar `localhost` no navegador.

`OPENROUTER_FALLBACK_MODELS` aceita uma lista de modelos separada por vírgulas. Se o modelo principal falhar ou devolver JSON inválido, o sistema tenta os modelos seguintes antes da heurística. O scheduler Celery recalcula diariamente os scores sujeitos à recência dos sinais.
As tentativas de IA gravam modelo, status, latência, tokens e custo quando informados pelo provedor, consultáveis por oferta em `GET /api/v1/offers/{offer_id}/ai-calls`. Prompts, respostas completas e chaves não são gravados nessa trilha.

## Publicação na máquina innovaapps

O script de deploy anterior fixava `APP_PORT=3002`, mas a verificação de 02/10/2026 encontrou outro aplicativo nessa porta. O endereço e a versão atualmente implantada do LeadEngine360 na Innovaapps ainda precisam ser confirmados antes do teste E2E ou de um deploy. A intenção do Compose é expor apenas o frontend; PostgreSQL, Redis e API ficam na rede interna do Docker.
O script de deploy agora respeita `APP_PORT` da `.env` ou o parâmetro `-AppPort`, verifica conflito de porta e inclui o scheduler. Nenhum deploy foi executado após essa mudança.

Para gerar um backup no host Docker, execute `python deploy/backup.py DIRETORIO_DE_BACKUP` na raiz do projeto. O script salva um dump PostgreSQL, um arquivo dos uploads e um manifesto com hashes, sem reiniciar a stack. Agendamento, destino externo e restauração de teste ainda precisam ser configurados na Innovaapps.

## Rodar componentes fora do Docker

Inicie PostgreSQL e Redis. No ambiente virtual, instale `backend/requirements.txt` e defina `DATABASE_URL`, `REDIS_URL` e `UPLOAD_DIR`. Na pasta `backend`, execute `alembic -c alembic.ini upgrade head`; depois rode a API (`uvicorn app.main:app --reload`), o worker (`celery -A app.worker.celery_app worker --loglevel=INFO --pool=solo`) e o scheduler (`celery -A app.worker.celery_app beat --loglevel=INFO`) em terminais separados. Na pasta `frontend`, execute `npm ci` e `npm run dev`. O worker com `--pool=solo` atende desenvolvimento local no Windows; o Compose usa concorrência de dois processos Linux.

## Escopo atual

- Cadastro e login, empresa vendedora e até cinco ofertas.
- Upload de PDF, DOCX, TXT e Markdown (até 20 MB por arquivo), processado em background por Celery e Redis.
- Extração, divisão e indexação do texto em trechos isolados por tenant e oferta, com estado e retries visíveis.
- Recuperação de trechos por relevância textual para contextualizar a análise.
- Perfil comercial e ICP sugerido, com evidências recuperadas e perguntas em aberto.
- O resultado da análise é um rascunho até o usuário revisar e aprovar o ICP.
- Após aprovar um ICP com critérios úteis, a tela de contas permite buscar empresas por OpenStreetMap / Overpass API usando uma tag e área geográfica. O worker recebe a resposta, registra a origem, deduplica e calcula o score. A execução pode ser acompanhada como job.
- E-mail e telefone gerais presentes na fonte OSM são associados à conta como contato da empresa, com link de origem. Esses dados não identificam um decisor pessoal.
- O administrador do tenant pode criar convites de equipe na tela `Equipe`. O convidado define a própria senha, e as ações de escrita respeitam os papéis administrador, gestor, analista, SDR e closer.

- O CSV permanece na API para compatibilidade/importação legada, mas não é o caminho operacional da busca de leads nem satisfaz sozinho o requisito do MVP.
- Fit Score usa segmento, porte e região informados pela fonte e definidos no ICP aprovado.
- O ICP pode ser revisado por formulário; JSON avançado permanece disponível. Pesos ficam em `ideal_customer_profile.weights`, obrigatoriedade em `ideal_customer_profile.required` e limiares em `classification_thresholds`. Falha em critério obrigatório impede Fit e classificação acima de Cold.
- Intent e Timing usam sinais adicionados manualmente com força, confiança, data e origem.
- O score de Engajamento considera contato, resposta, reunião, oportunidade, ganho e perda registrados no pipeline.
- Hot exige Fit Score de pelo menos 24, score total de 80 ou mais e um sinal com confiança de pelo menos 0,6.
- Exportação CSV preserva as dimensões do score e sua classificação.

A tela `Equipe` mostra o link do convite uma vez para o administrador copiar e compartilhar. O sistema ainda não envia e-mail de convite.

## Busca integrada de contas

Na tela `Contas e sinais`, selecione a oferta com ICP aprovado e informe uma tag do OpenStreetMap (por exemplo `amenity=restaurant`) e uma área pequena no formato `sul, oeste, norte, leste`. A interface grava a configuração em `profile.discovery`, ativa o conector da oferta e inicia `POST /api/v1/offers/{offer_id}/discovery`. O worker Celery consulta a API Overpass, guarda referências dos elementos OSM e pontua as contas. A tela acompanha o job e atualiza a lista ao concluir. Apenas resultados com nome são incluídos; site não é obrigatório.

Essa fonte é apropriada para alguns negócios locais. A cobertura e a disponibilidade da API pública variam. Para nichos sem tags OSM úteis, a jornada precisa de outro adaptador API/MCP com dados adequados. Não usar a instância pública para consultas em massa; para escala, configurar uma fonte ou instância compatível com a carga.

`OVERPASS_URL` permite apontar o worker para uma instância Overpass própria ou compatível. A consulta limita a área a um grau por eixo e retorna no máximo 200 elementos por execução. E-mail/telefone gerais só aparecem quando a fonte os fornece; nome, cargo e contato de decisores continuam pendentes de fonte adequada.

Apollo.io e Hunter também podem ser escolhidos na tela de contas. Configure `APOLLO_API_KEY` e/ou `HUNTER_API_KEY` no ambiente da API **e do worker** na Innovaapps; não envie chaves pelo chat nem as grave nas tabelas de negócio. O Apollo Organization Search consulta empresas com filtros do ICP e limita a primeira página a 100 resultados. O Hunter Discover consulta empresas e, quando Hunter está habilitado para a oferta, o worker usa Domain Search para buscar até 10 contatos por domínio. Esses endpoints exigem acesso e cotas conforme o plano do fornecedor. Os contatos têm origem e confiança registradas. A instalação dos apps Apollo/Hunter no ChatGPT não autentica o worker independente do LeadEngine360.

Cada conta encontrada recebe um `workflow_run` com etapas de origem, contatos, sinais, score e brief. `GET /api/v1/offers/{offer_id}/workflows` mostra o processamento; `GET /workflows/{run_id}` detalha as etapas; `POST /workflows/{run_id}/retry` reexecuta uma falha. Sinais externos automáticos ainda não têm conector e a etapa aparece como ignorada quando não há sinais. O job de descoberta pode terminar antes dos workflows individuais.

## Importação legada de contas

O endpoint `POST /api/v1/offers/{offer_id}/accounts/import` aceita CSV para migração/compatibilidade. São reconhecidos nomes de coluna em português e inglês para empresa, domínio/site, setor, porte e região. Uma repetição do mesmo domínio para a mesma oferta atualiza a conta existente. O lote aceita até 2.000 linhas e registra linhas ignoradas.

Os sinais são incluídos com tipo, descrição, confiança, força, data e URL de origem. A tela mantém a evidência, permite registrar resultados comerciais, recalcula o score e gera brief de abordagem para cada conta. Os briefs usam sinais informados e deixam lacunas como perguntas, sem declarar uma necessidade de compra como fato.

## Fontes e conectores

A tela `Fontes e conectores` mantém, por oferta, a seleção das fontes e ferramentas desejadas. OpenStreetMap / Overpass, Apollo.io e Hunter têm adaptadores de descoberta; Hunter também pode enriquecer contatos por domínio. Os demais itens planejados continuam sem execução. Salvar uma seleção não autentica fornecedores.

A arquitetura favorece alternativas abertas onde são viáveis: OpenStreetMap/Overpass para descoberta geográfica; WhatWeb para fingerprinting tecnológico; Crawl4AI self-hosted para extração controlada de páginas públicas; Mautic e Twenty como possíveis integrações de marketing/CRM. A análise e a escrita usam OpenRouter com o modelo configurado em `OPENROUTER_MODEL`. Há conectores comerciais opcionais no catálogo para fontes e enriquecimento como Apollo, Prospeo, LeadMagic, BuiltWith e outras. Não há hoje uma base open source que replique com cobertura geral os dados comerciais de contatos e intenção dos fornecedores pagos.

Credenciais de terceiros ainda não são coletadas nem gravadas. A próxima implementação de cada conector deve usar API oficial ou exportação autorizada, segredos fora das tabelas de negócio, limites de uso e evidência de origem. Extração web deve ser limitada a fontes públicas permitidas; automação de contas pessoais ou navegação automatizada em redes sociais não está habilitada.

## Limitações atuais

- PDFs digitalizados ainda precisam de OCR antes do envio.
- A recuperação RAG atual é lexical; embeddings e busca vetorial ficam para uma próxima etapa.
- A seleção de conectores é persistida por oferta, mas apenas os itens marcados como disponíveis funcionam no fluxo atual; os demais são catálogo/planejamento.
- OSM fornece somente contatos gerais quando disponíveis. Hunter pode localizar pessoas e e-mails associados ao domínio, conforme cobertura e plano; os dados externos ainda precisam de validação operacional. Não há coleta automática de sinais externos nem envio de campanhas.
- O schema é versionado por Alembic. A migração inicial preserva as tabelas do piloto e adiciona as novas tabelas, mas o banco remoto precisa de backup e inspeção antes da primeira atualização. Segredos de fornecedores adicionais devem ficar fora das tabelas de negócio.
