# Backend da Clinica Odontologica

API Django REST Framework para gestao odontologica multi-clinica.

## Contrato oficial

A API publica do produto esta versionada em `/api/v1/`.

Termos oficiais do dominio:

- `dentista`
- `cro`
- `nome_dentista`
- `/api/v1/dentistas/`

Nao fazem parte do contrato novo: `medico`, `crm`, `nome_medico` e `/medicos/`.

## Autenticacao

JWT:

- `POST /api/token/`
- `POST /api/token/refresh/`

Use o token de acesso no header:

```http
Authorization: Bearer <access_token>
```

## Endpoints principais

- `/api/v1/clinicas/`
- `/api/v1/horarios-funcionamento/`
- `/api/v1/bloqueios-agenda/`
- `/api/v1/indisponibilidades-dentistas/`
- `/api/v1/convites-pacientes/`
- `/api/v1/usuarios/`
- `/api/v1/dentistas/`
- `/api/v1/procedimentos/`
- `/api/v1/agendamentos/`
- `/api/v1/prontuarios/`
- `/api/v1/evolucoes-clinicas/`
- `/api/v1/odontogramas/`
- `/api/v1/registros-odontograma/`
- `/api/v1/planos-tratamento/`
- `/api/v1/itens-plano-tratamento/`
- `/api/v1/orcamentos/`
- `/api/v1/itens-orcamento/`
- `/api/v1/parcelas/`
- `/api/v1/pagamentos/`

Usuarios comuns acessam apenas dados da propria clinica. Staff/admin pode administrar globalmente nesta etapa.

## Agenda

Cada clinica possui configuracoes comerciais basicas:

- `slug`: identificador publico unico da clinica.
- `timezone`: fuso usado para interpretar expediente e validacoes locais, por padrao `America/Maceio`.
- `antecedencia_minima_cancelamento_horas`: prazo minimo para paciente cancelar um agendamento.
- `duracao_padrao_consulta_minutos`: duracao usada quando nao ha procedimento ou duracao informada.

O expediente semanal e gerenciado em `/api/v1/horarios-funcionamento/`. Staff/admin pode criar, editar e remover horarios. Usuarios comuns autenticados podem consultar apenas horarios da propria clinica.

Bloqueios manuais da agenda da clinica sao gerenciados em `/api/v1/bloqueios-agenda/`. Eles representam fechamentos, manutencoes, feriados locais ou outros intervalos em que a clinica nao atende.

Indisponibilidades de dentistas sao gerenciadas em `/api/v1/indisponibilidades-dentistas/`. Elas representam ferias, afastamentos ou intervalos em que um dentista especifico nao atende.

Na fase atual, escrita nesses endpoints e administrativa. Usuarios comuns autenticados podem consultar apenas registros vinculados a propria clinica.

Agendamentos respeitam o timezone e o expediente ativo da clinica:

- dia sem expediente retorna `400 Bad Request`;
- inicio antes da abertura retorna `400 Bad Request`;
- inicio depois do fechamento retorna `400 Bad Request`;
- agendamento que termina depois do fechamento retorna `400 Bad Request`;
- agendamento durante bloqueio ativo da clinica retorna `409 Conflict`;
- agendamento durante indisponibilidade ativa do dentista retorna `409 Conflict`;
- sobreposicoes com outro agendamento ativo do mesmo dentista continuam retornando `409 Conflict`.

Status oficiais de agendamento:

- `AGENDADA`
- `CONFIRMADA`
- `EM_ATENDIMENTO`
- `CONCLUIDA`
- `CANCELADA`
- `NAO_COMPARECEU`

Agendamentos nao devem ser alterados por `PATCH` ou `PUT` generico. Use as acoes explicitas:

- `POST /api/v1/agendamentos/{id}/cancelar/`
- `POST /api/v1/agendamentos/{id}/reagendar/`
- `POST /api/v1/agendamentos/{id}/confirmar/`
- `POST /api/v1/agendamentos/{id}/concluir/`
- `POST /api/v1/agendamentos/{id}/marcar-falta/`

Conflitos de horario e sobreposicoes retornam `409 Conflict`.

Pacientes nao podem cancelar consultas fora da antecedencia minima configurada na clinica. Staff/admin pode cancelar mesmo fora desse prazo.

## Cadastro publico por clinica

Pacientes podem ser cadastrados em contexto de clinica pelo slug:

- `POST /api/v1/clinicas/{slug}/pacientes/`

Esse endpoint e publico e sempre cria usuario `PACIENTE`, vinculado automaticamente a clinica do slug. Campos `tipo` e `clinica` enviados no payload nao permitem elevacao de privilegio nem troca de contexto.

Clinicas inativas rejeitam cadastro publico. Slugs inexistentes retornam `404 Not Found`.

## Convites de cadastro de pacientes

Staff/admin gera convites em `POST /api/v1/convites-pacientes/` para uma clinica ativa. A resposta de criacao retorna o token e o endpoint publico de consumo:

- `POST /api/v1/convites-pacientes/{token}/cadastrar/`

O convite e de uso unico, possui expiracao e vincula o paciente automaticamente a clinica que o gerou. O cadastro por token continua criando apenas usuarios `PACIENTE`; campos `tipo` e `clinica` no payload nao alteram privilegios nem contexto.

Fluxo atual:

1. A recepcao gera o convite.
2. O sistema retorna token e link/endpoint de cadastro.
3. A recepcao copia e envia o link manualmente ao paciente.
4. O paciente conclui o cadastro.
5. O convite recebe `usado_em` e nao pode ser reutilizado.

`FRONTEND_BASE_URL`, quando configurada, permite retornar um link amigavel no formato `/cadastro?convite={token}`. Sem essa variavel, a resposta retorna o endpoint publico da API. O frontend atual nao foi alterado para consumir esse parametro.

Envio real por WhatsApp, e-mail ou qualquer integracao externa ainda nao esta implementado nesta sprint.

## Prontuario odontologico (Sprint 9)

Cada paciente possui no maximo um prontuario ativo por clinica. A criacao de prontuario e administrativa (`staff/admin`) e sempre valida que paciente e clinica pertencem ao mesmo contexto. Prontuarios e evolucoes nao possuem exclusao fisica pela API.

- `GET/POST /api/v1/prontuarios/`
- `GET/PATCH /api/v1/prontuarios/{id}/anamnese/`
- `GET /api/v1/prontuarios/{id}/evolucoes/`
- `GET/POST /api/v1/evolucoes-clinicas/`

Pacientes podem consultar apenas o proprio prontuario, mas nao alteram anamnese e nao acessam ou escrevem evolucoes clinicas nesta primeira versao. Dentistas consultam prontuarios apenas da propria clinica e podem preencher ou atualizar anamnese; `staff/admin` mantem acesso global. Recursos de outra clinica retornam `404` para usuarios comuns.

Uma evolucao vincula de forma imutavel prontuario, agendamento e dentista. Dentistas so podem cria-la para o proprio atendimento; staff/admin tambem precisa informar um dentista que corresponda ao atendimento. O agendamento deve pertencer ao mesmo paciente e clinica do prontuario e estar em `EM_ATENDIMENTO` ou `CONCLUIDA`. Nao sao aceitos `AGENDADA`, `CONFIRMADA`, `CANCELADA` ou `NAO_COMPARECEU`.

Esta fase cobre anamnese textual (alergias, medicamentos, condicoes, antecedentes e observacoes), autoria e datas de criacao/atualizacao. Odontograma, plano de tratamento, prescricoes, atestados, anexos, exames e radiografias permanecem etapas futuras.

## Odontograma e plano de tratamento (Sprint 10)

O odontograma e clinicamente vinculado ao prontuario, com uma instancia ativa por prontuario. A clinica e a autoria sao inferidas pelo backend; pacientes apenas consultam dados do proprio prontuario. Registros odontologicos sao historicos: uma nova condicao cria outro registro, sem sobrescrever nem excluir o anterior.

A numeracao aceita dentes permanentes FDI: `11-18`, `21-28`, `31-38` e `41-48`. Faces: `VESTIBULAR`, `LINGUAL`, `PALATINA`, `MESIAL`, `DISTAL`, `OCLUSAL`, `INCISAL`, `GERAL`. Condicoes: `SAUDAVEL`, `CARIE`, `RESTAURADO`, `AUSENTE`, `FRATURADO`, `IMPLANTE`, `COROA`, `TRATAMENTO_CANAL`, `EXTRACAO_INDICADA`, `PROTESE` e `OUTRO`.

Planos de tratamento iniciam em `RASCUNHO`; seu status so muda por acoes explicitas: `propor`, `aprovar`, `iniciar`, `concluir` e `cancelar`. As transicoes permitidas sao `RASCUNHO -> PROPOSTO -> APROVADO -> EM_ANDAMENTO -> CONCLUIDO`, com cancelamento a partir de `PROPOSTO`, `APROVADO` ou `EM_ANDAMENTO`. Planos `CONCLUIDO` e `CANCELADO` nao aceitam novos itens. Um item pode referenciar um procedimento da mesma clinica, mas esta sprint nao implementa financeiro, anexos ou interface visual do odontograma.

## Financeiro: orcamentos e pagamentos manuais (Sprint 11)

Orcamentos iniciam em `RASCUNHO` e possuem itens, desconto e totais calculados exclusivamente no backend com `Decimal` e arredondamento de duas casas. Os campos `subtotal`, `total`, `valor_pago` e `saldo` sao somente leitura. Descontos podem ser `NENHUM`, `VALOR` ou `PERCENTUAL`; percentual fica entre 0 e 100, e desconto em valor nao pode superar o subtotal.

As transicoes sao explicitas: `RASCUNHO -> ENVIADO -> APROVADO` ou `REJEITADO`, e cancelamento a partir de `RASCUNHO` ou `ENVIADO`. Orcamento aprovado exige ao menos um item. Aprovacao, rejeicao e cancelamento sao administrativos; nao ha alteracao direta de status por `PATCH`/`PUT`. Orcamentos aprovados, rejeitados, cancelados ou vencidos nao aceitam itens. Nao ha exclusao fisica pela API.

Parcelas sao geradas por `POST /api/v1/orcamentos/{id}/parcelar/` apenas para orcamento aprovado. O payload recebe `quantidade_parcelas`, `primeiro_vencimento` e `intervalo_dias` opcional. A diferenca de arredondamento fica na ultima parcela, e o fluxo nao permite gerar parcelas duas vezes.

Pagamentos sao registros manuais em `POST /api/v1/pagamentos/`, feitos por staff/admin, com formas `DINHEIRO`, `PIX`, `CARTAO_CREDITO`, `CARTAO_DEBITO`, `TRANSFERENCIA` ou `OUTRO`. `PIX` e cartao sao apenas classificacoes do registro: esta sprint nao integra gateway, nao gera Pix real, nao emite documento fiscal e nao faz conciliacao, estorno ou cobranca recorrente. Cada pagamento atualiza o valor pago e saldo do orcamento; a parcela e marcada como `PAGA` quando seu saldo chega a zero. Uma `referencia_externa` opcional e unica por clinica para reduzir repeticao acidental.

Pacientes consultam somente os proprios orcamentos, parcelas e pagamentos, sem escrita. Dentistas consultam apenas dados da propria clinica e podem elaborar orcamentos e itens; pagamentos e aprovacao financeira permanecem administrativos. Clinica, paciente, autoria e valores calculados sao inferidos ou protegidos pelo backend, e recursos de outra clinica retornam `404` para usuarios comuns.

## Paginacao

Listagens usam a paginacao padrao do DRF:

```json
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": []
}
```

## Documentacao OpenAPI

- `/api/schema/`
- `/api/docs/`
- `/api/redoc/`

## Desenvolvimento

Variaveis principais:

- `ENVIRONMENT`: `development`, `test` ou `production`
- `SECRET_KEY`: obrigatoria em producao
- `DEBUG`: `True` ou `False`
- `DATABASE_URL`: URL do banco; se ausente fora de producao, usa SQLite local
- `USE_SQLITE_FOR_TESTS`: `True` para testes locais em SQLite; `False` para usar `DATABASE_URL`
- `ALLOWED_HOSTS`: lista separada por virgula
- `CORS_ALLOWED_ORIGINS`: lista separada por virgula
- `FRONTEND_BASE_URL`: URL base opcional para montar link amigavel de convite

Copie `.env.example` para `.env` no desenvolvimento local e ajuste os valores.

Instale as dependencias:

```powershell
pip install -r requirements.txt
```

Rode migrations e servidor:

```powershell
python manage.py migrate
python manage.py runserver
```

Rode testes:

```powershell
python manage.py test api
```

Lint:

```powershell
ruff check .
```

Coverage:

```powershell
coverage run manage.py test api
coverage report
```

## Docker

O compose de desenvolvimento fica em `back/docker-compose.yml` e sobe Django + PostgreSQL:

```powershell
docker compose up --build
```

O backend fica em `http://localhost:8000`.

Testes usando PostgreSQL via Docker:

```powershell
docker compose run --rm -e USE_SQLITE_FOR_TESTS=False backend python manage.py test api
```

## Health check

- `/api/health/`

Retorna apenas estado basico da aplicacao e do banco, sem expor segredos.

## Notificacoes

A Sprint 13 registra notificacoes e lembretes de consulta de forma sincrona, sem enviar mensagens a provedores externos.

Arquitetura atual: `Agenda -> NotificationService -> Banco de Dados -> Historico`.

Ao criar uma consulta, sao registrados lembretes pendentes para 24 h e 2 h antes. Reagendamentos cancelam os pendentes anteriores e criam novos; cancelamentos tambem os cancelam. A confirmacao de presenca registra apenas o estado interno e a auditoria.

Os endpoints sao `/api/v1/templates-mensagem/`, `/api/v1/notificacoes/`, `/api/v1/preferencias-comunicacao/` e `/api/v1/agendamentos/{id}/confirmar-presenca/`. Templates podem ser globais ou por clinica; pacientes veem apenas o proprio historico e alteram somente as proprias preferencias.

Arquitetura futura planejada: `Agenda -> NotificationService -> Celery -> Redis -> Adaptadores -> WhatsApp/Email/SMS/Push`. Redis, Celery, Kafka, WhatsApp, Email, SMS e Push reais nao sao integrados nesta sprint.

## Arquivos clinicos, consentimento e privacidade

- `POST/GET /api/v1/arquivos-clinicos/` recebe PDF, JPEG, PNG ou WEBP; o limite padrao e 10 MB e pode ser ajustado por `ARQUIVO_CLINICO_MAX_TAMANHO_BYTES`.
- O upload valida extensao, MIME, assinatura basica, tamanho e nome. O arquivo e armazenado pelo `FileField` do Django em caminho interno aleatorio por clinica/paciente; nao ha URL publica.
- `GET /api/v1/arquivos-clinicos/{id}/download/` exige JWT, aplica o isolamento por clinica/paciente e cria auditoria. O storage atual e local; o modelo permanece desacoplado para futura configuracao com `django-storages`/S3, sem credenciais AWS nesta sprint.
- Termos versionados ficam em `/api/v1/termos-consentimento/`; aceite e revogacao preservam historico em `/api/v1/consentimentos/`.
- `POST /api/v1/usuarios/{id}/exportar-dados/` produz uma exportacao JSON protegida. Senhas, tokens, segredos e caminhos de storage nao sao incluidos. Dados financeiros sao incluidos apenas para staff/admin.
- `POST /api/v1/usuarios/{id}/solicitar-anonimizacao/` registra a solicitacao; nao apaga prontuario, financeiro ou historico clinico automaticamente.

Esta base tecnica nao declara conformidade juridica integral com a LGPD. Regras de retencao devem ser validadas juridicamente antes da producao. Antimalware externo, assinatura digital certificada, OCR e URLs presigned/S3 nao fazem parte desta sprint.

## CI

O workflow `Backend CI` roda em push e pull request para mudancas do backend. Ele instala dependencias, sobe PostgreSQL, roda lint, verifica migrations, executa migrations, testes e coverage. Nao ha deploy configurado nesta sprint.
