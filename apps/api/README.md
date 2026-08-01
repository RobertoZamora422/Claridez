# API de Claridez

API REST de Claridez con configuración local validada, perfiles de credenciales separados,
PostgreSQL real, endpoints técnicos de salud y autenticación HTTP mediante sesiones Django.

Contiene el usuario local productivo, organizaciones y membresías globales de control, autorización
backend-first, `OrganizationSettings` y el módulo funcional `claridez.commercial`, todos los datos
privados con RLS.

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

## Endpoints técnicos y funcionales

- `/health` confirma únicamente que Django responde.
- `/ready` ejecuta `SELECT 1` y responde de forma genérica.

El flujo comercial vive bajo `/api/v1/organizations/{organization_id}/` y expone personas,
solicitudes, disponibilidad, cotizaciones/versiones y comandos explícitos de emisión, aceptación,
cierre, confirmación y cancelación. El contrato exacto está en la
[especificación 5.1](../../docs/product/ITERATION_5_1_COMMERCIAL_FLOW.md).

## Autenticación HTTP

Los endpoints de 4.3 viven bajo `/api/v1/auth/`:

| Método | Ruta |
|---|---|
| `GET` | `csrf/` |
| `POST` | `login/` |
| `POST` | `logout/` |
| `GET` | `me/` |
| `POST` | `password/change/` |
| `POST` | `password/reset/request/` |
| `POST` | `password/reset/confirm/` |
| `POST` | `email/verification/request/` |
| `POST` | `email/verification/confirm/` |

Todos los `POST`, incluido `login/`, requieren el token obtenido en `csrf/` mediante
`X-CSRFToken`. Las sesiones tienen un vencimiento absoluto de ocho horas sin renovación por
actividad. Las respuestas usan `Cache-Control: no-store`; `me/` expone solo el usuario global, sin
organización, membresías ni capacidades.

## Identidad local

`claridez.identity.User` es el usuario intercambiable de Django. Utiliza UUIDv4, correo completo
canónico y único, `display_name`, estado coherente con `is_active`, versión de seguridad y marcas
`created_at`/`updated_at`. La migración inicial está en
`src/claridez/identity/migrations/0001_initial.py`.

La recuperación de contraseña usa las primitivas de Django y la verificación usa un token separado.
En desarrollo el correo se entrega por consola y en pruebas se conserva en memoria. No hay
proveedor productivo. `django-axes` limita a cinco fallos por combinación de correo canónico e IP,
con enfriamiento de 15 minutos y sin confiar en cabeceras de proxy. Django Admin permanece
deshabilitado y sin URL.

## Organizaciones y membresías

`claridez.organizations` contiene `Organization` y `Membership` como tablas globales sin RLS. La
creación y las transiciones pasan por servicios transaccionales que bloquean primero la
organización y después la membresía para proteger al último propietario. La relación entre usuario
y organización es única y persistente.

Después de migrar, `npm run auth:bootstrap` permite crear localmente una organización activa y su
primer propietario sin conceder privilegios técnicos.

El catálogo cerrado contiene las siete capacidades de infraestructura de ADR 0011 y las ocho
capacidades funcionales de 5.1, sin jerarquías implícitas. `authorized_tenant_scope` revalida actor,
organización, membresía y capacidad dentro de
una transacción y establece el GUC local únicamente durante la operación. Los servicios autorizados
materializan sus resultados antes de cerrar el scope.

`OrganizationSettings` contiene solo moneda y zona horaria. Su tabla aplica `ENABLE` y `FORCE ROW
LEVEL SECURITY`, una política simétrica `USING`/`WITH CHECK` y cierre por defecto sin contexto. El
rol de aplicación no es propietario, no tiene `BYPASSRLS` ni `DELETE` sobre la tabla.

Los endpoints organizacionales de infraestructura siguen limitados al listado,
consulta/selección de contexto y lectura de settings y membresías. Las mutaciones funcionales se
limitan al contrato comercial 5.1 y no habilitan administración privilegiada de membresías.

## OpenAPI

`drf-spectacular` genera y valida `openapi-schema.yaml` como artefacto temporal ignorado. El esquema
incluye autenticación, operaciones organizacionales y el contrato comercial 5.1, pero todavía no
se publica ni genera un cliente TypeScript.

## Evidencia del spike de tenancy

El código y los scripts ejecutables de la Iteración 3 fueron eliminados en 4.0. Se conservan el
[protocolo](../../docs/architecture/TENANCY_SPIKE_PROTOCOL.md), los
[resultados](../../docs/architecture/TENANCY_SPIKE_RESULTS.md) y el
[modelo de amenazas](../../docs/security/TENANCY_SPIKE_THREAT_MODEL.md) como evidencia histórica.
ADR 0009 gobierna la implementación productiva independiente; el experimento eliminado no fue
restaurado ni importado.
