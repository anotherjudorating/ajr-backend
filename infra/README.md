# Terraform: бэкенд Another Judo Rating

Один root module, одно окружение (production), локальный state. Ничего из этого
ещё не применено: первый `plan` с import-блоками ниже — проверка, `apply` делает
владелец руками. План и обоснования: `docs/audits/2026-11-06-terraform-plan.md`
(раздел «2026-11-07: Render вместо Vercel» — про нынешнюю раскладку).

## Что здесь управляется

| Система | Ресурсы | Файл |
|---|---|---|
| Supabase, проект `vrnpqahtpjrlmlrkzbja` | `supabase_project` (prevent_destroy), `supabase_settings`: Data API (`db_schema=api`, `max_rows=1000`, extra search path), postgres-override `shared_buffers=64MB`, network restrictions, `ssl_enforcement` | `supabase.tf` |
| Cloudflare, аккаунт | Worker `ajr-update-trigger` (код из `../cloudflare/worker.js`, var `GITHUB_REPO`), 3 cron-расписания, `workers.dev` выключен | `cloudflare.tf` |
| GitHub, репо `ajr-backend` | настройки репо, ruleset на `main` (переименование «maun» → «main», required check `tests`), Actions-секреты `DATABASE_URL` и `REVALIDATE_SECRET`, Dependabot security updates, allowed actions, secret scanning | `github.tf` |

Хостинг сайта (Render, DNS зоны, Web Analytics, cache rules, репо `ajr-web`) —
в `ajr-web/infra/`. Два корня, потому что у каждого репо свой код, который
Terraform грузит или на который ссылается (`cloudflare/worker.js` здесь, сборка
сайта там), свой PR-процесс и свои токены; общее у них только `REVALIDATE_SECRET`
(одна переменная в обоих корнях, см. «Секреты»).

**Остаётся вне Terraform и почему:**

- Всё внутри Postgres (схемы, `api.*`, гранты, `alter role … set statement_timeout`)
  — Alembic (`release.yml`); Terraform объектов БД не видит.
- Секрет Worker’а `GITHUB_TOKEN` — `wrangler secret put` (ротация раз в год, как в
  `cloudflare/README.md`); `keep_bindings = ["secret_text"]` сохраняет его при
  заливке кода. Так токен не попадает в state.
- Dependabot version updates (`.github/dependabot.yml`), workflows — код.
- CodeQL default setup, «default workflow permissions», org settings — у провайдера
  нет ресурса или он тянет лишнее; дашборд.
- Бэкапы Supabase (free: ежедневный WAL-G, расписания нет), апгрейд Postgres, Auth
  (сайт без пользователей), pooler, storage — дефолты, не трогаем.
- Vercel: проект на паузе, удаляется ~2026-11-14; не моделируется. После удаления
  там ничего не останется, в коде сайта `vercel.json` можно убрать.

## Токены и права (минимум)

| Переменная | Где взять | Права |
|---|---|---|
| `TF_VAR_supabase_access_token` | supabase.com/dashboard/account/tokens → Generate new token «terraform» | read-write (нынешний в `~/.config/ajr/supabase.env` — read-only, им можно только `plan`) |
| `TF_VAR_cloudflare_api_token` | My Profile → API Tokens → Create Custom Token | **Account › Workers Scripts › Edit**, **Account › Account Settings › Read**; Account Resources: только свой аккаунт. Если один токен на оба корня — добавить права из `ajr-web/infra/README.md` |
| `TF_VAR_cloudflare_account_id` | Dashboard → любая зона → Overview → API → Account ID | не секрет |
| `TF_VAR_github_token` | Settings → Developer settings → Fine-grained tokens | Resource owner `anotherjudorating`, репо `ajr-backend` (+ `ajr-web`, если токен общий); Repository permissions: **Administration: RW**, **Secrets: RW**, **Variables: RW**, **Contents: R** (Metadata: R добавится). Срок ≤ 1 год, запись в календарь. Нынешний `github-dispatch.env` (только Actions RW) для apply не годится |
| `TF_VAR_supabase_database_password` | пароль внутри нынешнего `DATABASE_URL` (Settings → Database показывает только «reset» — **не сбрасывать**) | — |
| `TF_VAR_revalidate_secret` | `~/.config/ajr/revalidate.env` | — |

## Секреты: как текут

Значения — только через переменные окружения `TF_VAR_*` (или git-ignored
`terraform.tfvars`, см. `terraform.tfvars.example`). Удобно завести
`~/.config/ajr/terraform.env` (chmod 600):

```sh
# ~/.config/ajr/terraform.env — общий для обоих корней
export TF_VAR_cloudflare_account_id=…
export TF_VAR_cloudflare_zone_id=…           # нужен ajr-web/infra
export TF_VAR_cloudflare_api_token=…
export TF_VAR_github_token=…
export TF_VAR_supabase_access_token=…        # read-write, не тот, что в supabase.env
export TF_VAR_supabase_database_password=…
export TF_VAR_supabase_publishable_key=…     # нужен ajr-web/infra
. ~/.config/ajr/revalidate.env; export TF_VAR_revalidate_secret="$REVALIDATE_SECRET"
. ~/.config/ajr/render.env;     export TF_VAR_render_api_key="$RENDER_API_KEY"   # ajr-web/infra
```

Одна переменная `revalidate_secret` питает Actions-секрет здесь и env Render’а в
`ajr-web/infra`: ротация = новое значение в `terraform.env` + apply в обоих корнях.
`DATABASE_URL` собирается из `data.supabase_pooler` (session mode 5432,
`postgresql+psycopg://`) и пароля — формат README бэкенда.

**State.** Локальный, лежит вне репозитория (путь задаётся при `init`), в git не
попадает (`*.tfstate*` в `.gitignore`). В нём — пароль БД, `DATABASE_URL`,
`REVALIDATE_SECRET`, `jwt_secret` PostgREST. Почему не R2/S3 и не HCP Terraform:
один оператор, одна машина, apply только руками — удалённый бэкенд добавил бы бакет,
токен и блокировку, которые никому не нужны; HCP Terraform положил бы те же секреты
к третьей стороне. Бэкап перед каждым apply: `terraform state pull > ~/.config/ajr/tfstate/backup/ajr-backend-$(date +%F).json`
(каталог 700). Переезд позже (если появится второй оператор или CI-план): блок
`backend "s3"` для R2 из плана 11-06 + `terraform init -migrate-state`.

## Первый запуск

```sh
set -a; . ~/.config/ajr/terraform.env; set +a
cd ~/Projects/anotherjudorating/ajr-backend/infra
mkdir -p ~/.config/ajr/tfstate/backup && chmod 700 ~/.config/ajr/tfstate
terraform init -backend-config="endpoints={s3=\"https://$TF_VAR_cloudflare_account_id.r2.cloudflarestorage.com\"}"   # state in R2 (ajr-terraform-state)
terraform plan -out=import.plan            # только чтение; все import-блоки сразу
```

Ожидаемый план (проверено 2026-11-07 read-only токеном Supabase; Cloudflare и
GitHub без токенов — ожидание по документации):

- `11 to import`, `0 to add`, `0 to destroy`.
- `supabase_project`: без изменений. `supabase_settings`: «update in-place» только
  потому, что импорт приносит `auth`/`storage`/`pooler`, которых в конфиге нет —
  провайдер обновляет лишь заданные категории (`api`, `database`, `network`,
  `ssl_enforcement`), а они совпадают: запросов на запись не будет.
- `github_repository_ruleset.main`: `name: "maun" → "main"`. Два
  `github_actions_secret`: значение не читается → перезапись тем же значением.
  `github_repository`: возможны расхождения merge-настроек и secret scanning
  (токен-разведчик их не прочитал) — либо принять, либо скопировать реальные
  значения в `github.tf`.
- `cloudflare_workers_script`: одна перезаливка кода (wrangler грузил
  esbuild-бандл, Terraform грузит `worker.js` как есть; файл — один ESM-модуль без
  импортов, безвредно). Cron и subdomain — без изменений.

Если план показывает **destroy/replace чего угодно** — не применять, разобраться.
Применение (только владелец, по провайдерам, чтобы откат был локальным):

```sh
terraform apply -target=github_repository.backend -target=github_repository_ruleset.main \
  -target=github_actions_secret.database_url -target=github_actions_secret.revalidate_secret \
  -target=github_repository_dependabot_security_updates.backend -target=github_actions_repository_permissions.backend
terraform apply -target=cloudflare_workers_script.update_trigger -target=cloudflare_workers_cron_trigger.update_trigger \
  -target=cloudflare_workers_script_subdomain.update_trigger
terraform apply                             # Supabase и всё остальное
```

## Проверка после apply

- GitHub: `tests.yml` на следующем PR зелёный; Settings → Rules показывает «main».
  `curl -fsS -X POST -H "Authorization: Bearer $REVALIDATE_SECRET" https://www.anotherjudorating.com/api/revalidate`
  → `{"revalidated":"data"}` (значит, секрет тот же, что на Render). Следующий
  `update.yml` прошёл (`DATABASE_URL` собран верно; иначе `alert.yml` откроет issue).
- Cloudflare: Workers → `ajr-update-trigger` → Settings → Variables: `GITHUB_TOKEN`
  на месте; следующий запуск `:15` «Update data» появился в Actions.
- Supabase: `GET /v1/projects/{ref}/postgrest` не изменился; сайт отвечает.

## Откат

- GitHub/Supabase: `terraform state rm <адрес>` — ничего не удаляется, объект просто
  перестаёт быть под Terraform; секреты известны, вернуть руками в Settings.
- Worker: `cd cloudflare && npx wrangler@4 deploy && npx wrangler@4 secret put GITHUB_TOKEN`
  (`cloudflare/README.md`), затем `terraform state rm` трёх ресурсов Worker’а.
- `shared_buffers` или `ssl_enforcement` — вернуть прежнее значение в `.tf` и
  apply (перезапуск Postgres; делать между запусками `update.yml`).

## Что дальше (отдельными PR, после импорта)

1. `ssl_enforcement = true` + `database_url = "…?sslmode=require"` одним apply;
   миграция role timeouts (`anon` 3s, `authenticated` 8s) — обычный release.
2. `cloudflare/README.md`: убрать `wrangler deploy` (деплой кода — `terraform apply`),
   оставить `wrangler secret put` и `wrangler dev`.
3. Дрейф-план в Actions (черновик в плане 11-06, §3.2) — только когда захочется
   класть read-only токены в secrets репо.


## State в R2 (с 2026-11-08)

State лежит в приватном бакете R2 `ajr-terraform-state` (ключ `backend/terraform.tfstate`,
блокировка — объект рядом, `use_lockfile`). Доступ — отдельный R2 API token (Object Read & Write
только на этот бакет) в `~/.config/ajr/terraform.env`: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
Перенос с локального файла был одной командой (`terraform init -migrate-state` с той же
`-backend-config`); локальные файлы в `~/.config/ajr/tfstate/` остались резервной копией.
