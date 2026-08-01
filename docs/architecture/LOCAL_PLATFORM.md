# Plataforma local y configuración

- **Iteración:** 2 — Plataforma local y configuración
- **Fecha de verificación:** 31 de julio de 2026
- **Ámbito:** desarrollo local en Windows

Este documento permite reconstruir la plataforma técnica local. No define infraestructura productiva ni introduce entidades funcionales.

## Topología

```text
Windows nativo
├── Django / uv
├── React, Vite / npm
└── Docker Desktop
    └── PostgreSQL 17 en contenedor
        ├── puerto interno 5432
        ├── publicación 127.0.0.1:55432 por defecto
        └── volumen claridez_postgres17_data
```

PostgreSQL no se publica en `0.0.0.0`. La red del host solo recibe la vinculación de loopback declarada en `compose.yaml`.

## Imagen verificada

| Dato | Valor |
|---|---|
| Repositorio | Imagen oficial `postgres` |
| Tag | `17.10-bookworm` |
| Digest del índice OCI | `sha256:4f736ae292687621d4dbe0d499ffd024a36bd2ee7d8ca6f2ccd4c800f047b394` |
| Arquitectura comprobada | `linux/amd64` |
| Digest del manifiesto de arquitectura | `sha256:67870dc097790edf2bd6726658db995dcc830f799d41bb2b78ef07c9a2d5f010` |
| Fecha | 31 de julio de 2026 |

El digest fijado es el del índice oficial y Compose selecciona explícitamente `linux/amd64`. Esta imagen es exclusivamente local; no constituye una decisión de despliegue.

## Entorno observado

| Componente | Versión observada |
|---|---:|
| Docker Desktop | 4.55.0.213807 |
| Docker Compose | 2.40.3-desktop.1 |
| Docker Engine, cliente y servidor | 29.1.3 |
| PostgreSQL | 17.10, distribución Debian 17.10-1.pgdg12+1 |
| pydantic-settings | 2.14.2 |

Estas versiones documentan la ejecución realizada, pero no convierten Docker Desktop o Engine en dependencias productivas.

### Actualización controlada

1. Comprobar que el nuevo tag específico existe en el repositorio oficial.
2. Consultar el índice OCI con autenticación de lectura del registro y registrar `Docker-Content-Digest`.
3. Comprobar que el índice contiene la arquitectura requerida y registrar su digest.
4. Sustituir tag y digest conjuntamente; nunca usar `latest`, `17` ni etiquetas flotantes.
5. Ejecutar `docker compose config --quiet`, descargar la imagen y recrear el contenedor sin eliminar el volumen.
6. Repetir conexión, versión, UTC, UTF-8, healthcheck, persistencia, roles, migraciones, endpoints y pruebas.
7. Actualizar este documento y el ADR 0007 con fecha y evidencia antes de que el propietario confirme el cambio.

## Configuración versionada y local

- `.env.example`: contrato versionado, con nombres y valores no secretos.
- `.env`: configuración local ignorada; contiene secretos sintéticos generados para el equipo actual.
- `compose.yaml`: servicio, puerto, volumen, imagen y healthcheck versionados.
- Volumen y contenedor: artefactos locales administrados por Docker, nunca versionados.
- `claridez_test`: dato efímero de pruebas, creado y destruido por Django.

Para crear un `.env` nuevo, copiar el ejemplo y completar cada variable secreta con un valor independiente generado mediante un generador criptográfico. Un ejemplo de generador en PowerShell es:

```powershell
function New-ClaridezSecret {
  $bytes = [byte[]]::new(48)
  $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $generator.GetBytes($bytes)
    [Convert]::ToBase64String($bytes)
  } finally {
    $generator.Dispose()
  }
}
```

No se deben copiar esos valores a documentación, issues, logs o informes.

## Variables exactas

| Variable | Perfil | Secreta | Regla local |
|---|---|---:|---|
| `CLARIDEZ_ENVIRONMENT` | Todos | No | Exactamente `local` |
| `CLARIDEZ_SECRET_KEY` | Django | Sí | Independiente y de al menos 32 caracteres |
| `CLARIDEZ_ALLOWED_HOSTS` | Ejecución | No | Hosts locales conocidos separados por coma |
| `CLARIDEZ_LOG_LEVEL` | Ejecución | No | `DEBUG`, `INFO`, `WARNING` o `ERROR` |
| `CLARIDEZ_AUTH_LINK_BASE_URL` | Ejecución | No | Base HTTP local para enlaces de recuperación y verificación |
| `CLARIDEZ_DB_HOST` | Todos | No | Loopback; predeterminado `127.0.0.1` |
| `CLARIDEZ_DB_PORT` | Todos | No | Puerto 1–65535; predeterminado `55432` |
| `CLARIDEZ_DB_CONNECT_TIMEOUT` | Todos | No | 1–10 segundos |
| `CLARIDEZ_DB_STATEMENT_TIMEOUT_MS` | Todos | No | 100–30000 milisegundos |
| `CLARIDEZ_DB_SSLMODE` | Todos | No | `disable`, solo para loopback local |
| `CLARIDEZ_DB_NAME` | Ejecución/bootstrap | No | `claridez_local` |
| `CLARIDEZ_DB_USER` | Ejecución/bootstrap | No | `claridez_app` |
| `CLARIDEZ_DB_PASSWORD` | Ejecución/bootstrap | Sí | Credencial exclusiva de aplicación |
| `CLARIDEZ_MIGRATION_DB_USER` | Migración/bootstrap | No | `claridez_migrator` |
| `CLARIDEZ_MIGRATION_DB_PASSWORD` | Migración/bootstrap | Sí | Credencial exclusiva de migración |
| `CLARIDEZ_TEST_DB_NAME` | Pruebas/bootstrap | No | `claridez_test` |
| `CLARIDEZ_TEST_DB_USER` | Pruebas/bootstrap | No | `claridez_test_runner` |
| `CLARIDEZ_TEST_DB_PASSWORD` | Pruebas/bootstrap | Sí | Credencial exclusiva de pruebas |
| `CLARIDEZ_POSTGRES_ADMIN_DB` | Bootstrap | No | `postgres` |
| `CLARIDEZ_POSTGRES_ADMIN_USER` | Bootstrap | No | `postgres` |
| `CLARIDEZ_POSTGRES_ADMIN_PASSWORD` | Bootstrap/Compose | Sí | Uso local explícito; Django no la carga |

Una variable ausente o inválida impide cargar el perfil. El error identifica campos y tipos, pero omite valores.

## Perfiles Django

- `claridez.settings.development`: servidor local con `claridez_app`.
- `claridez.settings.migration`: `manage.py migrate` y comprobación de migraciones con `claridez_migrator`.
- `claridez.settings.test`: pytest y creación de `claridez_test` con `claridez_test_runner`.
- `BootstrapSettings`: solo `tools/local_database.py`; no es un perfil Django.

Todos usan exclusivamente `django.db.backends.postgresql`, sesiones UTC y conexiones no persistentes (`CONN_MAX_AGE=0`) en esta etapa. `TIME_ZONE` conserva `America/Guayaquil` para la presentación de Django y `USE_TZ=True` mantiene instantes conscientes de zona horaria.

Staging y producción deberán incorporar módulos separados, secretos inyectados, `DEBUG=False`, hosts explícitos, TLS y validaciones propias. No heredarán automáticamente el `.env` ni las credenciales locales.

## Roles y privilegios

| Rol | LOGIN | CREATEDB | DDL/propiedad | DML | Restricciones |
|---|---:|---:|---|---|---|
| `postgres` | Sí | Sí | Bootstrap total | Total | Solo comandos locales explícitos |
| `claridez_migrator` | Sí | No | Propietario de base/esquema; aplica migraciones | Por propiedad | Sin superusuario, CREATEROLE, REPLICATION o BYPASSRLS |
| `claridez_app` | Sí | No | Ninguno | DML aplicable; sin `DELETE` sobre `Organization`, `Membership` ni `OrganizationSettings` | Sin CREATE, propiedad, `BYPASSRLS` ni acceso a `django_migrations` |
| `claridez_test_runner` | Sí | Sí | Solo en bases de prueba que crea localmente | Total dentro de su base efímera | Sin superusuario, CREATEROLE, REPLICATION o BYPASSRLS |

El bootstrap revoca privilegios de `PUBLIC` en `claridez_local` y en su esquema. `db:migrate` ejecuta Django con el migrador y luego vuelve a aplicar los grants de objetos para la aplicación.

## Comandos oficiales

Ejecutar desde la raíz en PowerShell:

| Comando | Función |
|---|---|
| `npm run db:start` | Iniciar PostgreSQL y esperar su healthcheck |
| `npm run db:stop` | Detener PostgreSQL sin eliminar contenedor ni volumen |
| `npm run db:status` | Mostrar estado del servicio |
| `npm run db:logs` | Mostrar las últimas 200 líneas del contenedor |
| `npm run db:prepare` | Preparar idempotentemente roles, base y privilegios |
| `npm run db:check` | Comprobar versión y sesión con `claridez_app` |
| `npm run db:migrate` | Aplicar migraciones con el migrador y reconciliar DML |
| `npm run db:migrations:check` | Comprobar migraciones faltantes sin generarlas |
| `npm run api:run` | Ejecutar Django nativamente en `127.0.0.1:8000` |
| `npm run auth:bootstrap` | Crear localmente una organización activa y su primer propietario |
| `npm run test:integration` | Ejecutar pruebas marcadas contra PostgreSQL real |
| `npm run check` | Puerta reproducible sin auditorías ni integración real |
| `npm run check:all` | Añadir conexión, migraciones e integración PostgreSQL |
| `npm run db:reset -- --confirm-local-data-loss` | Recrear solo `claridez_local` y eliminar la base efímera de prueba |

Inicio nuevo recomendado:

```text
npm run db:start
npm run db:prepare
npm run db:migrate
npm run db:check
npm run auth:bootstrap
npm run check:all
```

`auth:bootstrap` solicita cualquier contraseña nueva mediante entrada oculta, aplica los
validadores de Django y no acepta contraseñas como argumento. Puede reutilizar un usuario activo,
verificado y con contraseña utilizable sin modificar `is_staff` o `is_superuser`. Cada ejecución
es idempotente para la misma organización y propietario, pero puede crear organizaciones distintas.

Los comandos de inicio, detención, estado y logs delegan en Docker Compose. Las migraciones delegan en `manage.py`. No existen `db:dump` ni `db:restore` todavía.

## Reset protegido

`db:reset` se niega sin confirmación explícita. Además valida simultáneamente entorno `local`, host loopback, nombres exactos, PostgreSQL 17, UTF-8, UTC, `cluster_name=claridez-local` y ausencia de variables que indiquen staging o producción. Solo elimina `claridez_local` y `claridez_test`; reconstruye la primera y reserva la segunda para el ciclo de pruebas.

El reset no elimina roles, contenedor, volumen ni clúster y no ejecuta `docker compose down -v`.

## Endpoints técnicos y autenticación

| Método y ruta | Éxito | Fallo | Comprobación |
|---|---|---|---|
| `GET /health` | `200 {"status":"ok"}` | No depende de PostgreSQL | Proceso Django |
| `HEAD /health` | `200`, cuerpo vacío | No depende de PostgreSQL | Proceso Django |
| `GET /ready` | `200 {"status":"ready"}` | `503 {"status":"unavailable"}` | `SELECT 1` |
| `HEAD /ready` | `200`, cuerpo vacío | `503`, cuerpo vacío | `SELECT 1` |

Readiness no expone detalles de conexión ni comprueba migraciones en cada solicitud.

La autenticación local expone bajo `/api/v1/auth/` `csrf/`, `login/`, `logout/`, `me/`,
`password/change/`, `password/reset/request/`, `password/reset/confirm/`,
`email/verification/request/` y `email/verification/confirm/`. Todos sus `POST` exigen CSRF, incluso
el login anónimo. `csrf/` entrega en JSON el valor que debe enviarse como `X-CSRFToken`; la cookie
CSRF es `HttpOnly`, por lo que el cliente no debe intentar leerla.

Las sesiones vencen exactamente ocho horas después del login. No se guardan en cada petición ni se
renuevan por actividad. Las cookies de sesión y CSRF son `HttpOnly`, `SameSite=Lax` y se marcan
`Secure` fuera de los perfiles locales y de prueba. Todas las respuestas de autenticación y salud
usan `Cache-Control: no-store`.

Desarrollo entrega correos de texto por consola; las pruebas usan memoria. Los enlaces toman la
base local no secreta `CLARIDEZ_AUTH_LINK_BASE_URL`. No existe proveedor real de correo y será
obligatorio configurarlo antes de incorporar usuarios externos.

Axes conserva intentos en PostgreSQL, bloquea después de cinco fallos por combinación de correo
canónico e IP durante 15 minutos y responde JSON `429` con `Retry-After`. Solo se usa
`REMOTE_ADDR`: no se confía en cabeceras de proxies hasta elegir y documentar el despliegue.

La API organizacional añade `GET /api/v1/organizations/`, `GET` y `POST` sobre `context/`, y las
lecturas `settings/` y `memberships/` por UUID. La selección de contexto exige CSRF, guarda solo
`last_organization_id` y no renueva el vencimiento absoluto. No existen endpoints privilegiados de
escritura.

`organizations_organizationsettings` pertenece a `claridez_migrator`, aplica `ENABLE` y `FORCE ROW
LEVEL SECURITY` y no devuelve filas sin el GUC local establecido por `authorized_tenant_scope`.
Las migraciones de datos futuras deben iterar organizaciones dentro de transacciones explícitas,
establecer `set_config('claridez.organization_id', ..., true)` para cada operación y materializar
todo antes de cambiar el contexto. El migrador participa en la misma política y no debe desactivar
RLS silenciosamente.

## Datos y recuperación

El volumen sobrevive a detener y recrear el contenedor. Esto no sustituye una copia de seguridad. Los procedimientos de dump, restore, retención y recuperación se definirán cuando existan datos funcionales y objetivos reales de recuperación.

## Evidencia de salida

- `docker compose config --quiet` validó la definición sin imprimir variables expandidas.
- El contenedor alcanzó el estado `healthy` y Docker confirmó `127.0.0.1:55432` como única publicación.
- El identificador físico del clúster permaneció igual después de forzar la recreación del contenedor.
- La conexión normal informó `claridez_app`, PostgreSQL 17.10, UTF-8 y UTC.
- El migrador pudo ejecutar DDL técnico; la aplicación pudo hacer el DML autorizado y recibió
  `InsufficientPrivilege` al intentar DDL o eliminar organizaciones y membresías.
- Django creó `claridez_test` con `claridez_test_runner` y la destruyó al terminar la suite.
- `/health` permaneció en 200 con PostgreSQL detenido; `/ready` pasó de 200 a 503 y volvió a 200 al reiniciarlo.
- Las pruebas rápidas, la integración PostgreSQL, `check`, `check:all` y ambas auditorías completaron correctamente.

Las migraciones propias `identity/0001_initial.py` y `organizations/0001_initial.py`, además de las
migraciones estándar de sesiones y Axes, se aplican con `claridez_migrator`.
`organizations/0002_organizationsettings.py` realiza el backfill, crea la función mínima del GUC,
los grants y la política RLS. El rol normal recibe solo el DML requerido, pero no propiedad, DDL,
`BYPASSRLS` ni `DELETE` sobre las tres tablas organizacionales.
