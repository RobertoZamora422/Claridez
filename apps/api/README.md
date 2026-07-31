# API de Claridez

Esqueleto técnico de la API REST de Claridez. En la Iteración 2 incorpora configuración local validada, perfiles de credenciales separados, PostgreSQL real y los endpoints técnicos `/health` y `/ready`.

No contiene aplicaciones funcionales, modelos, migraciones, usuarios del dominio ni reglas multiempresa productivas.

## Requisitos

- Python 3.13.14.
- uv 0.12.0.
- Las dependencias fijadas en `pyproject.toml` y `uv.lock`.

PostgreSQL 17.10 se ejecuta mediante el `compose.yaml` raíz. Django continúa ejecutándose nativamente en Windows.

## Instalación reproducible

Desde la raíz del repositorio:

```text
uv --directory apps/api sync --locked
```

## Configuración técnica

Los perfiles son:

- `claridez.settings.development`: ejecución normal con `claridez_app`.
- `claridez.settings.migration`: migraciones con `claridez_migrator`.
- `claridez.settings.test`: pruebas con `claridez_test_runner` y PostgreSQL real.

`pydantic-settings` valida las variables requeridas desde el `.env` local ignorado. Los errores no incluyen valores. La guía completa se encuentra en [la plataforma local](../../docs/architecture/LOCAL_PLATFORM.md).

## Endpoints

- `/health` confirma únicamente que Django responde.
- `/ready` ejecuta `SELECT 1` y responde de forma genérica.

No existen endpoints de negocio.

## OpenAPI

`drf-spectacular` genera `openapi-schema.yaml` únicamente como artefacto temporal de comprobación. El archivo está ignorado y no debe editarse. El contrato OpenAPI se versionará cuando existan endpoints funcionales aprobados.
