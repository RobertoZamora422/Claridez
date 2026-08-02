# Claridez

**Gestión integral para salones y espacios de eventos.**

*Gestiona con Claridez* - *Todo tu negocio, claro y bajo control.*

Claridez es una plataforma SaaS B2B privada, propietaria y multiempresa para organizar la gestión
comercial, la agenda, la operación y las finanzas de salones y espacios de eventos. Es un proyecto
nuevo y completamente independiente de RFM Core.

## Estado actual

Las Iteraciones 0–4, el flujo comercial 5.1, sus cierres 5.1.1/5.1.2 y la implementación local de
5.2 están completadas. El backend contiene identidad, sesiones, organizaciones, membresías,
autorización tenant-aware, RLS, personas, solicitudes, cotizaciones versionadas, agenda de espacio
único, reservas y preparación/ejecución operativa. La web cubre esos flujos en escritorio y móvil.

El cutover de 5.2 no se ha ejecutado sobre un entorno destino. No existen staging, producción,
proveedor productivo de correo, contratos/archivos, módulos financieros, portal ni los módulos
posteriores definidos en el Roadmap.

El destino completo del producto ya está definido; su implementación no se presume terminada:

- [Blueprint maestro del producto funcional](docs/product/PRODUCT_BLUEPRINT.md)
- [Roadmap completo de entrega](docs/product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff para continuidad](docs/PROJECT_HANDOFF.md)

La siguiente etapa es **P6 — Configuración del negocio, sedes y catálogo**. No hay una etapa
funcional activa: se debe presentar un plan breve y recibir aprobación antes de implementarla.

## Fuentes de verdad

Antes de trabajar:

1. leer [AGENTS.md](AGENTS.md);
2. leer Blueprint, Roadmap y Handoff;
3. revisar la especificación funcional y los ADR aplicables;
4. comprobar Git, código, migraciones, configuración y pruebas reales.

Los ADR aceptados gobiernan decisiones arquitectónicas. El Blueprint gobierna el destino del
producto; las especificaciones aprobadas gobiernan sus flujos exactos; el Roadmap gobierna orden y
estado; el Handoff conserva el punto de continuidad. La
[línea base v0.1](docs/product/PRODUCT_BASELINE.md) y el
[roadmap de inicialización](docs/architecture/INITIALIZATION_ROADMAP.md) permanecen como historia,
no compiten con las fuentes maestras actuales.

## Arquitectura vigente

- Monorepo y monolito modular; no se utilizan microservicios.
- Backend Django y Django REST Framework en `apps/api`.
- Frontend React, TypeScript estricto y Vite en `apps/web`.
- PostgreSQL en desarrollo, CI, staging y producción.
- API REST JSON versionada bajo `/api/v1` y OpenAPI generado/validado.
- Sesiones Django de servidor, CSRF y autorización backend-first por capacidades.
- Todo dato privado pertenece a una organización y usa aplicación tenant-aware más RLS como
  defensa en profundidad.
- Django y React/Vite se ejecutan nativamente en Windows; solo PostgreSQL está contenerizado.

Las decisiones exactas están en [docs/adr](docs/adr/README.md) y la plataforma local en
[LOCAL_PLATFORM.md](docs/architecture/LOCAL_PLATFORM.md).

## Documentación principal

- [Índice documental](docs/README.md)
- [Blueprint maestro](docs/product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](docs/product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff](docs/PROJECT_HANDOFF.md)
- [Especificación comercial 5.1](docs/product/ITERATION_5_1_COMMERCIAL_FLOW.md)
- [Cierre 5.1.1](docs/product/ITERATION_5_1_1_HARDENING.md)
- [Mantenibilidad y CI 5.1.2](docs/product/ITERATION_5_1_2_MAINTAINABILITY_CI.md)
- [Especificación operativa 5.2](docs/product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md)
- [Cutover obligatorio 5.2](docs/architecture/ITERATION_5_2_CUTOVER.md)
- [Registro de ADR](docs/adr/README.md)
- [Marca](docs/brand/README.md)
- [Contribución](CONTRIBUTING.md) y [seguridad](SECURITY.md)

## Desarrollo local

Versiones fijadas:

- Python 3.13.14 y uv 0.12.0.
- Node.js 24.18.1 y npm 11.16.0.
- Docker Desktop con Docker Compose para PostgreSQL 17.10.

Instalación reproducible desde la raíz:

```text
uv --directory apps/api sync --locked
npm ci
```

Después de crear `.env` desde `.env.example`:

```text
npm run db:start
npm run db:prepare
npm run db:migrate
npm run db:check
npm run auth:bootstrap
```

Comandos oficiales:

```text
npm run clean
npm run format
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm run check
npm run check:all
npm run audit
```

`clean` elimina únicamente cachés, cobertura, OpenAPI, builds y temporales regenerables dentro del
repositorio; acepta `--dry-run` y preserva `.git`, entornos, dependencias, `.env`, bases, secretos y
archivos del usuario. `format` modifica archivos. `check:all` añade PostgreSQL real, migraciones,
RLS y concurrencia. `audit` consulta servicios externos.

## Modelo de trabajo

1. Leer Blueprint, Roadmap y Handoff.
2. Confirmar el estado real del repositorio.
3. Identificar la siguiente etapa incompleta.
4. Presentar únicamente un plan breve y decisiones bloqueantes.
5. Recibir aprobación.
6. Implementar la etapa completa.
7. Ejecutar validaciones.
8. Actualizar Roadmap y Handoff.
9. Reportar el resultado visible.
10. Indicar exactamente la siguiente etapa.

No se exige una especificación extensa antes de cada módulo. Los ADR se reservan para decisiones
transversales, irreversibles o relacionadas con datos, seguridad, infraestructura, concurrencia o
límites arquitectónicos.

## Propiedad

Software privado y propietario. Todos los derechos reservados.
