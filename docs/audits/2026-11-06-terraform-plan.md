# План: вся инфраструктура Another Judo Rating под Terraform

Дата: 2026-11-06. Это план, ничего не применено, не импортировано и не изменено.
Черновик `.tf`-файлов (проверен `terraform validate` против реальных схем провайдеров,
без бэкенда и без обращений к API) лежит вне репозиториев:
`/Users/macbook/.claude/jobs/eb258c77/tmp/terraform-plan/`. Секреты в отчёте
только по именам переменных.

## 0. Что проверено и как

Прочитано: все workflow бэкенда (`update`, `release`, `alert`, `tests`, `backup`,
`loadtest`, `watchdog`), `.github/*.sh`, `cloudflare/{worker.js,wrangler.toml,README.md}`,
`README.md`, `.gitignore`; у фронтенда `vercel.json`, `next.config.ts`, `.env.example`,
`src/lib/api.ts`, `src/app/api/revalidate/route.ts`, `.github/workflows/check.yml`,
`docs/seo/2026-11-04-strategy.md`; прежние аудиты (`docs/audits/2026-11-0{3,4,5}-*.md`);
прототипы `~/Projects/alivewater/terraform/` (github 6.13 + supabase 1.11 + cloudflare
4.52, Pages + Worker + секреты Actions, локальный state) и `~/Projects/ajr/infra/`
(только `supabase_project` + `supabase_settings{ssl_enforcement}`, локальный state,
заметка «переехать в GCS»; в backlog бэкенда причин отказа нет — судя по датам,
проект `ajr` 17.10 был заменён проектом `vrnpqahtpjrlmlrkzbja` 28.10, созданным руками).

Read-only запросы (только GET / `read_only: true`):

| Система | Чем | Что увидели | Чего не хватило |
|---|---|---|---|
| Supabase | `SUPABASE_ACCESS_TOKEN` (read-only, **привязан к проекту**: `/v1/organizations` → `[]`, org → 403) | project, postgrest, postgres config, network, ssl, pooler, backups, api-keys (без значений), auth, storage, advisors, `pg_db_role_setting`, `pg_settings` | ничего существенного |
| Vercel | `VERCEL_TOKEN` | project `ajr-web-8jes`, env (ключи, не значения), домены, protection | `/v2/user`, `/v2/teams/{id}` → 403/404: токен без прав на аккаунт/команду (для Terraform нужен **team-scoped** токен) |
| GitHub | `GITHUB_DISPATCH_TOKEN` (fine-grained, только Actions RW) | оба репо (публичные), ruleset бэкенда | secrets/variables, actions permissions, dependabot/code-scanning/secret-scanning состояние, org settings → 403: нужны **Administration: read**, **Secrets: read** |
| Cloudflare | токена нет, wrangler не залогинен | только публичный DNS (`dig`) и заголовки ответа | zone id, account id, id записей, тип записей под прокси, настройки зоны, bindings Worker’а |

### Состояние на 2026-11-06 (факты, не из документации)

- **Supabase** `vrnpqahtpjrlmlrkzbja`, org `xhihsrgzeswkwkvceypf`, `eu-central-1`, PG 17.11.0.003
  (доступен апгрейд до .018), free (addons: none). PostgREST: `db_schema=api`, `max_rows=1000`,
  `db_extra_search_path=public,extensions`. Postgres-overrides через платформу: **только**
  `shared_buffers=64MB` (в `pg_settings` 8192×8kB, `source=configuration file`); остальное
  дефолты инстанса (`statement_timeout=120s`, `work_mem=2184kB`, `max_connections=60`,
  `jit=off`). Role-settings (сделаны руками, ни одна миграция их не ставит):
  `anon statement_timeout=3s`, `authenticated statement_timeout=8s`. Network: `0.0.0.0/0`,
  `::/0`. SSL enforcement: **off**. Pooler: transaction mode, 6543, `default_pool_size=null`
  (job использует session mode 5432 — README). Backups: `walg_enabled`, PITR off, список пуст
  (free). Auth: дефолты (`site_url=http://localhost:3000`, signup открыт) — сайт auth не
  использует. API keys: legacy anon/service_role + publishable `default` + secret `default` +
  secret `metrics` (04.11). Advisors: 2 WARN (`ajr.result_label` search_path; SECURITY DEFINER
  `api.athlete`).
- **Vercel** team `team_gIgeCP6dRhrKksc1Qqew2mtx`, project `prj_Cwj1Z8hoJhtwS3lqJgsLHFp5r3Wi`
  («ajr-web-8jes», nextjs, node 24.x, git: `anotherjudorating/ajr-web`, production branch
  `main`). `autoAssignCustomDomains=false`, `gitForkProtection=true`,
  `ssoProtection=all_except_custom_domains`, `oidcTokenConfig={enabled,team}`,
  `gitComments={onCommit:false,onPullRequest:true}`, `productionDeploymentsFastLane=true`,
  `resourceConfig={fluid:true, functionDefaultRegions:["iad1"]}` — **дефолт проекта iad1**,
  а `vercel.json` задаёт `fra1` и реально работает (`x-vercel-id: fra1::…`). Env:
  `SUPABASE_URL` (sensitive, prod/preview/dev, id `HisGjwDEbnnLMum9`), `SUPABASE_KEY`
  (sensitive, все, `6AXGYAnANUI6pmBx`), `REVALIDATE_SECRET` (sensitive, prod,
  `iQoyvo9JYvGeEqkF`). Домены: `www.anotherjudorating.com`, `anotherjudorating.com` → 308 на
  www, `ajr-web-8jes-delta.vercel.app`. Web Analytics и Speed Insights включены.
- **GitHub** org `anotherjudorating` (id 348801882), репо `ajr-backend` (1435677012) и
  `ajr-web` (1435679328), оба публичные, wiki/projects включены, environments нет.
  Ruleset только у бэкенда: id 26053455, имя **«maun»** (опечатка), `~DEFAULT_BRANCH`,
  правила deletion, non_fast_forward, pull_request (0 approvals, merge/squash/rebase,
  `require_extra_approval_for_unattributed_changes=true`), required check `tests`
  (integration 15368 = Actions). **У `ajr-web` ruleset нет.** Секреты, которые читают
  workflow: только `DATABASE_URL` и `REVALIDATE_SECRET` (оба в `ajr-backend`); `vars.*` не
  используются; `check.yml` фронтенда секретов не читает. Dependabot: `dependabot.yml` в
  обоих репо (uv+actions; npm).
- **Cloudflare**: NS `amir/nola.ns.cloudflare.com`; apex и www отвечают IP прокси
  (`104.21.35.205`, `172.67.179.144` + AAAA), `server: cloudflare`, то есть записи
  проксированы на Vercel; TXT на apex: `google-site-verification=Sxy6Fa…`,
  `yandex-verification: a1673926f4c55bb0`; MX/CAA нет. Worker `ajr-update-trigger`:
  `compatibility_date=2026-10-01`, `workers_dev=false`, var `GITHUB_REPO`, секрет
  `GITHUB_TOKEN`, cron `*/15 * * * *`, `40 2 * * *`, `10 3 * * 1`.
- Локально: Terraform **1.14.8**, Docker, Node 21; `tofu` нет; `gh` CLI нет.
  Провайдеры (registry, 06.11): cloudflare **5.28.1**, github **6.13.0**, supabase
  **1.11.0**, vercel **5.25.0**.

## 1. По провайдерам: что покрывается, что нет, как импортировать

### 1.1 GitHub — `integrations/github ~> 6.13`

| Есть сейчас | Ресурс | Import ID |
|---|---|---|
| репо `ajr-backend`, `ajr-web` (описание, homepage, visibility, wiki/projects/issues, merge-методы, delete-branch-on-merge) | `github_repository` | `ajr-backend`, `ajr-web` |
| ruleset на main (бэкенд) | `github_repository_ruleset` | `ajr-backend:26053455` |
| ruleset на main (фронт) — **нет, создаётся** (required check `check`) | `github_repository_ruleset` | — |
| секреты Actions `DATABASE_URL`, `REVALIDATE_SECRET` | `github_actions_secret` | `ajr-backend:DATABASE_URL`, `ajr-backend:REVALIDATE_SECRET` (значение после импорта не читается — первый apply перезапишет тем же) |
| Dependabot security updates | `github_repository_dependabot_security_updates` | `ajr-backend`, `ajr-web` |
| разрешённые actions | `github_actions_repository_permissions` | `ajr-backend`, `ajr-web` |
| secret scanning + push protection | блок `security_and_analysis` в `github_repository` (на публичном репо `advanced_security` задать нельзя — всегда включён) | вместе с репо |

Не управляется Terraform’ом (остаётся кодом или документом):
- **Dependabot version updates** — это файлы `.github/dependabot.yml` (уже код).
- **CodeQL default setup** — ресурса в провайдере нет. Держать как документированный шаг
  (`gh api -X PATCH /repos/{o}/{r}/code-scanning/default-setup -f state=configured`) в
  `docs/infrastructure.md`; или перейти на `codeql.yml` workflow (тогда это код).
- **Default workflow permissions** («Read repository contents», «Allow Actions to create
  PRs») — ресурса нет; workflow и так объявляют `permissions:` явно, что важнее.
- **Org settings** (`github_organization_settings`) — требует `billing_email` и ведёт ~30
  полей; для одного владельца не стоит включать. Org-уровневые rulesets/секретов нет.
- Ruleset: поле `require_extra_approval_for_unattributed_changes` (API вернул `true`) у
  провайдера 6.13 отсутствует → возможен вечный diff; тогда `ignore_changes` или оставить
  как есть (провайдер поля не трогает).

Токен для Terraform: fine-grained PAT, resource owner `anotherjudorating`, репо
`ajr-backend` + `ajr-web`; Repository permissions: **Administration: Read and write**
(репо-настройки, rulesets, actions permissions, security), **Secrets: Read and write**,
**Variables: Read and write** (на будущее), **Metadata: Read** (автоматически),
**Contents: Read**. Organization permissions не нужны, пока org settings не управляются.
Срок — максимум 1 год, запись в календарь (как у `GITHUB_TOKEN` Worker’а). Альтернатива
без срока — GitHub App (провайдер поддерживает `app_auth`), но это ещё одна сущность;
для одного владельца PAT достаточно.

### 1.2 Supabase — `supabase/supabase ~> 1.11`

| Есть сейчас | Ресурс / поле | Import ID |
|---|---|---|
| проект `ajr` | `supabase_project` (`prevent_destroy`, `ignore_changes=[database_password, instance_size]`) | `vrnpqahtpjrlmlrkzbja` |
| Data API: exposed schema `api`, max_rows 1000, extra search path | `supabase_settings.api` (JSON `db_schema`, `max_rows`, `db_extra_search_path`) | `vrnpqahtpjrlmlrkzbja` (один ресурс на все категории) |
| `shared_buffers=64MB` (поставлен CLI) | `supabase_settings.database` (JSON; тот же API, что `supabase postgres-config update`; поля: `shared_buffers`, `work_mem`, `effective_cache_size`, `statement_timeout`, `max_connections`, …) | тот же |
| network restrictions | `supabase_settings.network` (`restrictions=[…]`) | тот же |
| SSL enforcement | `supabase_settings.ssl_enforcement` | тот же |
| auth, pooler, storage | те же категории JSON — **намеренно не управлять** (сайт без auth; pooler на дефолтах) | — |
| publishable key | `data.supabase_apikeys`; доп. ключи (`metrics`) — `supabase_apikey` (опционально) | — |

**Важно:** `supabase_settings.database.statement_timeout` — это серверный дефолт
(120 с сегодня, не переопределён), а не 3 с для `anon`. **Role-level**
`statement_timeout` (`anon` 3s, `authenticated` 8s) — объект базы, Terraform его не
видит. Держать кодом как Alembic-миграцию:

```python
# migrations/versions/xxxx_role_timeouts.py
def upgrade():
    op.execute("alter role anon set statement_timeout = '3s'")
    op.execute("alter role authenticated set statement_timeout = '8s'")
def downgrade():
    op.execute("alter role anon reset statement_timeout")
    op.execute("alter role authenticated reset statement_timeout")
```

плюс тест рядом с `test_site_role_cannot_read_our_tables` (`select current_setting('statement_timeout')`
под `set role anon`). Это закрывает замечание M4 аудита 11-03 («не всё из миграций»).

Не управляется: бэкапы (free: ежедневный WAL-G, PITR off, расписания нет — только
`backup.yml`), апгрейд Postgres (`/upgrade`, ручное действие), compute add-on (платно),
custom domain (Pro). Free-план ограничений для нужных полей не создаёт: network
restrictions (`entitlement: allowed`), SSL enforcement, postgres config — всё применимо.

Токен: `supabase.com/dashboard/account/tokens` → **Generate new token** «terraform».
Нынешний read-only токен видит только проект — значит, в дашборде токены можно
ограничивать проектом и правами; Terraform’у нужен такой же **project-scoped, но
read-write** (если скоупинг доступен; иначе полный PAT). `database_password` провайдер
требует как обязательное поле, но API его не возвращает: подставить пароль из
нынешнего `DATABASE_URL` (вариант `supabase_database_password`), **не** сбрасывать —
сброс сломает `DATABASE_URL` всех workflow.

### 1.3 Vercel — `vercel/vercel ~> 5.25`

| Есть сейчас | Ресурс | Import ID |
|---|---|---|
| проект (framework, node, git-repo, production branch, auto-assign domains **off**, fork protection, deployment protection «Standard (new)» = API `all_except_custom_domains`, OIDC, git comments, fast lane, fluid, regions) | `vercel_project` | `team_gIgeCP6dRhrKksc1Qqew2mtx/prj_Cwj1Z8hoJhtwS3lqJgsLHFp5r3Wi` |
| `www.anotherjudorating.com` | `vercel_project_domain` | `team_…/prj_…/www.anotherjudorating.com` |
| `anotherjudorating.com` → 308 www | `vercel_project_domain` (`redirect`, `redirect_status_code=308`) | `team_…/prj_…/anotherjudorating.com` |
| `SUPABASE_URL`, `SUPABASE_KEY`, `REVALIDATE_SECRET` | `vercel_project_environment_variable` (`sensitive=true`, `value_wo` — значение не попадает в state) | `team_…/prj_…/HisGjwDEbnnLMum9`, `…/6AXGYAnANUI6pmBx`, `…/iQoyvo9JYvGeEqkF` |

Не управляется / остаётся в коде:
- **«Только main собирается»** — `vercel.json` `git.deploymentEnabled`; **регион fra1** —
  `vercel.json` `regions`. Это код фронтенда; Terraform не дублирует. Дефолт проекта
  `functionDefaultRegions=["iad1"]` расходится с реальностью — черновик ставит
  `resource_config.function_default_regions=["fra1"]` (одно безвредное изменение при
  первом apply; можно и не трогать).
- Web Analytics / Speed Insights toggles — полей у `vercel_project` нет; по-прежнему
  дашборд (и пакеты в `package.json`).
- `*.vercel.app` домен — системный, не импортируется.
- Значения env типа `sensitive` API не отдаёт → после импорта первый план покажет
  `update in-place` каждого значения; это ожидаемо.

Токен: `vercel.com/account/settings/tokens` → Create, **Scope: команда владельца**
(та, где `team_gIgeCP6dRhrKksc1Qqew2mtx`), срок по вкусу (365 д.). Нынешний
`VERCEL_TOKEN` не читает ни user, ни team — для Terraform не годится. В провайдере
`team = var.vercel_team_id`.

### 1.4 Cloudflare — `cloudflare/cloudflare ~> 5.28` (не 4.52 как в alivewater)

v5 — переписанный провайдер (ресурсы `cloudflare_dns_record`, `cloudflare_zone_setting`
по одному на настройку, `cloudflare_workers_script` с `content_file`+`content_sha256`
и списком `bindings`, `cloudflare_r2_bucket`). v4 в maintenance; начинать новый код
на v4 нет смысла. Паттерн alivewater (`plain_text_binding`/`secret_text_binding`,
`cloudflare_workers_cron_trigger.schedules=[…]`) переносится 1:1 в v5-синтаксис
(черновик `cloudflare.tf`).

| Есть сейчас | Ресурс | Import ID |
|---|---|---|
| зона `anotherjudorating.com` | **`data "cloudflare_zone"`** (не ресурс: нечего настраивать, а `destroy` ресурса удалил бы зону) | — |
| apex и www → Vercel (proxied) | `cloudflare_dns_record` ×2 | `<zone_id>/<record_id>` (id и тип — из `GET /zones/{zone_id}/dns_records`) |
| TXT Google, TXT Yandex | `cloudflare_dns_record` ×2 | то же |
| настройки зоны: ssl, always_use_https, min_tls_version, rocket_loader, email_obfuscation, mirage, automatic_https_rewrites, brotli | `cloudflare_zone_setting` ×8 (`for_each`) | `<zone_id>/<setting_id>` |
| Worker `ajr-update-trigger` (код, compat date, var `GITHUB_REPO`) | `cloudflare_workers_script` (`content_file=../cloudflare/worker.js`, `keep_bindings=["secret_text"]`) | `<account_id>/ajr-update-trigger` |
| 3 cron | `cloudflare_workers_cron_trigger` | `<account_id>/ajr-update-trigger` |
| `workers_dev=false` | `cloudflare_workers_script_subdomain` (`enabled=false`) | `<account_id>/ajr-update-trigger` |
| бакет state `ajr-terraform-state` (создаётся руками до `init`) | `cloudflare_r2_bucket` (`prevent_destroy`) | `<account_id>/ajr-terraform-state/default` |

Не управляется:
- **Crawler Hints** (Caching → Configuration) — в провайдере ресурса нет (это flags
  API). Остаётся ручной настройкой, записанной в `docs/infrastructure.md`; раз в квартал
  глазами. (Альтернатива — IndexNow-пинг из `/api/revalidate`, тогда тумблер не нужен.)
- **Managed robots.txt / AI-боты** — есть `cloudflare_bot_management`
  (`is_robots_txt_managed`, `ai_training`, …), но ресурс пишет весь объект, часть полей
  зависит от плана; не включать, пока SEO-аудит не решил судьбу robots.txt.
- **Секрет Worker’а `GITHUB_TOKEN`**: решение — **не** класть в Terraform. Upload через
  Terraform заменяет все bindings, которых нет в конфиге; `keep_bindings=["secret_text"]`
  сохраняет секрет, положенный `wrangler secret put`. Ротация раз в год — как сегодня
  (`cloudflare/README.md`), без state. Если захочется — `var.github_dispatch_token` +
  binding `secret_text` (секрет окажется в state).
- `wrangler deploy` **перестаёт** быть путём деплоя Worker’а (см. 3.3); `wrangler.toml`
  остаётся для `wrangler dev`.

Токен (My Profile → API Tokens → Create Token → Custom): **Zone › DNS › Edit**,
**Zone › Zone Settings › Edit**, **Zone › Zone › Read**, **Account › Workers Scripts ›
Edit**, **Account › Workers R2 Storage › Edit** (ресурс бакета), **Account › Account
Settings › Read**; Zone Resources: Include › Specific zone › `anotherjudorating.com`;
Account Resources: только аккаунт владельца. (Bot Management Edit — только если
решат управлять robots-тумблером.) Это **отдельный** токен от R2-токена state (ниже):
у R2 API token свой формат (Access Key ID / Secret).

## 2. Раскладка

**Где:** каталог `ajr-backend/terraform/` (не отдельный репо). Причины: бэкенд уже
ops-репо (workflows, `cloudflare/`, аудиты), Worker’у нужен
`${path.module}/../cloudflare/worker.js`, один PR-процесс и один `alert`-паттерн;
`.gitignore` бэкенда уже игнорирует `.terraform/`, `*.tfstate*`, `*.tfvars`
(и разрешает `*.tfvars.example`). Terraform будет управлять и самим `ajr-backend` — это
нормально (alivewater делает то же). Отдельный репо имел бы смысл при нескольких
командах/окружениях; здесь одно окружение и один человек.

**Плоско, без модулей**, один root module, один state: ~25 ресурсов, модули ничего не
дали бы. Файлы: `versions.tf`, `providers.tf`, `variables.tf`, `github.tf`,
`supabase.tf`, `vercel.tf`, `cloudflare.tf`, `imports.tf` (на время импорта),
`outputs.tf`, `terraform.tfvars.example`, `backend.hcl.example` (черновик).

**Окружения:** только production. Без workspaces.

**Версии:** `required_version = "~> 1.14"`, провайдеры `~> 6.13 / ~> 1.11 / ~> 5.25 /
~> 5.28`, `.terraform.lock.hcl` коммитится (как в alivewater). Dependabot для
`terraform` ecosystem — добавить в `dependabot.yml` (directory `/terraform`).

**Секреты → Terraform.** Переменные `sensitive = true`; значения — из
`~/.config/ajr/terraform.env` (chmod 600, экспорт `TF_VAR_*` и `AWS_*` для R2), в том
же стиле, что нынешние `~/.config/ajr/*.env`; `terraform.tfvars` (git-ignored) — как
запасной вариант. В Actions (раздел 3) — repository secrets `TF_*` + `R2_*`. Никаких
значений в `.tf`.

Переменные-секреты: `github_token`, `supabase_access_token`, `vercel_api_token`,
`cloudflare_api_token`, `supabase_database_password`, `revalidate_secret`,
`supabase_publishable_key`, (`github_dispatch_token` — пусто). Переменные-идентификаторы
(дефолты в `variables.tf`): org/repo, `supabase_project_ref`, `supabase_organization_id`,
`vercel_team_id`, `vercel_project_id`; без дефолта — `cloudflare_account_id`,
`cloudflare_zone_id`.

Одна переменная `revalidate_secret` питает и GitHub-секрет, и Vercel env: ротация =
смена значения + один apply, без окна рассинхрона. `DATABASE_URL` собирается из
`data.supabase_pooler` + пароль (как в alivewater), в формате README (session mode
5432, `postgresql+psycopg://`); включение SSL — в том же apply добавляется
`?sslmode=require`.

**Backend (state в R2):**

```hcl
backend "s3" {
  bucket = "ajr-terraform-state"
  key    = "production/terraform.tfstate"
  region = "auto"
  # endpoints = { s3 = "https://<account_id>.r2.cloudflarestorage.com" }  # через -backend-config=backend.hcl
  use_lockfile                = true   # блокировка .tflock через If-None-Match: *, R2 это поддерживает (проверить в шаге 0)
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_s3_checksum            = true
  use_path_style              = true
}
```

Учётные данные — `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` = пара R2 API token.
Блокировка: Terraform ≥ 1.10 умеет lock-файл в S3 без DynamoDB; R2 документирует
`If-None-Match: *` на `PutObject`, на чём это и построено — но проверить двумя
параллельными `plan` в шаге 0; если не сработает, снять `use_lockfile` (один оператор,
плюс `concurrency: terraform` в workflow — достаточно). Версионирования у R2 нет:
перед каждым apply `terraform state pull > ~/.config/ajr/state-backup/$(date +%F).json`
(одна строка в `Makefile`/`justfile`), state содержит секреты — папка 700.

## 3. Процесс

### 3.1 Кто применяет
**Локально владелец**: `plan` → читает → `apply`. Apply из Actions не делать:
нужны были бы все write-токены в секретах репо и environment с required reviewers;
для одного человека это шаг назад (локально токены в `~/.config/ajr`, как сейчас).

### 3.2 Actions: план и дрейф
Черновик `workflows/terraform.yml`: (а) `pull_request` с `paths: [terraform/**]` —
план в summary; (б) `schedule` ежедневно 05:30 UTC (после ночного прогона) — план с
`-detailed-exitcode`; код 2 открывает/комментирует issue «Infrastructure drifted», код 0
закрывает (ровно логика `alert.yml`/`watchdog.yml`); (в) `workflow_dispatch`.
`concurrency: terraform`, `permissions: contents: read, issues: write`. Нужны секреты
репо: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `TF_GITHUB_TOKEN`,
`TF_SUPABASE_ACCESS_TOKEN`, `TF_VERCEL_API_TOKEN`, `TF_CLOUDFLARE_API_TOKEN`,
`TF_SUPABASE_DATABASE_PASSWORD`, `TF_SUPABASE_PUBLISHABLE_KEY`, существующий
`REVALIDATE_SECRET`; variables `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_ZONE_ID`.
Цена: те же write-токены лежат в GitHub secrets (план их не использует для записи, но
они там есть). Если это не нравится — оставить только локальный `plan` и ручной
еженедельный запуск; дрейф тогда ловится глазами. Компромисс: для дрейфа завести
**вторые, read-only** токены там, где платформа это умеет (Supabase — да, судя по
нынешнему; Cloudflare — да, `Read` вместо `Edit`; Vercel/GitHub — нет, PAT без записи
secrets не прочитает их имена… GitHub `Secrets: read` есть, Vercel — read-only токенов
нет). Рекомендация: начать с локального, добавить workflow на шаге 5, когда импорт
стабилен.

### 3.3 Кто чем владеет (чтобы не было драки)

| Объект | Владелец | Не трогает |
|---|---|---|
| Всё внутри Postgres (схемы, `api.*`, гранты, **role timeouts**) | Alembic (`release.yml`) | Terraform |
| Платформенные настройки Supabase (`shared_buffers`, exposed schema, network, SSL) | Terraform | `supabase` CLI / дашборд (после импорта) |
| Код сайта, `vercel.json` (регион, ветки), деплой | git → Vercel | Terraform (только project/domains/env) |
| Worker: код + crons + vars | Terraform (`content_file`, `filesha256`) | `wrangler deploy` — **убрать из README**, оставить `wrangler secret put` и `wrangler dev` |
| Секрет Worker’а `GITHUB_TOKEN` | `wrangler secret put` (ротация раз в год) | Terraform (`keep_bindings`) |
| Секреты Actions `DATABASE_URL`, `REVALIDATE_SECRET` | Terraform | ручное редактирование в Settings |
| DNS, zone settings | Terraform | дашборд |
| Crawler Hints, managed robots, Web Analytics, CodeQL setup | дашборд + `docs/infrastructure.md` | — |
| `dependabot.yml`, workflows | git | — |

Правило: что изменено руками в «территории Terraform» — ловит дрейф-план и попадает
либо в `.tf`, либо откатывается. Миграция, меняющая `alter role … set`, и Terraform
никогда не пересекаются (разные объекты).

## 4. Чеклист владельца (что сделать руками, один раз)

1. **Cloudflare — идентификаторы.** Dashboard → `anotherjudorating.com` → Overview →
   справа блок «API»: записать **Zone ID** и **Account ID** → `TF_VAR_cloudflare_zone_id`,
   `TF_VAR_cloudflare_account_id` (не секреты).
2. **R2 bucket.** Dashboard → R2 Object Storage → Create bucket: name
   `ajr-terraform-state`, Location: Automatic + hint **Western Europe (weur)**, без
   public access, без custom domain. (Free: 10 GB; state ~100 KB.)
3. **R2 API token.** R2 → Manage R2 API Tokens → Create API token: name
   `terraform-state`, Permissions **Object Read & Write**, «Specify bucket(s)» →
   `ajr-terraform-state`, TTL: Forever. Сохранить **Access Key ID** и **Secret Access
   Key** → `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` в `~/.config/ajr/terraform.env`.
4. **Cloudflare API token** (п. 1.4): My Profile → API Tokens → Create Token → Create
   Custom Token: Zone›DNS›Edit, Zone›Zone Settings›Edit, Zone›Zone›Read,
   Account›Workers Scripts›Edit, Account›Workers R2 Storage›Edit, Account›Account
   Settings›Read; Zone Resources: Specific zone `anotherjudorating.com` →
   `TF_VAR_cloudflare_api_token`. Сразу: `GET https://api.cloudflare.com/client/v4/zones/<zone_id>/dns_records`
   → записать **id и type** четырёх записей (apex, www, 2×TXT) в `imports.tf`.
5. **Supabase PAT.** `supabase.com/dashboard/account/tokens` → Generate new token
   «terraform»; если есть выбор scope — проект `ajr`, read-write →
   `TF_VAR_supabase_access_token`. Пароль БД — тот, что внутри `DATABASE_URL`
   (Settings → Database показывает только «reset»; **не сбрасывать**) →
   `TF_VAR_supabase_database_password`. Publishable key: Project Settings → API Keys →
   `sb_publishable_…` → `TF_VAR_supabase_publishable_key`.
6. **Vercel token.** `vercel.com/account/settings/tokens` → Create: name `terraform`,
   **Scope: команда** (не personal), Expiration 1 год → `TF_VAR_vercel_api_token`.
7. **GitHub PAT.** Settings → Developer settings → Personal access tokens →
   Fine-grained → Generate: Resource owner `anotherjudorating`, Only select
   repositories: `ajr-backend`, `ajr-web`; Repository permissions: Administration RW,
   Secrets RW, Variables RW, Contents R (Metadata R добавится сам); срок 1 год (запись
   в календарь рядом с токеном Worker’а) → `TF_VAR_github_token`. Если org требует
   одобрения PAT — одобрить в Org → Settings → Personal access tokens.
8. **Текущее значение `REVALIDATE_SECRET`** (оно есть у владельца; GitHub и Vercel его
   не покажут) → `TF_VAR_revalidate_secret`. Если утеряно — сгенерировать новое: один
   apply обновит оба места.
9. Завести `~/.config/ajr/terraform.env` (chmod 600) с перечисленным; `backend.hcl`
   (git-ignored) с `endpoints = { s3 = "https://<account_id>.r2.cloudflarestorage.com" }`.
10. Перед импортом выписать из дашбордов то, что токены не прочитали: GitHub → Settings
    → General (merge buttons, auto-delete branches) и → Actions → General (allowed
    actions) для обоих репо; Cloudflare → SSL/TLS mode, Speed → Rocket Loader, Scrape
    Shield → Email obfuscation (сверить с `local.zone_settings`; план покажет
    расхождения, но лучше знать заранее, что «должно быть»).
11. Позже, для workflow (шаг 5 раздела 5): те же значения как repository secrets
    `TF_*`, `R2_*` и variables `CLOUDFLARE_*` в `ajr-backend`.

Бесплатные планы ничего из нужного не блокируют: Supabase free — network restrictions,
SSL enforcement и postgres config доступны (проверено по API: `entitlement: allowed`,
`appliedSuccessfully`); Vercel Hobby — API проекта/доменов/env доступен; Cloudflare Free —
DNS, zone settings, Workers (cron на free есть, Worker уже работает), R2 free tier.

## 5. Риски и порядок выкатки

### Риски
1. **Удаление/пересоздание при импорте.** Опасные места: `supabase_project` (смена
   `name`/`region`/`organization_id` = replace = потеря БД), `vercel_project` (replace =
   потеря домена/настроек, новый `*.vercel.app`), DNS-записи (неверный `type`/`name` =
   delete+create, секунды без сайта), зона Cloudflare (не ресурс). Защита:
   `prevent_destroy` на project/web/bucket/repo; **каждый импорт — `terraform plan`
   без apply и чтение глазами; apply только если план содержит лишь `import` и
   ожидаемые `update in-place`** (список ожидаемых — ниже). Никогда не `-auto-approve`.
2. **Секреты в state**: `DATABASE_URL` (пароль БД), `REVALIDATE_SECRET`,
   `jwt_secret` PostgREST (приходит в `supabase_settings.api` при импорте), пароль
   Supabase, R2-пара в `.terraform/`. Смягчение: приватный бакет с токеном только на
   него; `value_wo` у Vercel env; секрет Worker’а вне Terraform; `terraform output`
   секретов `sensitive`; бэкап state в 700-папку. Terraform 1.14 не шифрует state
   (OpenTofu умеет — вариант на будущее, если захочется: совместим с этим кодом).
3. **Worker:** Terraform грузит `worker.js` как есть, а wrangler грузил esbuild-бандл →
   первый apply перезальёт код (безвредно, один-файловый ESM без импортов). Главный риск —
   **потеря `GITHUB_TOKEN` binding’а** при заливке без `keep_bindings` → cron падает, через
   ≤2 ч `watchdog.yml` откроет issue. Проверка сразу после apply: Workers → Settings →
   Variables показывает секрет; следующий `:15` запуск `Update data` появился в Actions.
   Откат: `npx wrangler@4 deploy && wrangler secret put GITHUB_TOKEN`.
4. **Secrets/env после импорта** не читаются → первый apply перезаписывает их тем же
   значением. Если `TF_VAR_revalidate_secret` введён с ошибкой — `refresh-site.sh` начнёт
   получать 401 (`::notice`, не падение), сайт перестанет обновляться. Проверка: после
   apply `curl -fsS -X POST -H "Authorization: Bearer $REVALIDATE_SECRET" https://www.anotherjudorating.com/api/revalidate`
   → `{"revalidated":"data"}`. Если `DATABASE_URL` собран не так — следующий `update.yml`
   упадёт на `pg_dump`/publish, `alert.yml` откроет issue; откат — вернуть секрет руками
   из `~/.config` (значение известно).
5. **Supabase `supabase_settings`** после импорта тянет все категории; в конфиге только
   четыре — провайдер управляет лишь заданными ключами. Риск: `database` JSON с
   неполным набором может прислать `restart_database`? Нет — поле опционально; но любое
   изменение `shared_buffers` **перезапускает Postgres** (так и CLI делает). Делать такие
   изменения ночью, не во время `update.yml` (окно между `:xx` запусками 15 минут; или
   временно выключить cron Worker’а).
6. **Rate limits**: Supabase Management API 60 req/min (plan делает ~10), Cloudflare
   1200/5 мин, GitHub 5000/ч, Vercel — не проблема. Ежедневный дрейф-план — десятки
   запросов.
7. **Провайдерские пробелы**: ruleset-поле `require_extra_approval_for_unattributed_changes`
   (вечный diff → `ignore_changes`); `vercel_project` поля, которых нет в провайдере
   (analytics) — просто не управляются; cloudflare v5 — молодые ресурсы, `cloudflare_zone_setting`
   для объектных настроек капризен — выбраны только строковые on/off.
8. **Один человек, одна машина**: state в R2 и `.env` в `~/.config` — при потере
   ноутбука инфраструктура живёт, но для apply нужны все токены заново (выпускаются за
   час); state восстановим повторным импортом (`imports.tf` в git).

### Порядок (каждый шаг — отдельный PR в `ajr-backend`, план = проверка)

| Шаг | Что | Проверка (fitness) | Откат | Оценка |
|---|---|---|---|---|
| 0 | Чеклист 1–3, 9; `terraform/` с черновиком, `terraform init` на R2; тест блокировки (два `plan` параллельно → второй падает с lock error; иначе снять `use_lockfile`); `terraform plan` с **пустым** `imports.tf` → ожидаемо «N to add» (ничего не применять) | `init` ок, объект state появился в бакете после первого `apply` шага 1 | удалить бакет; ничего не изменилось | ½ дня |
| 1 | **GitHub** (чеклист 7): import-блоки репо, ruleset, secrets, dependabot, actions permissions; `plan -target` по провайдеру | план: только `import` + ruleset rename «maun»→«main» + rewrite 2 секретов + (новый ruleset `ajr-web`, если решено); после apply: `tests.yml`/`update.yml` проходят, ruleset виден в Settings → Rules | `terraform state rm` всего GitHub (ничего не удаляется), секреты — известны | ½ дня |
| 2 | **Cloudflare** (чеклист 1–4): DNS, zone settings, Worker, cron, subdomain, бакет | план: `import` + одна перезаливка Worker’а, **0 destroy/replace** у DNS; после apply: `dig` без изменений, сайт отвечает, секрет Worker’а на месте, следующий запуск `Update data` пришёл вовремя (Actions) | `state rm` Cloudflare; Worker — `wrangler deploy` + `secret put` | ½ дня |
| 3 | **Vercel** (чеклист 6): project, 2 домена, 3 env | план: `import` + update 3 env values (+ `function_default_regions` iad1→fra1, если оставлено); после apply: `curl /api/revalidate` с секретом → 200; следующий деплой main (или Redeploy) — сайт работает, `x-vercel-id: fra1` | `state rm`; env — значения известны | 2–3 ч |
| 4 | **Supabase** (чеклист 5): project + settings (api, database, network, ssl=false как есть) | план: `import`, **0 changes** (если `instance_size` даёт diff — `ignore_changes`); `GET /postgrest` без изменений; сайт и `update.yml` работают | `state rm` (ничего не удаляется) | 2–3 ч |
| 4b | Отдельный PR: `ssl_enforcement = true` + `DATABASE_URL…?sslmode=require` одним apply; миграция role timeouts (`anon` 3s, `authenticated` 8s) через обычный release | следующий `update.yml` и `backup.yml` зелёные; Supabase advisor без «SSL not enforced»; тест на `statement_timeout` под `anon` | `ssl_enforcement=false` + apply; `alembic downgrade` | 2 ч |
| 5 | `terraform.yml`: PR-план + ежедневный дрейф → issue; Dependabot для `terraform`; `docs/infrastructure.md` (ручные тумблеры: Crawler Hints, managed robots, Web Analytics, CodeQL; где какие токены и сроки) ; README: убрать `wrangler deploy`, добавить раздел Terraform | ручная правка настройки в дашборде → на следующее утро issue «Infrastructure drifted»; откат правки → issue закрыт | удалить workflow | 2–3 ч |

Итого ≈ 2–3 рабочих дня, из них ~половина — ожидание и проверки. Шаг 1 первым: он
единственный, где нельзя ничего сломать, и он сразу чинит реальную дыру (нет ruleset
у `ajr-web`, опечатка «maun»).

## 6. Открытые вопросы владельцу

1. Secret scanning/push protection, merge-методы, allowed actions — какие значения
   сейчас (токен не прочитал)? Черновик предполагает «включено / все три / all».
2. Создавать ли ruleset для `ajr-web` в шаге 1 (required check `check`)? Рекомендация: да.
3. Ставить ли дефолт региона проекта Vercel в `fra1` (сейчас `iad1`, перекрыт
   `vercel.json`)? Рекомендация: да, одно изменение, убирает расхождение.
4. Управлять ли `GITHUB_TOKEN` Worker’а из Terraform (секрет в state) или оставить
   `wrangler secret put`? Рекомендация: оставить wrangler.
5. Нужен ли дрейф-workflow с write-токенами в GitHub secrets, или достаточно локального
   еженедельного `plan`? Рекомендация: workflow, но только после шага 4.
6. Включать ли `ssl_enforcement` сразу в шаге 4 (а не 4b)? Рекомендация: отдельно,
   чтобы импорт был «0 changes».
7. Хотите ли OpenTofu ради шифрования state (код тот же)? Пока нет оснований.

## 7. 2026-11-07: Render вместо Vercel — код в репозиториях

Сайт переехал на Render (web service `ajr-web`, `srv-dbnfcae7bikc73cdfkmg`, Frankfurt,
Starter, env `SUPABASE_URL`/`SUPABASE_KEY`/`REVALIDATE_SECRET`/`PORT`, домены
`www.anotherjudorating.com` + apex-редирект; Cloudflare по-прежнему проксирует).
Vercel-проект на паузе, удаляется ~2026-11-14 — **раздел 1.3 и `vercel.tf` черновика
устарели**, Vercel не моделируется. Vercel Analytics убран из кода; замена —
Cloudflare Web Analytics, через Terraform.

Код (ветки `terraform` в обоих репо, ничего не применено):

- `ajr-backend/infra/` — Supabase (`supabase_project` + `supabase_settings`: api,
  database, network, ssl), Cloudflare Worker `ajr-update-trigger` + cron + subdomain,
  GitHub `ajr-backend` (репо, ruleset, 2 секрета Actions, dependabot, allowed
  actions). README там же: токены, первый запуск, проверки, откат.
- `ajr-web/infra/` — Render (`render_project`, `render_web_service` с env и доменом,
  провайдер `render-oss/render ~> 1.9`), Cloudflare зона (4 DNS-записи, 5 настроек,
  `cloudflare_web_analytics_site`, `cloudflare_ruleset` cache rule на
  `/api/search-index`, `/sitemap.xml`, `/llms.txt` — §10.2 аудита 11-07), GitHub
  `ajr-web` (репо, **новый** ruleset `main` с check `check`, dependabot, allowed actions).

Отличия от плана выше:

- **Два корня вместо одного** (`infra/` в каждом репо): у каждого свой код, на
  который Terraform ссылается (`cloudflare/worker.js` здесь, сборка сайта там), свой
  PR-процесс, свои токены. Общее — `revalidate_secret` (одна переменная в обоих
  корнях из `~/.config/ajr/terraform.env`).
- **State локальный**, вне репозитория (`terraform init -backend-config=path=~/.config/ajr/tfstate/…`),
  а не R2: один оператор, apply только руками; бакет, R2-токен и блокировка не
  нужны. Бэкап `terraform state pull` перед apply. Переезд на R2 (блок из §2) —
  `init -migrate-state`, когда появится CI-план или второй оператор.
- Секрет Worker’а остаётся у `wrangler secret put` (`keep_bindings`), как
  рекомендовано в §6.4; переменная `github_dispatch_token` убрана.
- `github_actions_secret` использует `plaintext_value` (в черновике было `value`).
- Zone settings сокращены до пяти (`ssl=strict` для Render, `always_use_https`,
  `min_tls_version`, `rocket_loader`, `email_obfuscation`).

Проверено 2026-11-07 read-only: `terraform validate` в обоих корнях; `plan` с
import-блоками — Supabase (read-only токен): `2 to import, 0 to add, 0 to destroy`,
один «update in-place» у `supabase_settings` только из-за сброса в state категорий
`auth`/`storage`, которые конфиг не задаёт (провайдер пишет лишь заданные категории);
Render (настоящий ключ): `2 to import, 0 to change, 0 to destroy`, значения env
совпали. Cloudflare и GitHub без токенов — план по документации.

Чеклист владельца сокращается до: Cloudflare account/zone id + API-токен (права в
README корней), read-write токен Supabase, fine-grained PAT GitHub, пароль БД из
`DATABASE_URL`, publishable key; R2 и Vercel-токен не нужны.
