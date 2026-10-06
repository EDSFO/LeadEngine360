# LeadEngine360 — instruções e histórico de colaboração

## Registro das interações

- Leia este arquivo antes de trabalhar no projeto.
- Registre aqui cada nova interação de trabalho: solicitação do usuário, decisões, ações executadas, resultados e pendências. Atualize o registro ao concluir a interação.
- Preserve o histórico anterior. Correções devem ser acrescentadas com indicação do que substituem.
- Use datas no fuso America/Sao_Paulo. Não invente horários ou resultados.
- Este registro cobre as interações disponíveis nesta conversa e as futuras; não presume acesso a conversas anteriores. As solicitações iniciais estão transcritas abaixo, e as ações do assistente estão resumidas.
- Não registre senhas, tokens, chaves de API, conteúdo de `.env` ou dados pessoais de clientes. Descreva configurações sensíveis apenas pelo nome.
- Diferencie implementação encontrada no código, comportamento efetivamente testado e comportamento ainda não validado.

## Ambiente — informação confirmada pelo usuário

- **Erick:** máquina do workspace local, em `C:\Users\erick\Desktop\LeadEngine360`.
- **Innovaapps:** máquina que hospeda o Docker e os containers do projeto. Os testes do ambiente implantado devem ser direcionados a ela.
- A indisponibilidade do Docker na Erick não indica falha no ambiente do projeto.
- Não iniciar Docker nem montar uma stack local na Erick para substituir o ambiente implantado sem uma solicitação específica nesse sentido.
- O README e `deploy/innovaapps.ps1` documentam a porta **3002** na Innovaapps. Confirmar o endereço acessível e o estado remoto antes de executar os testes.
- Um timeout em `http://innovaapps:3002` a partir da Erick não prova que os containers estejam parados: endereço, resolução de nome, conectividade e serviço ainda precisam ser verificados.
- Em testes E2E, usar dados fictícios identificáveis e preservar os dados existentes. Não executar deploy, reiniciar a stack remota ou alterar credenciais como parte de um diagnóstico sem necessidade e autorização compatível.

## Objetivo em andamento

Avaliar o LeadEngine360 de ponta a ponta e entregar evidências do que funciona, do que falha e do que falta para concluir o MVP. Comparar separadamente o escopo implementado/documentado no README e os critérios do `PRD_LeadEngine360_v0.1.docx`.

## Histórico

### 2026-10-02 — solicitação de teste E2E

**Usuário:** “Conseguimos fazer um teste E2E para sabermos o que está funcional e o que não está , bem como o que falta para concluirmos o MVP ?”

**Ações e constatações do assistente:**

- Leu README, configuração Docker Compose, script de deploy, dependências e código de frontend/backend; extraiu texto e tabelas do PRD.
- Consultou a skill Playwright para preparar a verificação no navegador.
- Identificou no código o fluxo de cadastro/login, empresa/oferta, documentos, ICP, importação CSV, scoring, sinais manuais, resultados comerciais, briefs e exportação. Isso ainda não equivale a aprovação E2E.
- Identificou diferença de escopo: o PRD prevê contatos, enriquecimento, processamento automático de contas, papéis, fallback entre modelos e auditoria mais ampla; o README descreve um fluxo manual e conectores majoritariamente planejados.
- Tentou acessar localhost e `http://innovaapps:3002`. A tentativa ao hostname remoto expirou; o ambiente remoto não foi inspecionado.
- Preparou equivocadamente uma execução local na Erick: API em 127.0.0.1:8000, frontend em 127.0.0.1:3000, SQLite isolado em `output/playwright/e2e.db`, uploads de teste e IA externa desabilitada nessa execução.
- Tentou iniciar Docker Desktop local; a API do Docker permaneceu indisponível nas consultas realizadas. Essa tentativa não valida o Docker da Innovaapps.
- Abriu a página inicial local com Playwright; o navegador registrou um erro de console ainda não investigado. Não concluiu cadastro, importação nem qualquer fluxo E2E completo.
- A execução foi interrompida antes da conclusão. Foram gerados artefatos locais em `output/` e `.playwright-cli/`.

**Pendência:** retomar o diagnóstico no ambiente correto, verificar conectividade com a Innovaapps e executar a matriz de fluxos com evidências. Ainda não existe laudo E2E concluído.

### 2026-10-02 — histórico persistente e correção do ambiente

**Usuário:** “Precisamos fazer algumas melhoras e correções:
01) Crie o agents.md para armazenar todas as nossas interações
02) O Docker com o container do projeto não  está na máquina Erick e sim na Innovaapps.”

**Decisões e ações:**

- Criado este `AGENTS.md` na raiz, com nome convencional para instruções de agentes, histórico disponível e regra de atualização nas próximas interações.
- Corrigido o contexto operacional: Docker e containers do projeto estão na Innovaapps; Erick é o workspace local.
- A preparação local anterior não deve ser usada para concluir se o ambiente implantado funciona ou falha.
- Encerrados os processos de API e frontend iniciados pelo assistente para o teste local e fechada a sessão Playwright `le360-e2e`. Artefatos preservados para rastreabilidade.
- Nenhuma alteração nos containers ou no deploy da Innovaapps foi realizada.

**Próximo passo:** validar o acesso à Innovaapps e continuar a avaliação E2E originalmente solicitada, mantendo explícita a distinção entre falhas, itens não implementados e verificações bloqueadas pelo ambiente.

### 2026-10-02 — retomada do E2E na Innovaapps

**Usuário:** “Podemos dar sequencia no E2E”.

- Innovaapps confirmada online pelo Tailscale, IP `100.108.2.19`.
- A porta 3002 responde, mas apresenta **Innova Content Agent**, não LeadEngine360. Isso corrige a hipótese de endereço do README; a porta atual do LeadEngine360 ainda precisa ser identificada.
- SSH por hostname não tinha chave de host conhecida; por IP a chave conhecida foi aceita, mas o usuário `erick` não autenticou. Nenhum comando remoto foi executado.
- Solicitado ao usuário URL/porta atual ou usuário SSH configurado, sem pedir senha/chave.
- Preparada matriz de 22 casos, evidências de conectividade e análise estática preliminar em `output/playwright/E2E-2026-10-02.md`.
- Nenhum fluxo funcional do LeadEngine360 foi concluído nesta retomada; nenhuma alteração remota ou stack local foi iniciada.
- Atenção para reprodução: cálculo de score consulta eventos antes de flush em sessão com autoflush desabilitado; não declarar como falha E2E antes de testar.

### 2026-10-06 — análise de completude funcional

**Usuário:** “Faça uma análise no projeto e me traga o que está faltando para termos o sistema 100% funciuonal”.

- Reexaminados README, PRD v0.1, frontend/backend, modelos, schemas, Celery, Compose e script de deploy. Comparados separadamente o piloto manual do README e os requisitos do PRD.
- Executados testes diretos de funções reais com dados fictícios em SQLite exclusivamente em memória, sem iniciar servidor/stack, Docker ou worker, sem usar banco existente ou chamar IA externa.
- Reproduzidos: primeiro sinal não entra no score imediato (40 em vez de 80); primeira reunião não entra no engajamento imediato (0 em vez de 12); duplicata de domínio no mesmo CSV gera erro de unicidade do score; salvamentos sucessivos permitem seis ofertas; API aprova ICP vazio. Edição de oferta mantém ICP aprovado, exigindo decisão sobre invalidação.
- Isso acrescenta evidência isolada à hipótese de scoring de 02/10; não substitui E2E na Innovaapps. Recálculo explícito refletiu corretamente o sinal e a reunião. Consulta de contas de outro tenant retornou 404, sem validar todo o isolamento do produto.
- Checagem TypeScript com `--noEmit --incremental false` passou. Não foram executados build Docker, testes PostgreSQL/Redis/worker ou E2E de navegador nesta interação.
- Relatório e roteiro priorizado em `output/analysis-2026-10-06/ANALISE.md`; script reprodutível e resultados na mesma pasta. Identificadas lacunas de contatos, enriquecimento/coleta efetivos, processamento assíncrono de contas, papéis, fallback entre modelos, auditoria IA, paginação, manutenção/históricos, migrações e recuperação operacional.
- Nenhum código funcional, credencial, container ou deploy foi alterado. Artefatos anteriores e alterações preexistentes foram preservados.
- **Pendências:** corrigir falhas reproduzidas; fechar escopo/fontes do primeiro nicho; confirmar endereço e versão do LeadEngine360 na Innovaapps e executar aceite remoto. A evidência da porta 3002 é histórica de 02/10, não uma nova verificação de disponibilidade.

### 2026-10-06 — busca integrada de leads e conexões Apollo/Hunter

**Usuário:** Determinou que a busca por leads após a definição do ICP deve ocorrer somente por integrações com serviços, MCP ou APIs; perguntou o que falta para o sistema funcionar, se existe opção open source, se Apollo.io e Hunter podem ser usados, informou que instalou ambos no ChatGPT e perguntou como usá-los aqui.

**Decisões e ações:**

- Mantida a importação CSV apenas como compatibilidade legada, fora da jornada operacional de descoberta. OpenStreetMap/Overpass permanece opção aberta para nichos locais, com cobertura limitada.
- Implementados no código adaptadores de busca de empresas via Apollo Organization Search e Hunter Discover, usando critérios do ICP e limites de até 100 resultados por chamada. Hunter Domain Search pode buscar contatos por domínio quando selecionado para a oferta. Chaves são referenciadas somente pelos nomes `APOLLO_API_KEY` e `HUNTER_API_KEY` e devem ser configuradas na API e no worker; nenhuma chave foi lida, alterada ou registrada aqui.
- Implementados workflow e etapas persistentes por conta, processamento Celery para score e brief, consulta de status na API/tela e reprocessamento de falhas. A etapa de sinais automáticos é marcada como ignorada quando não existe fonte configurada.
- Confirmado pela busca de plugins que Apollo e Hunter aparecem como instalados e habilitados no catálogo da conta, mas as ferramentas desses apps não foram expostas como ferramentas chamáveis nesta sessão. Uma consulta de permissões retornou estado incompatível (“não instalado”), portanto a conexão efetiva aqui não foi comprovada. Orientado o uso de `/apps` e menção explícita do app para consulta interativa. A conexão do chat não autentica automaticamente o worker do projeto.
- Consultada documentação oficial de Apollo e Hunter para endpoints, autenticação, limites e uso de créditos. Nenhuma chamada real às APIs comerciais foi feita.
- Testes de backend com respostas simuladas: 18 passaram. Build de produção do frontend passou; `git diff --check` não apontou erros de whitespace (apenas avisos de conversão LF/CRLF). Migrações foram testadas em SQLite novo e cenário legado sintético, não no banco remoto.
- Nenhum deploy, teste E2E remoto, reinício de containers ou alteração de credenciais foi realizado.

**Pendências:** obter acesso confirmado ao LeadEngine360 na Innovaapps; configurar as chaves de API de forma segura no host, conferir se os planos permitem os endpoints escolhidos e validar as chamadas reais, migrações e fluxo completo no ambiente implantado. Escolher o primeiro nicho/ICP operacional e confirmar limites de gasto/cotas antes de buscas em volume. As conexões dos apps do ChatGPT podem apoiar consultas interativas quando disponíveis, mas não substituem a autenticação da aplicação implantada.

### 2026-10-06 — decisão sobre a busca de leads após o ICP

**Usuário:** “A busca por leads, após encontrarmos o ICP ideal, deve ser feita via integrações com serviços, MCP, APIs, nunca de forma manual.”

- Decisão de produto: a aprovação do ICP deve iniciar a descoberta de leads por serviços integrados via API ou MCP. Pesquisa ou entrada manual de leads não satisfazem o fluxo principal nem o aceite do MVP.
- Esta decisão substitui qualquer interpretação anterior de que o piloto baseado em CSV poderia concluir o MVP. O CSV permanece descrito como implementação encontrada no código, não como validação da descoberta exigida.
- Atualizados `README.md` e `output/analysis-2026-10-06/ANALISE.md` para explicitar a lacuna, o fluxo esperado e o critério de aceite.
- Nenhuma integração foi implementada ou testada nesta interação. Permanecem pendentes a seleção/configuração das fontes do primeiro nicho, implementação da busca e validação E2E na Innovaapps.

### 2026-10-06 — plano para deixar o sistema funcional

**Usuário:** “Agora me traga o que precisamos para deixar o sistema funcional?”

- Reconsultados o relatório de completude e os endpoints/catálogo de integrações no código local. A busca por API/MCP continua apenas planejada no catálogo; o endpoint operacional encontrado para entrada de contas é a importação CSV.
- Consolidado plano priorizado: corrigir falhas reproduzidas de ICP, score, duplicatas e limite de ofertas; implementar descoberta por fonte real após ICP aprovado, processamento assíncrono, contatos/enriquecimento e rastreabilidade; completar interface, papéis, fallback IA e operação; validar no ambiente implantado.
- Distinção mantida: testes isolados anteriores comprovam falhas específicas, mas não há aceite E2E do LeadEngine360 na Innovaapps. Nenhuma implementação, deploy ou teste remoto foi realizado nesta interação.
- Pendem a escolha do nicho e de ao menos uma fonte com acesso API/MCP, a implementação do fluxo e a confirmação do endereço/versão da aplicação na Innovaapps.

### 2026-10-06 — início da implementação contínua do MVP

**Usuário:** “Implemente até ficar funcional.” Ao ser perguntado pelo primeiro nicho/fonte, respondeu: “Existe alguma opção opensource?”

- Escolhida provisoriamente a opção aberta OpenStreetMap / Overpass para negócios locais, com cobertura dependente de tags e região. A escolha não encerra a necessidade de outra fonte para nichos B2B sem cobertura adequada ou contatos/decisores.
- Corrigidos no código o score imediato do primeiro sinal e atividade, a duplicata de domínio no mesmo CSV, a aprovação de ICP sem critérios e o limite total de cinco ofertas. Mudanças em oferta ou empresa tornam ICP aprovado um rascunho. Implementada validação de critérios, pesos e limiares do ICP.
- Criados adaptador de descoberta Overpass com tag e área limitadas, registro de origem por elemento OSM, job Celery com retries, endpoints para iniciar/consultar descoberta e interface para configurar a busca e acompanhar o job. Contas sem site podem ser identificadas pelo ID da fonte. A busca usa API; a entrada CSV foi retirada da interface principal, mas o endpoint legado permanece.
- Adicionados total/paginação/filtros no servidor para a lista de contas e leitura de brief já salvo. README atualizado com fluxo, limites e estado de implantação. Atribuição OSM aparece na interface e na exportação.
- Validação local: 8 testes de backend em SQLite isolado passaram; checagem TypeScript passou; build de produção Next.js passou antes das últimas mudanças de paginação/brief (estas têm checagem TypeScript, mas build posterior ainda pendente). O teste HTTP do endpoint de descoberta usa fila simulada; o teste do worker usa resposta externa simulada.
- Duas tentativas de chamada real à API pública Overpass falharam a partir da Erick: uma resposta 504 e um timeout. Portanto, a disponibilidade da fonte real e o fluxo implantado ainda não foram comprovados. `OVERPASS_URL` permite apontar para instância compatível, sem configurar nem iniciar Docker local.
- Permanecem faltando: fonte adequada ao nicho real e contatos/decisores, enriquecimento e sinais externos, processamento completo da conta, papéis/permissões, fallback entre modelos, auditoria, migrações/backup/monitoramento e E2E na Innovaapps. Nenhum container remoto ou deploy foi alterado.

### 2026-10-06 — continuação da implementação do MVP

**Objetivo ativo do usuário:** “Implemente até ficar funcional.” Nenhuma mudança de escopo foi solicitada nesta continuação. Foi perguntada de forma assíncrona a URL atual do LeadEngine360 na Innovaapps; a resposta ainda não estava disponível ao fechar este registro.

- Confirmado no PRD v0.1: contatos (nome/cargo e e-mail/telefone quando disponíveis), papéis básicos, fallback de modelo, jobs, telemetria de IA e backups são requisitos do MVP. A fonte OSM pode fornecer apenas canais gerais da empresa; isso não comprova identificação de decisores.
- Implementados contatos gerais extraídos da fonte OSM com origem e consulta por conta; interface exibe contatos e registros de origem separadamente. A repetição da descoberta atualiza o contato sem duplicá-lo.
- Implementados convites de equipe com token armazenado em hash, validade de sete dias, aceite com senha própria, papéis e permissões de escrita. Criadas telas `/team` e `/join`. Teste HTTP provou que SDR registra atividade, mas não aprova ICP nem administra usuários. Administração da plataforma entre tenants ainda não foi implementada.
- Implementados fallback sequencial entre modelos OpenRouter configurados, trilha de chamadas de IA por oferta (modelo, status, latência, tokens/custo quando disponíveis) e brief heurístico que não afirma Fit sem critério confirmado. O brief recebe ICP e score atuais.
- Implementados critério obrigatório no scoring e editor visual para listas, pesos e limiares do ICP; JSON avançado permanece disponível. Scheduler Celery recalcula scores diariamente. Endpoint `/health` verifica banco e Redis.
- Introduzida migração Alembic inicial compatível com tabelas anteriores do piloto, que verifica colunas existentes e adiciona tabelas novas. Docker inicia a API após aplicar a migração. Teste local validou banco vazio e cópia sintética do schema anterior, preservando registro preexistente; PostgreSQL implantado ainda não foi testado.
- O script de deploy deixou de fixar a porta 3002 e prepara a imagem do scheduler. Foi criado `deploy/backup.py` para dump PostgreSQL e arquivo de uploads com manifesto de hashes; o backup não foi executado na Innovaapps e não há teste de restauração ou agendamento.
- Verificações locais: 16 testes de backend passaram, build de produção Next.js passou, Compose foi lido como YAML e script PowerShell de deploy passou na análise sintática. Nenhum container local/remoto, credencial ou dado existente foi alterado.
- Pendências centrais: validar fonte externa real e cobertura do nicho, decisores/enriquecimento/sinais externos, workflow de conta com etapas e observabilidade completa, auditoria de mudanças, operação de backup/restauração, endereço/versão remota e aceite E2E na Innovaapps. As chamadas reais anteriores à Overpass pública falharam com 504/timeout; não foram repetidas nesta continuação.

### 2026-10-06 — teste real das APIs Apollo e Hunter

**Usuário:** “Já adicionei as api's key do apolllo e do hunter , veja se consegue fazer a busca por leads usando um icp qualquer como teste”.

- Verificado sem ler ou registrar valores: `APOLLO_API_KEY` e `HUNTER_API_KEY` estão preenchidas no `.env` local; não estão no ambiente de processo. A configuração do Compose encaminha ambas à API e ao worker, mas a configuração remota da Innovaapps não foi consultada.
- Chamadas reais feitas diretamente dos adaptadores locais, sem subir serviços, enfileirar job ou gravar resultados no banco. ICP de teste: empresas de software/SaaS, faixa 51–200 pessoas, Brasil.
- Hunter Discover respondeu com 100 empresas. Foram inspecionados até cinco nomes/domínios como amostra; os resultados não foram persistidos. A cota/crédito consumido não foi verificado.
- Apollo respondeu HTTP 403: o endpoint Organization Search usado pela integração não está disponível no plano Free; a própria resposta informa que requer plano pago. Nenhum resultado Apollo foi obtido.
- O teste valida as credenciais locais e a chamada direta ao Hunter, mas não valida o worker, a aplicação implantada, o armazenamento de leads ou as variáveis na Innovaapps. Não foi feita busca de contatos via Hunter Domain Search.
- Nenhum arquivo de implementação, dado de negócio, container ou deploy foi alterado nesta interação; este registro foi atualizado.