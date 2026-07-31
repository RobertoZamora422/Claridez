# API de Claridez

Esqueleto técnico de la API REST de Claridez. En la Iteración 1 contiene únicamente la configuración necesaria para validar Django, Django REST Framework, PostgreSQL como backend exclusivo y la generación técnica de OpenAPI.

No contiene aplicaciones funcionales, modelos, migraciones, usuarios del dominio ni reglas multiempresa productivas.

## Requisitos

- Python 3.13.14.
- uv 0.12.0.
- Las dependencias fijadas en `pyproject.toml` y `uv.lock`.

PostgreSQL 17 es la versión objetivo, pero no se instala ni se conecta durante esta iteración.

## Instalación reproducible

Desde la raíz del repositorio:

```text
uv --directory apps/api sync --locked
```

## Configuración técnica

Los comandos automatizados utilizan `claridez.settings.test`. Esta configuración declara exclusivamente el backend PostgreSQL, pero las pruebas bootstrap y las comprobaciones no abren una conexión.

`claridez.settings.development` exige `CLARIDEZ_SECRET_KEY`. La configuración validada y los secretos locales se completarán en la Iteración 2.

## OpenAPI

`drf-spectacular` genera `openapi-schema.yaml` únicamente como artefacto temporal de comprobación. El archivo está ignorado y no debe editarse. El contrato OpenAPI se versionará cuando existan endpoints funcionales aprobados.
