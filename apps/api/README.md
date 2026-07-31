# API de Claridez

Esqueleto técnico de la API REST de Claridez. En la Iteración 2 incorpora configuración local validada, perfiles de credenciales separados, PostgreSQL real y los endpoints técnicos `/health` y `/ready`.

Contiene el usuario local productivo de 4.1 y las organizaciones y membresías globales de control
de 4.2. No contiene todavía autorización del actor, datos privados tenant ni modelos funcionales de
negocio.

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

## Identidad local

`claridez.identity.User` es el usuario intercambiable de Django. Utiliza UUIDv4, correo completo
canónico y único, `display_name`, estado coherente con `is_active`, versión de seguridad y marcas
`created_at`/`updated_at`. La migración inicial está en
`src/claridez/identity/migrations/0001_initial.py`.

La aplicación no incorpora todavía RLS, serializers, vistas, URLs de autenticación, recuperación,
correo, cookies, `django-axes` ni expiración absoluta de sesiones. Django Admin permanece
deshabilitado y sin URL.

## Organizaciones y membresías

`claridez.organizations` contiene `Organization` y `Membership` como tablas globales sin RLS. La
creación y las transiciones pasan por servicios transaccionales que bloquean primero la
organización y después la membresía para proteger al último propietario. La relación entre usuario
y organización es única y persistente.

Después de migrar, `npm run auth:bootstrap` permite crear localmente una organización activa y su
primer propietario sin conceder privilegios técnicos.

## OpenAPI

`drf-spectacular` genera `openapi-schema.yaml` únicamente como artefacto temporal de comprobación. El archivo está ignorado y no debe editarse. El contrato OpenAPI se versionará cuando existan endpoints funcionales aprobados.

## Evidencia del spike de tenancy

El código y los scripts ejecutables de la Iteración 3 fueron eliminados en 4.0. Se conservan el
[protocolo](../../docs/architecture/TENANCY_SPIKE_PROTOCOL.md), los
[resultados](../../docs/architecture/TENANCY_SPIKE_RESULTS.md) y el
[modelo de amenazas](../../docs/security/TENANCY_SPIKE_THREAT_MODEL.md) como evidencia histórica.
ADR 0009 acepta aplicación tenant-aware más RLS sin convertir el experimento en implementación
productiva.
